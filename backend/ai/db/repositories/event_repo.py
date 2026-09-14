"""Security event repository for PostgreSQL persistence.

Uses session-per-operation pattern. No shared AsyncSession.
Includes ON CONFLICT for safe upserts.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai.events.engine import SecurityEvent
from ai.db.models import SecurityEventModel
from ai.db.repositories.base import db_operation


class EventRepository:
    """Async CRUD for security_events table with per-operation sessions."""

    def _to_event(self, model: SecurityEventModel) -> SecurityEvent:
        return SecurityEvent(
            event_id=model.event_id,
            event_type=model.event_type,
            severity=model.severity,
            camera_id=model.camera_id,
            zone_id=model.zone_id or "",
            zone_name=model.zone_name or "",
            track_id=model.track_id,
            object_class=model.object_class,
            timestamp=model.timestamp.isoformat() if model.timestamp else "",
            confidence=model.confidence,
            bbox=model.bbox if isinstance(model.bbox, dict) else {},
            status=model.status,
        )

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

    async def create(self, event: SecurityEvent) -> Optional[SecurityEvent]:
        """Insert a new event. Uses ON CONFLICT DO NOTHING for safety."""
        async def _create(session):
            stmt = pg_insert(SecurityEventModel).values(
                event_id=event.event_id,
                event_type=event.event_type,
                severity=event.severity,
                camera_id=event.camera_id,
                zone_id=event.zone_id if event.zone_id else None,
                zone_name=event.zone_name,
                track_id=event.track_id,
                object_class=event.object_class,
                timestamp=self._parse_timestamp(event.timestamp),
                confidence=event.confidence,
                bbox=event.bbox,
                status=event.status,
            ).on_conflict_do_nothing(index_elements=["event_id"])
            await session.execute(stmt)
            await session.flush()
            return event
        return await db_operation("event.create", _create)

    async def get(self, event_id: str) -> Optional[SecurityEvent]:
        async def _get(session):
            result = await session.execute(
                select(SecurityEventModel).where(SecurityEventModel.event_id == event_id)
            )
            model = result.scalar_one_or_none()
            return self._to_event(model) if model else None
        return await db_operation("event.get", _get)

    async def list_for_camera(self, camera_id: str, limit: int = 100) -> List[SecurityEvent]:
        async def _list(session):
            result = await session.execute(
                select(SecurityEventModel)
                .where(SecurityEventModel.camera_id == camera_id)
                .order_by(SecurityEventModel.timestamp.desc())
                .limit(limit)
            )
            return [self._to_event(m) for m in result.scalars().all()]
        return await db_operation("event.list_camera", _list) or []

    async def update_status(self, event_id: str, status: str) -> bool:
        """Update an existing event's status (e.g. DETECTED -> ACTIVE -> RESOLVED)."""
        async def _update(session):
            result = await session.execute(
                update(SecurityEventModel)
                .where(SecurityEventModel.event_id == event_id)
                .values(status=status)
            )
            return result.rowcount > 0
        return await db_operation("event.update_status", _update) or False
