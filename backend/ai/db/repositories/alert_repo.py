"""Alert repository for PostgreSQL persistence.

Uses session-per-operation pattern. No shared AsyncSession.
Includes ON CONFLICT for safe upserts.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai.db.models import AlertModel
from ai.db.repositories.base import db_operation


class AlertRepository:
    """Async CRUD for alerts table with per-operation sessions."""

    def _to_dict(self, model: AlertModel) -> dict:
        return {
            "id": model.alert_id,
            "timestamp": model.timestamp.isoformat() if model.timestamp else "",
            "cameraId": model.camera_id,
            "eventType": model.event_type,
            "title": model.title,
            "severity": model.severity,
            "trackId": model.track_id,
            "confidence": model.confidence,
            "zone": model.zone,
            "reason": model.reason,
            "status": model.status,
            "source": model.source,
        }

    def _parse_timestamp(self, ts) -> datetime:
        """Convert ISO string or datetime to datetime object."""
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str) and ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        return datetime.now(timezone.utc)

    async def create(self, alert: dict) -> Optional[dict]:
        """Insert a new alert. Uses ON CONFLICT DO NOTHING for safety."""
        async def _create(session):
            ts = self._parse_timestamp(alert.get("timestamp", ""))
            stmt = pg_insert(AlertModel).values(
                alert_id=alert.get("id", ""),
                camera_id=alert.get("cameraId", ""),
                timestamp=ts,
                event_type=alert.get("eventType", ""),
                title=alert.get("title", ""),
                severity=alert.get("severity", "MEDIUM"),
                track_id=alert.get("trackId"),
                confidence=alert.get("confidence"),
                zone=alert.get("zone"),
                reason=alert.get("reason"),
                status=alert.get("status", "ACTIVE"),
                source=alert.get("source", "AI"),
            ).on_conflict_do_nothing(index_elements=["alert_id"])
            await session.execute(stmt)
            await session.flush()
            return alert
        return await db_operation("alert.create", _create)

    async def get(self, alert_id: str) -> Optional[dict]:
        async def _get(session):
            result = await session.execute(
                select(AlertModel).where(AlertModel.alert_id == alert_id)
            )
            model = result.scalar_one_or_none()
            return self._to_dict(model) if model else None
        return await db_operation("alert.get", _get)

    async def list_for_camera(self, camera_id: str, limit: int = 100) -> List[dict]:
        async def _list(session):
            result = await session.execute(
                select(AlertModel)
                .where(AlertModel.camera_id == camera_id)
                .order_by(AlertModel.timestamp.desc())
                .limit(limit)
            )
            return [self._to_dict(m) for m in result.scalars().all()]
        return await db_operation("alert.list_camera", _list) or []

    async def list_recent(self, limit: int = 50) -> List[dict]:
        async def _list(session):
            result = await session.execute(
                select(AlertModel)
                .order_by(AlertModel.timestamp.desc())
                .limit(limit)
            )
            return [self._to_dict(m) for m in result.scalars().all()]
        return await db_operation("alert.list_recent", _list) or []

    async def update_status(self, alert_id: str, status: str) -> bool:
        """Update an existing alert's status."""
        async def _update(session):
            result = await session.execute(
                update(AlertModel)
                .where(AlertModel.alert_id == alert_id)
                .values(status=status)
            )
            return result.rowcount > 0
        return await db_operation("alert.update_status", _update) or False
