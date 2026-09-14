"""Zone repository for PostgreSQL persistence.

Uses session-per-operation pattern. No shared AsyncSession.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select, update

from ai.events.engine import Zone
from ai.db.models import ZoneModel
from ai.db.repositories.base import db_operation


class ZoneRepository:
    """Async CRUD for zones table with per-operation sessions."""

    def _to_zone(self, model: ZoneModel) -> Zone:
        return Zone(
            id=model.id,
            camera_id=model.camera_id,
            name=model.name,
            points=model.points if isinstance(model.points, list) else [],
            enabled=model.enabled,
            severity=model.severity,
        )

    async def create(self, zone: Zone) -> Optional[Zone]:
        async def _create(session):
            model = ZoneModel(
                id=zone.id,
                camera_id=zone.camera_id,
                name=zone.name,
                points=zone.points,
                enabled=zone.enabled,
                severity=zone.severity,
            )
            session.add(model)
            await session.flush()
            return self._to_zone(model)
        return await db_operation("zone.create", _create)

    async def get(self, zone_id: str) -> Optional[Zone]:
        async def _get(session):
            result = await session.execute(
                select(ZoneModel).where(ZoneModel.id == zone_id)
            )
            model = result.scalar_one_or_none()
            return self._to_zone(model) if model else None
        return await db_operation("zone.get", _get)

    async def list_for_camera(self, camera_id: str) -> List[Zone]:
        async def _list(session):
            result = await session.execute(
                select(ZoneModel).where(ZoneModel.camera_id == camera_id)
            )
            return [self._to_zone(m) for m in result.scalars().all()]
        return await db_operation("zone.list_camera", _list) or []

    async def list_all(self) -> List[Zone]:
        async def _list(session):
            result = await session.execute(select(ZoneModel))
            return [self._to_zone(m) for m in result.scalars().all()]
        return await db_operation("zone.list_all", _list) or []

    async def update(self, zone_id: str, **fields) -> Optional[Zone]:
        async def _update(session):
            fields["updated_at"] = datetime.now(timezone.utc)
            protected = {"id", "created_at"}
            update_fields = {k: v for k, v in fields.items() if k not in protected}
            if not update_fields:
                return await self.get(zone_id)
            await session.execute(
                update(ZoneModel)
                .where(ZoneModel.id == zone_id)
                .values(**update_fields)
            )
            await session.flush()
            return await self.get(zone_id)
        return await db_operation("zone.update", _update)

    async def delete(self, zone_id: str) -> bool:
        async def _delete(session):
            result = await session.execute(
                delete(ZoneModel).where(ZoneModel.id == zone_id)
            )
            return result.rowcount > 0
        return await db_operation("zone.delete", _delete) or False

    async def delete_for_camera(self, camera_id: str) -> int:
        async def _delete(session):
            result = await session.execute(
                delete(ZoneModel).where(ZoneModel.camera_id == camera_id)
            )
            return result.rowcount
        return await db_operation("zone.delete_camera", _delete) or 0
