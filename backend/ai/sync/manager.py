"""SyncManager — background store-and-forward synchronization worker.

Periodically inspects the sync queue, attempts to push pending items to the
central server, and handles retry with exponential backoff. Tolerates
database/network failures without crashing the AI pipeline.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from ai.config import settings
from ai.db.repositories.sync_repo import SyncQueueRepository
from ai.evidence.store import EvidenceStore
from ai.sync.client import CentralSyncClient

logger = logging.getLogger("ibvap.sync")


class SyncManager:
    """Background worker that synchronizes local events/evidence to central server."""

    def __init__(
        self,
        sync_repo: SyncQueueRepository,
        evidence_store: Optional[EvidenceStore],
        audit_repo,
        central_client: CentralSyncClient,
        network_health=None,
    ):
        self._sync_repo = sync_repo
        self._evidence_store = evidence_store
        self._audit_repo = audit_repo
        self._client = central_client
        self._network_health = network_health
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._connectivity = "OFFLINE"
        self._last_success: Optional[str] = None
        self._last_failure: Optional[str] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background sync loop."""
        if not settings.SYNC_ENABLED:
            print("[SYNC] Sync disabled via SYNC_ENABLED=false")
            return

        # Self-referencing detection: CENTRAL_API_URL points to this server
        from urllib.parse import urlparse
        parsed = urlparse(settings.CENTRAL_API_URL)
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host in ("localhost", "127.0.0.1", "0.0.0.0") and port == 8000:
            print("[SYNC] Self-referencing detected: CENTRAL_API_URL=%s" % settings.CENTRAL_API_URL)
            print("[SYNC] No separate central server configured — sync disabled in standalone mode")
            print("[SYNC] To enable sync, set CENTRAL_API_URL to a real central server address")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        print("[SYNC] Background sync worker started (interval=%ds)" % settings.SYNC_INTERVAL_SEC)

    async def stop(self):
        """Stop the sync loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        await self._client.close()
        print("[SYNC] Background sync worker stopped")

    async def _run_loop(self):
        """Main sync loop — runs periodically."""
        while self._running:
            try:
                await self._check_connectivity()
                if self._connectivity != "OFFLINE":
                    await self.run_sync_pass()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[SYNC] Loop iteration failed: %s", e)

            try:
                await asyncio.sleep(settings.SYNC_INTERVAL_SEC)
            except asyncio.CancelledError:
                break

    async def _cleanup_loop(self):
        """Periodically clean up old synced items."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # check hourly
                if self._sync_repo and settings.SYNC_CLEANUP_DAYS > 0:
                    deleted = await self._sync_repo.cleanup_synced(settings.SYNC_CLEANUP_DAYS)
                    if deleted > 0:
                        print("[SYNC] Cleaned up %d old synced items" % deleted)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[SYNC] Cleanup failed: %s", e)

    async def _check_connectivity(self):
        """Check central server reachability.

        If NetworkHealthManager is available, defer to it (it drives the state).
        Otherwise, fall back to direct health check.
        """
        if self._network_health:
            # NetworkHealthManager drives the state — just read it
            self._connectivity = self._network_health.state.value
            return

        # Fallback: direct health check (no hysteresis)
        try:
            ok = await self._client.health_check()
            old_state = self._connectivity
            if ok:
                self._connectivity = "CONNECTED"
                if old_state in ("OFFLINE", "DEGRADED"):
                    print("[SYNC] Central server reachable — state: %s -> CONNECTED" % old_state)
            else:
                if self._connectivity == "CONNECTED":
                    self._connectivity = "DEGRADED"
                    print("[SYNC] Central server unreachable — state: CONNECTED -> DEGRADED")
                elif self._connectivity != "DEGRADED":
                    self._connectivity = "OFFLINE"
        except Exception:
            if self._connectivity == "CONNECTED":
                self._connectivity = "DEGRADED"

    async def run_sync_pass(self) -> dict:
        """Execute one synchronization pass. Returns stats."""
        if not self._sync_repo:
            return {"processed": 0, "synced": 0, "failed": 0}

        pending = await self._sync_repo.get_pending(limit=settings.SYNC_BATCH_SIZE)
        if not pending:
            return {"processed": 0, "synced": 0, "failed": 0}

        # Claim items
        sync_ids = [item["syncId"] for item in pending]
        claimed = await self._sync_repo.claim(sync_ids)
        if claimed == 0:
            return {"processed": 0, "synced": 0, "failed": 0}

        # Process claimed items (use original list, not re-fetch)
        synced = 0
        failed = 0
        for item in pending[:claimed]:
            try:
                ok = await self._process_item(item)
                if ok:
                    synced += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning("[SYNC] Failed to process %s: %s", item.get("syncId"), e)
                failed += 1

        now = datetime.now(timezone.utc).isoformat()
        if synced > 0:
            self._last_success = now
        if failed > 0:
            self._last_failure = now

        return {"processed": len(pending), "synced": synced, "failed": failed}

    async def _process_item(self, item: dict) -> bool:
        """Synchronize a single queue item. Returns True on success."""
        sync_id = item["syncId"]
        entity_type = item["entityType"]
        entity_id = item["entityId"]
        payload = item.get("payload") or {}
        attempt = item.get("attemptCount", 0)

        if entity_type == "EVENT":
            result = await self._client.push_event(payload, sync_id)
        elif entity_type == "EVIDENCE":
            # Push metadata first
            result = await self._client.push_evidence_metadata(payload, sync_id)
            if result.success and self._evidence_store:
                # Then push file
                file_path = payload.get("filePath", "")
                expected_hash = payload.get("sha256Hash", "")
                if file_path and self._evidence_store.exists(file_path):
                    file_bytes = self._evidence_store.load(file_path)
                    file_result = await self._client.push_evidence_file(
                        entity_id, file_bytes, expected_hash, sync_id
                    )
                    if not file_result.success:
                        result = file_result
        else:
            logger.warning("[SYNC] Unknown entity_type: %s", entity_type)
            return False

        if result.success:
            await self._sync_repo.mark_synced(sync_id)
            await self._audit_log("sync.succeeded", entity_type, entity_id, {"sync_id": sync_id})
            return True
        elif result.retryable:
            next_retry = self._compute_next_retry(attempt)
            await self._sync_repo.mark_failed(sync_id, result.error or "unknown", next_retry)
            return False
        else:
            # Non-retryable failure — mark as failed with max error
            await self._sync_repo.mark_failed(
                sync_id, "non_retryable: %s" % (result.error or "unknown")
            )
            await self._audit_log(
                "sync.failed", entity_type, entity_id,
                {"sync_id": sync_id, "error": result.error, "retryable": False},
            )
            return False

    def _compute_next_retry(self, attempt_count: int) -> datetime:
        """Compute next retry time using bounded exponential backoff."""
        delay = settings.SYNC_BACKOFF_BASE_SEC * (2 ** attempt_count)
        delay = min(delay, settings.SYNC_BACKOFF_MAX_SEC)
        return datetime.now(timezone.utc) + timedelta(seconds=delay)

    async def _audit_log(self, action: str, entity_type: str, entity_id: str, details: dict = None):
        """Fire-and-forget audit log."""
        try:
            if self._audit_repo:
                await self._audit_repo.log(
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    details=details,
                    actor="SYNC_WORKER",
                )
        except Exception:
            pass

    async def enqueue_event(self, event_id: str, event_payload: dict) -> bool:
        """Enqueue an event for synchronization. Called from pipeline."""
        if not settings.SYNC_ENABLED or not self._sync_repo:
            return False
        try:
            result = await self._sync_repo.enqueue(
                entity_type="EVENT",
                entity_id=event_id,
                operation="CREATE",
                payload=event_payload,
            )
            return result is not None
        except Exception as e:
            logger.warning("[SYNC] Failed to enqueue event %s: %s", event_id, e)
            return False

    async def enqueue_evidence(self, evidence_id: str, evidence_payload: dict) -> bool:
        """Enqueue evidence for synchronization. Called from pipeline."""
        if not settings.SYNC_ENABLED or not self._sync_repo:
            return False
        try:
            result = await self._sync_repo.enqueue(
                entity_type="EVIDENCE",
                entity_id=evidence_id,
                operation="CREATE",
                payload=evidence_payload,
            )
            return result is not None
        except Exception as e:
            logger.warning("[SYNC] Failed to enqueue evidence %s: %s", evidence_id, e)
            return False

    def get_status(self) -> dict:
        """Return current sync status for API endpoint."""
        return {
            "state": self._connectivity,
            "enabled": settings.SYNC_ENABLED,
            "lastSuccessAt": self._last_success,
            "lastFailureAt": self._last_failure,
        }
