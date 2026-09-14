"""Sync queue repository for store-and-forward persistence.

Uses session-per-operation pattern. Idempotent inserts via ON CONFLICT.
"""

import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy import select, update, delete, func

from ai.db.models import SyncQueueModel
from ai.db.repositories.base import db_operation


class SyncQueueRepository:
    """Async CRUD for sync_queue table with per-operation sessions."""

    async def enqueue(
        self,
        entity_type: str,
        entity_id: str,
        operation: str = "CREATE",
        payload: dict = None,
    ) -> Optional[dict]:
        """Enqueue an item for synchronization. Idempotent on entity_type+entity_id."""
        async def _enqueue(session):
            # Check if already queued
            existing = await session.execute(
                select(SyncQueueModel).where(
                    SyncQueueModel.entity_type == entity_type,
                    SyncQueueModel.entity_id == entity_id,
                    SyncQueueModel.status.in_(["PENDING", "IN_PROGRESS", "FAILED"]),
                )
            )
            if existing.scalar_one_or_none():
                return None  # Already queued

            sync_id = "SYNC-" + secrets.token_hex(8)
            item = SyncQueueModel(
                sync_id=sync_id,
                entity_type=entity_type,
                entity_id=entity_id,
                operation=operation,
                status="PENDING",
                attempt_count=0,
                payload=payload,
            )
            session.add(item)
            await session.flush()
            return self._to_dict(item)

        return await db_operation("sync.enqueue", _enqueue)

    async def get_pending(self, limit: int = 20) -> List[dict]:
        """Get pending or failed items ready for retry."""
        async def _get_pending(session):
            now = datetime.now(timezone.utc)
            result = await session.execute(
                select(SyncQueueModel).where(
                    SyncQueueModel.status.in_(["PENDING", "FAILED"]),
                    (
                        (SyncQueueModel.next_retry_at.is_(None))
                        | (SyncQueueModel.next_retry_at <= now)
                    ),
                ).order_by(SyncQueueModel.created_at.asc()).limit(limit)
            )
            return [self._to_dict(m) for m in result.scalars().all()]
        return await db_operation("sync.get_pending", _get_pending) or []

    async def claim(self, sync_ids: List[str]) -> int:
        """Mark items as IN_PROGRESS. Returns count claimed."""
        async def _claim(session):
            if not sync_ids:
                return 0
            now = datetime.now(timezone.utc)
            result = await session.execute(
                update(SyncQueueModel)
                .where(
                    SyncQueueModel.sync_id.in_(sync_ids),
                    SyncQueueModel.status.in_(["PENDING", "FAILED"]),
                )
                .values(
                    status="IN_PROGRESS",
                    last_attempt_at=now,
                    attempt_count=SyncQueueModel.attempt_count + 1,
                )
            )
            return result.rowcount
        return await db_operation("sync.claim", _claim) or 0

    async def mark_synced(self, sync_id: str) -> bool:
        """Mark an item as successfully synchronized."""
        async def _mark(session):
            now = datetime.now(timezone.utc)
            result = await session.execute(
                update(SyncQueueModel)
                .where(SyncQueueModel.sync_id == sync_id)
                .values(status="SYNCED", synced_at=now)
            )
            return result.rowcount > 0
        return await db_operation("sync.mark_synced", _mark) or False

    async def mark_failed(self, sync_id: str, error: str, next_retry_at: datetime = None) -> bool:
        """Mark an item as failed with error and optional retry time."""
        async def _mark(session):
            result = await session.execute(
                update(SyncQueueModel)
                .where(SyncQueueModel.sync_id == sync_id)
                .values(
                    status="FAILED",
                    last_error=error,
                    next_retry_at=next_retry_at,
                )
            )
            return result.rowcount > 0
        return await db_operation("sync.mark_failed", _mark) or False

    async def count_by_status(self) -> dict:
        """Count items grouped by status."""
        async def _count(session):
            result = await session.execute(
                select(SyncQueueModel.status, func.count(SyncQueueModel.sync_id))
                .group_by(SyncQueueModel.status)
            )
            counts = {row[0]: row[1] for row in result.all()}
            return {
                "PENDING": counts.get("PENDING", 0),
                "IN_PROGRESS": counts.get("IN_PROGRESS", 0),
                "FAILED": counts.get("FAILED", 0),
                "SYNCED": counts.get("SYNCED", 0),
            }
        return await db_operation("sync.count_by_status", _count) or {
            "PENDING": 0, "IN_PROGRESS": 0, "FAILED": 0, "SYNCED": 0,
        }

    async def get_recent_synced(self, limit: int = 10) -> List[dict]:
        """Get recently synced items for status display."""
        async def _list(session):
            result = await session.execute(
                select(SyncQueueModel)
                .where(SyncQueueModel.status == "SYNCED")
                .order_by(SyncQueueModel.synced_at.desc())
                .limit(limit)
            )
            return [self._to_dict(m) for m in result.scalars().all()]
        return await db_operation("sync.get_recent_synced", _list) or []

    async def cleanup_synced(self, older_than_days: int = 30) -> int:
        """Delete synced items older than N days. Returns count deleted."""
        async def _cleanup(session):
            cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
            result = await session.execute(
                delete(SyncQueueModel).where(
                    SyncQueueModel.status == "SYNCED",
                    SyncQueueModel.synced_at < cutoff,
                )
            )
            return result.rowcount
        return await db_operation("sync.cleanup", _cleanup) or 0

    def _to_dict(self, model: SyncQueueModel) -> dict:
        return {
            "syncId": model.sync_id,
            "entityType": model.entity_type,
            "entityId": model.entity_id,
            "operation": model.operation,
            "status": model.status,
            "attemptCount": model.attempt_count,
            "lastAttemptAt": model.last_attempt_at.isoformat() if model.last_attempt_at else None,
            "nextRetryAt": model.next_retry_at.isoformat() if model.next_retry_at else None,
            "lastError": model.last_error,
            "payload": model.payload,
            "createdAt": model.created_at.isoformat() if model.created_at else None,
            "syncedAt": model.synced_at.isoformat() if model.synced_at else None,
        }
