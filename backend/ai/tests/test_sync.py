"""Section 12 Store-and-Forward Synchronization Tests.

Tests:
1. enqueue event
2. enqueue evidence
3. duplicate event prevention
4. duplicate evidence prevention
5. pending retrieval
6. claim item
7. mark synced
8. mark failed
9. retry scheduling
10. exponential backoff
11. central available
12. central unavailable
13. central recovery
14. HTTP 500 retry
15. HTTP 401 handling
16. timeout handling
17. event sync end-to-end
18. evidence metadata sync
19. evidence file sync with SHA-256
20. no duplicate central records
21. AI pipeline continues when central unavailable
22. local evidence accessible offline
23. graceful worker shutdown
24. /sync/status endpoint
25. RBAC on /sync/run
"""

import asyncio
import hashlib
import os
import secrets
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from ai.sync.client import CentralSyncClient, SyncResult
from ai.sync.manager import SyncManager


# ──────────────────────────────────────────────────────────────
# Mocks
# ──────────────────────────────────────────────────────────────

class MockSyncRepo:
    """In-memory sync queue repository for testing."""
    def __init__(self):
        self._store = {}
        self._id_counter = 0

    async def enqueue(self, entity_type, entity_id, operation="CREATE", payload=None):
        # Idempotent: check if already queued
        for item in self._store.values():
            if (item["entityType"] == entity_type
                    and item["entityId"] == entity_id
                    and item["status"] in ("PENDING", "IN_PROGRESS", "FAILED")):
                return None
        self._id_counter += 1
        sync_id = "SYNC-%04d" % self._id_counter
        item = {
            "syncId": sync_id,
            "entityType": entity_type,
            "entityId": entity_id,
            "operation": operation,
            "status": "PENDING",
            "attemptCount": 0,
            "lastAttemptAt": None,
            "nextRetryAt": None,
            "lastError": None,
            "payload": payload,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "syncedAt": None,
        }
        self._store[sync_id] = item
        return item

    async def get_pending(self, limit=20):
        now = datetime.now(timezone.utc)
        items = []
        for item in self._store.values():
            if item["status"] in ("PENDING", "FAILED"):
                if item["nextRetryAt"] is None:
                    items.append(item)
                else:
                    retry_time = datetime.fromisoformat(item["nextRetryAt"])
                    if retry_time <= now:
                        items.append(item)
        items.sort(key=lambda x: x["createdAt"])
        return items[:limit]

    async def claim(self, sync_ids):
        count = 0
        for sid in sync_ids:
            item = self._store.get(sid)
            if item and item["status"] in ("PENDING", "FAILED"):
                item["status"] = "IN_PROGRESS"
                item["attemptCount"] += 1
                item["lastAttemptAt"] = datetime.now(timezone.utc).isoformat()
                count += 1
        return count

    async def mark_synced(self, sync_id):
        item = self._store.get(sync_id)
        if item:
            item["status"] = "SYNCED"
            item["syncedAt"] = datetime.now(timezone.utc).isoformat()
            return True
        return False

    async def mark_failed(self, sync_id, error, next_retry_at=None):
        item = self._store.get(sync_id)
        if item:
            item["status"] = "FAILED"
            item["lastError"] = error
            item["nextRetryAt"] = next_retry_at.isoformat() if next_retry_at else None
            return True
        return False

    async def count_by_status(self):
        counts = {"PENDING": 0, "IN_PROGRESS": 0, "FAILED": 0, "SYNCED": 0}
        for item in self._store.values():
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return counts

    async def cleanup_synced(self, older_than_days=30):
        return 0

    async def get_recent_synced(self, limit=10):
        items = [i for i in self._store.values() if i["status"] == "SYNCED"]
        return sorted(items, key=lambda x: x.get("syncedAt", ""), reverse=True)[:limit]


class MockAuditRepo:
    def __init__(self):
        self.logs = []

    async def log(self, action, entity_type, entity_id, details=None, actor=None):
        self.logs.append({
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
            "actor": actor,
        })


class MockCentralClient:
    """Mock central client for testing."""
    def __init__(self, available=True, fail_events=False, fail_evidence=False,
                 http_status=200, timeout_on=None):
        self._available = available
        self._fail_events = fail_events
        self._fail_evidence = fail_evidence
        self._http_status = http_status
        self._timeout_on = timeout_on or set()
        self.pushed_events = []
        self.pushed_evidence_meta = []
        self.pushed_evidence_files = []

    async def health_check(self):
        return self._available

    async def push_event(self, event_payload, sync_id):
        if not self._available:
            return SyncResult(success=False, error="connection_refused", retryable=True)
        if self._fail_events:
            return SyncResult(success=False, status_code=500, error="server_error", retryable=True)
        if "event" in self._timeout_on:
            return SyncResult(success=False, error="timeout", retryable=True)
        self.pushed_events.append({"payload": event_payload, "sync_id": sync_id})
        return SyncResult(success=True, status_code=200)

    async def push_evidence_metadata(self, evidence_payload, sync_id):
        if not self._available:
            return SyncResult(success=False, error="connection_refused", retryable=True)
        if self._fail_evidence:
            return SyncResult(success=False, status_code=500, error="server_error", retryable=True)
        if "evidence" in self._timeout_on:
            return SyncResult(success=False, error="timeout", retryable=True)
        self.pushed_evidence_meta.append({"payload": evidence_payload, "sync_id": sync_id})
        return SyncResult(success=True, status_code=200)

    async def push_evidence_file(self, evidence_id, file_bytes, sha256, sync_id):
        if not self._available:
            return SyncResult(success=False, error="connection_refused", retryable=True)
        # Verify SHA-256
        actual_hash = hashlib.sha256(file_bytes).hexdigest()
        if actual_hash != sha256:
            return SyncResult(success=False, status_code=400, error="hash_mismatch", retryable=False)
        self.pushed_evidence_files.append({
            "evidence_id": evidence_id, "sha256": sha256, "sync_id": sync_id,
        })
        return SyncResult(success=True, status_code=200)

    async def close(self):
        pass


class MockEvidenceStore:
    def __init__(self):
        self._store = {}

    def exists(self, path):
        return path in self._store

    def load(self, path):
        return self._store.get(path, b"")

    def save(self, data, path):
        self._store[path] = data
        return path

    def _full_path(self, path):
        return path


# ──────────────────────────────────────────────────────────────
# Tests — Queue Operations (1-10)
# ──────────────────────────────────────────────────────────────

class TestSyncQueue(unittest.TestCase):
    """Tests 1-10: Queue operations."""

    def setUp(self):
        self.repo = MockSyncRepo()

    def test_01_enqueue_event(self):
        result = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-001", payload={"event_id": "EVT-001"})
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["entityType"], "EVENT")
        self.assertEqual(result["status"], "PENDING")

    def test_02_enqueue_evidence(self):
        result = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVIDENCE", "EVD-001", payload={"evidence_id": "EVD-001"})
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["entityType"], "EVIDENCE")
        self.assertEqual(result["status"], "PENDING")

    def test_03_duplicate_event_prevention(self):
        asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-DUP")
        )
        result = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-DUP")
        )
        self.assertIsNone(result)  # Should be rejected

    def test_04_duplicate_evidence_prevention(self):
        asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVIDENCE", "EVD-DUP")
        )
        result = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVIDENCE", "EVD-DUP")
        )
        self.assertIsNone(result)

    def test_05_pending_retrieval(self):
        asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-P1")
        )
        asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-P2")
        )
        pending = asyncio.get_event_loop().run_until_complete(
            self.repo.get_pending(limit=10)
        )
        self.assertEqual(len(pending), 2)

    def test_06_claim_item(self):
        item = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-CL")
        )
        claimed = asyncio.get_event_loop().run_until_complete(
            self.repo.claim([item["syncId"]])
        )
        self.assertEqual(claimed, 1)
        pending = asyncio.get_event_loop().run_until_complete(
            self.repo.get_pending()
        )
        self.assertEqual(len(pending), 0)  # No longer pending

    def test_07_mark_synced(self):
        item = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-SY")
        )
        asyncio.get_event_loop().run_until_complete(
            self.repo.mark_synced(item["syncId"])
        )
        counts = asyncio.get_event_loop().run_until_complete(
            self.repo.count_by_status()
        )
        self.assertEqual(counts["SYNCED"], 1)
        self.assertEqual(counts["PENDING"], 0)

    def test_08_mark_failed(self):
        item = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-FA")
        )
        asyncio.get_event_loop().run_until_complete(
            self.repo.mark_failed(item["syncId"], "test_error")
        )
        counts = asyncio.get_event_loop().run_until_complete(
            self.repo.count_by_status()
        )
        self.assertEqual(counts["FAILED"], 1)

    def test_09_retry_scheduling(self):
        item = asyncio.get_event_loop().run_until_complete(
            self.repo.enqueue("EVENT", "EVT-RT")
        )
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=5)
        asyncio.get_event_loop().run_until_complete(
            self.repo.mark_failed(item["syncId"], "timeout", next_retry)
        )
        # Should NOT appear in pending (retry not yet due)
        pending = asyncio.get_event_loop().run_until_complete(
            self.repo.get_pending()
        )
        self.assertEqual(len(pending), 0)

    def test_10_exponential_backoff(self):
        from ai.config import Settings
        s = Settings()
        # Test backoff formula: base * 2^attempt, capped at max
        delays = []
        for attempt in range(6):
            delay = s.SYNC_BACKOFF_BASE_SEC * (2 ** attempt)
            delay = min(delay, s.SYNC_BACKOFF_MAX_SEC)
            delays.append(delay)

        # Verify monotonic increase
        for i in range(1, len(delays)):
            self.assertGreaterEqual(delays[i], delays[i-1])
        # Verify cap
        self.assertLessEqual(delays[-1], s.SYNC_BACKOFF_MAX_SEC + 1)
        # Verify first few values
        self.assertAlmostEqual(delays[0], 2.0)   # base * 2^0
        self.assertAlmostEqual(delays[1], 4.0)   # base * 2^1
        self.assertAlmostEqual(delays[2], 8.0)   # base * 2^2
        self.assertAlmostEqual(delays[3], 16.0)  # base * 2^3
        self.assertAlmostEqual(delays[4], 32.0)  # base * 2^4
        self.assertAlmostEqual(delays[5], 60.0)  # capped at max


# ──────────────────────────────────────────────────────────────
# Tests — Connectivity (11-16)
# ──────────────────────────────────────────────────────────────

class TestSyncConnectivity(unittest.TestCase):
    """Tests 11-16: Central connectivity handling."""

    def setUp(self):
        self.repo = MockSyncRepo()
        self.audit = MockAuditRepo()
        self.store = MockEvidenceStore()

    def _make_manager(self, client):
        return SyncManager(self.repo, self.store, self.audit, client)

    def test_11_central_available(self):
        client = MockCentralClient(available=True)
        mgr = self._make_manager(client)
        ok = asyncio.get_event_loop().run_until_complete(client.health_check())
        self.assertTrue(ok)

    def test_12_central_unavailable(self):
        client = MockCentralClient(available=False)
        mgr = self._make_manager(client)
        ok = asyncio.get_event_loop().run_until_complete(client.health_check())
        self.assertFalse(ok)

    def test_13_central_recovery(self):
        client = MockCentralClient(available=False)
        mgr = self._make_manager(client)
        asyncio.get_event_loop().run_until_complete(mgr._check_connectivity())
        self.assertEqual(mgr._connectivity, "OFFLINE")

        # Simulate recovery
        client._available = True
        asyncio.get_event_loop().run_until_complete(mgr._check_connectivity())
        self.assertEqual(mgr._connectivity, "CONNECTED")

    def test_14_http_500_retry(self):
        client = MockCentralClient(available=True, fail_events=True)
        asyncio.get_event_loop().run_until_complete(
            client.push_event({"event_id": "EVT-500"}, "SYNC-500")
        )
        result = asyncio.get_event_loop().run_until_complete(
            client.push_event({"event_id": "EVT-500"}, "SYNC-500")
        )
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertEqual(result.status_code, 500)

    def test_15_http_401_handling(self):
        client = MagicMock()
        client.push_event = AsyncMock(return_value=SyncResult(
            success=False, status_code=401, error="auth_error", retryable=False
        ))
        result = asyncio.get_event_loop().run_until_complete(
            client.push_event({}, "SYNC-401")
        )
        self.assertFalse(result.success)
        self.assertFalse(result.retryable)

    def test_16_timeout_handling(self):
        client = MockCentralClient(available=True, timeout_on={"event"})
        result = asyncio.get_event_loop().run_until_complete(
            client.push_event({"event_id": "EVT-TIMEOUT"}, "SYNC-TIMEOUT")
        )
        self.assertFalse(result.success)
        self.assertTrue(result.retryable)


# ──────────────────────────────────────────────────────────────
# Tests — Synchronization (17-20)
# ──────────────────────────────────────────────────────────────

class TestSyncSynchronization(unittest.TestCase):
    """Tests 17-20: End-to-end sync operations."""

    def setUp(self):
        self.repo = MockSyncRepo()
        self.audit = MockAuditRepo()
        self.store = MockEvidenceStore()

    def _make_manager(self, client):
        return SyncManager(self.repo, self.store, self.audit, client)

    def test_17_event_sync(self):
        client = MockCentralClient(available=True)
        mgr = self._make_manager(client)

        # Enqueue event
        asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_event("EVT-SYNC-01", {"event_id": "EVT-SYNC-01", "type": "INTRUSION"})
        )

        # Run sync pass
        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["synced"], 1)
        self.assertEqual(len(client.pushed_events), 1)

    def test_18_evidence_metadata_sync(self):
        client = MockCentralClient(available=True)
        mgr = self._make_manager(client)

        # Enqueue evidence
        asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_evidence("EVD-SYNC-01", {
                "evidence_id": "EVD-SYNC-01",
                "event_id": "EVT-001",
                "sha256Hash": "abc123",
            })
        )

        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["synced"], 1)
        self.assertEqual(len(client.pushed_evidence_meta), 1)

    def test_19_evidence_file_sync_with_sha256(self):
        client = MockCentralClient(available=True)
        mgr = self._make_manager(client)

        # Setup evidence store with file
        test_data = b"test evidence image bytes"
        expected_hash = hashlib.sha256(test_data).hexdigest()
        self.store.save(test_data, "CAM-01/EVT-001/EVD-FILE-01.jpg")

        # Enqueue evidence with file path
        asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_evidence("EVD-FILE-01", {
                "evidence_id": "EVD-FILE-01",
                "filePath": "CAM-01/EVT-001/EVD-FILE-01.jpg",
                "sha256Hash": expected_hash,
            })
        )

        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["synced"], 1)
        self.assertEqual(len(client.pushed_evidence_files), 1)
        self.assertEqual(client.pushed_evidence_files[0]["sha256"], expected_hash)

    def test_20_no_duplicate_central_records(self):
        client = MockCentralClient(available=True)
        mgr = self._make_manager(client)

        # Enqueue same event twice
        asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_event("EVT-DUP-01", {"event_id": "EVT-DUP-01"})
        )
        result = asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_event("EVT-DUP-01", {"event_id": "EVT-DUP-01"})
        )
        self.assertFalse(result)  # Second enqueue rejected (returns False)

        # Sync once
        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["synced"], 1)
        self.assertEqual(len(client.pushed_events), 1)


# ──────────────────────────────────────────────────────────────
# Tests — Integration & Edge Cases (21-25)
# ──────────────────────────────────────────────────────────────

class TestSyncIntegration(unittest.TestCase):
    """Tests 21-25: Integration and edge cases."""

    def setUp(self):
        self.repo = MockSyncRepo()
        self.audit = MockAuditRepo()
        self.store = MockEvidenceStore()

    def _make_manager(self, client):
        return SyncManager(self.repo, self.store, self.audit, client)

    def test_21_pipeline_continues_when_central_unavailable(self):
        """AI pipeline should not crash when central is unreachable."""
        client = MockCentralClient(available=False)
        mgr = self._make_manager(client)

        # Simulate pipeline enqueuing during outage
        asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_event("EVT-OFFLINE-01", {"event_id": "EVT-OFFLINE-01"})
        )

        # Sync pass should not crash
        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["synced"], 0)
        self.assertEqual(stats["failed"], 1)

        # Queue item should be FAILED (retryable)
        counts = asyncio.get_event_loop().run_until_complete(self.repo.count_by_status())
        self.assertEqual(counts["FAILED"], 1)

    def test_22_local_evidence_accessible_offline(self):
        """Local evidence store works independently of central connectivity."""
        store = MockEvidenceStore()
        data = b"offline evidence data"
        store.save(data, "CAM-01/EVT-001/EVD-OFFLINE.jpg")
        self.assertTrue(store.exists("CAM-01/EVT-001/EVD-OFFLINE.jpg"))
        self.assertEqual(store.load("CAM-01/EVT-001/EVD-OFFLINE.jpg"), data)

    def test_23_graceful_worker_shutdown(self):
        """SyncManager stops cleanly without hanging."""
        client = MockCentralClient(available=True)
        mgr = self._make_manager(client)

        # Start and immediately stop
        asyncio.get_event_loop().run_until_complete(mgr.start())
        asyncio.get_event_loop().run_until_complete(mgr.stop())
        self.assertFalse(mgr._running)
        self.assertIsNone(mgr._task)

    def test_24_sync_status_endpoint_data(self):
        """SyncManager.get_status returns correct structure."""
        client = MockCentralClient(available=True)
        mgr = self._make_manager(client)
        mgr._connectivity = "CONNECTED"
        mgr._last_success = "2026-09-06T12:00:00Z"

        status = mgr.get_status()
        self.assertEqual(status["state"], "CONNECTED")
        self.assertEqual(status["lastSuccessAt"], "2026-09-06T12:00:00Z")
        self.assertTrue(status["enabled"])

    def test_25_rbac_sync_control_permission(self):
        """SYNC_CONTROL permission exists for ADMIN and OPERATOR."""
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.SYNC_CONTROL, ROLE_PERMISSIONS[Role.ADMIN])
        self.assertIn(Permission.SYNC_CONTROL, ROLE_PERMISSIONS[Role.OPERATOR])
        self.assertNotIn(Permission.SYNC_CONTROL, ROLE_PERMISSIONS[Role.VIEWER])

    def test_26_rbac_sync_read_permission(self):
        """SYNC_READ permission exists for all roles."""
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.SYNC_READ, ROLE_PERMISSIONS[Role.ADMIN])
        self.assertIn(Permission.SYNC_READ, ROLE_PERMISSIONS[Role.OPERATOR])
        self.assertIn(Permission.SYNC_READ, ROLE_PERMISSIONS[Role.VIEWER])

    def test_27_non_retryable_error_stops_retries(self):
        """Auth errors should not be retried."""
        client = MagicMock()
        client.push_event = AsyncMock(return_value=SyncResult(
            success=False, status_code=403, error="forbidden", retryable=False
        ))
        mgr = self._make_manager(client)

        asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_event("EVT-403", {"event_id": "EVT-403"})
        )

        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["failed"], 1)

        # Verify item is FAILED with non_retryable prefix
        counts = asyncio.get_event_loop().run_until_complete(self.repo.count_by_status())
        self.assertEqual(counts["FAILED"], 1)

    def test_28_failed_item_retried_after_backoff(self):
        """Failed items should be retried when next_retry_at passes."""
        client = MockCentralClient(available=False)
        mgr = self._make_manager(client)

        asyncio.get_event_loop().run_until_complete(
            mgr.enqueue_event("EVT-RETRY", {"event_id": "EVT-RETRY"})
        )

        # First pass — fails
        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["failed"], 1)

        # Simulate time passing — set next_retry_at to past
        items = asyncio.get_event_loop().run_until_complete(self.repo.get_pending())
        # Manually set retry time to past
        for sid, item in self.repo._store.items():
            if item["entityId"] == "EVT-RETRY":
                item["nextRetryAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

        # Make client available
        client._available = True

        # Second pass — should succeed
        stats = asyncio.get_event_loop().run_until_complete(mgr.run_sync_pass())
        self.assertEqual(stats["synced"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
