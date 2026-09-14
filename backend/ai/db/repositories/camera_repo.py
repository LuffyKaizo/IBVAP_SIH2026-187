"""Camera repository for PostgreSQL persistence.

Uses session-per-operation pattern. No shared AsyncSession.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai.camera.config import CameraConfig
from ai.db.models import CameraModel
from ai.db.repositories.base import db_operation, is_db_available


class CameraRepository:
    """Async CRUD for cameras table with per-operation sessions."""

    def _to_config(self, model: CameraModel) -> CameraConfig:
        return CameraConfig(
            camera_id=model.camera_id,
            name=model.name,
            location=model.location,
            source=model.source,
            source_type=model.source_type,
            camera_type=model.camera_type,
            enabled=model.enabled,
            sd_card_capable=model.sd_card_capable if model.sd_card_capable is not None else False,
            sd_card_status=model.sd_card_status or "UNKNOWN",
            sd_card_capacity_gb=model.sd_card_capacity_gb,
            last_sync_at=model.last_sync_at.isoformat() if model.last_sync_at else None,
            pending_footage_count=model.pending_footage_count or 0,
            last_offline_at=model.last_offline_at.isoformat() if model.last_offline_at else None,
            last_online_at=model.last_online_at.isoformat() if model.last_online_at else None,
            created_at=model.created_at.isoformat() if model.created_at else "",
            updated_at=model.updated_at.isoformat() if model.updated_at else "",
        )

    async def create(self, config: CameraConfig) -> Optional[CameraConfig]:
        async def _create(session):
            model = CameraModel(
                camera_id=config.camera_id,
                name=config.name,
                location=config.location,
                source=config.source,
                source_type=config.source_type,
                camera_type=config.camera_type,
                enabled=config.enabled,
                sd_card_capable=config.sd_card_capable,
                sd_card_status=config.sd_card_status,
                sd_card_capacity_gb=config.sd_card_capacity_gb,
                pending_footage_count=config.pending_footage_count,
            )
            session.add(model)
            await session.flush()
            return self._to_config(model)
        return await db_operation("camera.create", _create)

    async def get(self, camera_id: str) -> Optional[CameraConfig]:
        async def _get(session):
            result = await session.execute(
                select(CameraModel).where(CameraModel.camera_id == camera_id)
            )
            model = result.scalar_one_or_none()
            return self._to_config(model) if model else None
        return await db_operation("camera.get", _get)

    async def list_all(self) -> List[CameraConfig]:
        async def _list(session):
            result = await session.execute(
                select(CameraModel).order_by(CameraModel.created_at)
            )
            return [self._to_config(m) for m in result.scalars().all()]
        return await db_operation("camera.list", _list) or []

    async def list_enabled(self) -> List[CameraConfig]:
        async def _list(session):
            result = await session.execute(
                select(CameraModel)
                .where(CameraModel.enabled == True)
                .order_by(CameraModel.created_at)
            )
            return [self._to_config(m) for m in result.scalars().all()]
        return await db_operation("camera.list_enabled", _list) or []

    async def update(self, camera_id: str, **fields) -> Optional[CameraConfig]:
        async def _update(session):
            protected = {"camera_id", "created_at"}
            update_fields = {k: v for k, v in fields.items() if k not in protected}
            if not update_fields:
                return await self.get(camera_id)
            update_fields["updated_at"] = datetime.now(timezone.utc)
            await session.execute(
                update(CameraModel)
                .where(CameraModel.camera_id == camera_id)
                .values(**update_fields)
            )
            await session.flush()
            # Read back
            result = await session.execute(
                select(CameraModel).where(CameraModel.camera_id == camera_id)
            )
            model = result.scalar_one_or_none()
            return self._to_config(model) if model else None
        return await db_operation("camera.update", _update)

    async def delete(self, camera_id: str) -> bool:
        async def _delete(session):
            result = await session.execute(
                delete(CameraModel).where(CameraModel.camera_id == camera_id)
            )
            return result.rowcount > 0
        return await db_operation("camera.delete", _delete) or False

    async def exists(self, camera_id: str) -> bool:
        async def _exists(session):
            result = await session.execute(
                select(CameraModel.camera_id).where(CameraModel.camera_id == camera_id)
            )
            return result.scalar_one_or_none() is not None
        return await db_operation("camera.exists", _exists) or False

    async def count(self) -> int:
        async def _count(session):
            result = await session.execute(select(CameraModel))
            return len(result.scalars().all())
        return await db_operation("camera.count", _count) or 0

    async def count_enabled(self) -> int:
        async def _count(session):
            result = await session.execute(
                select(CameraModel).where(CameraModel.enabled == True)
            )
            return len(result.scalars().all())
        return await db_operation("camera.count_enabled", _count) or 0
