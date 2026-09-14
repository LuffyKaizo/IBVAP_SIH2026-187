"""User/profile repository for PostgreSQL persistence.

Uses session-per-operation pattern. No shared AsyncSession.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select, update

from ai.db.models import ProfileModel
from ai.db.repositories.base import db_operation, is_db_available


class UserRepository:
    """Async CRUD for profiles table with per-operation sessions."""

    async def get_by_email(self, email: str) -> Optional[ProfileModel]:
        async def _get(session):
            result = await session.execute(
                select(ProfileModel).where(ProfileModel.email == email)
            )
            return result.scalar_one_or_none()
        return await db_operation("user.get_by_email", _get)

    async def get_by_id(self, user_id: str) -> Optional[ProfileModel]:
        async def _get(session):
            result = await session.execute(
                select(ProfileModel).where(ProfileModel.user_id == user_id)
            )
            return result.scalar_one_or_none()
        return await db_operation("user.get_by_id", _get)

    async def create(self, user_id: str, email: str, password_hash: str,
                     full_name: str = None, role: str = "VIEWER") -> Optional[ProfileModel]:
        async def _create(session):
            model = ProfileModel(
                user_id=user_id,
                email=email,
                password_hash=password_hash,
                full_name=full_name,
                role=role,
            )
            session.add(model)
            await session.flush()
            return model
        return await db_operation("user.create", _create)

    async def list_all(self) -> List[ProfileModel]:
        async def _list(session):
            result = await session.execute(
                select(ProfileModel).order_by(ProfileModel.created_at)
            )
            return list(result.scalars().all())
        return await db_operation("user.list", _list) or []

    async def count(self) -> int:
        async def _count(session):
            result = await session.execute(select(ProfileModel))
            return len(result.scalars().all())
        return await db_operation("user.count", _count) or 0

    async def update(self, user_id: str, **fields) -> Optional[ProfileModel]:
        async def _update(session):
            protected = {"user_id", "created_at"}
            update_fields = {k: v for k, v in fields.items() if k not in protected}
            if not update_fields:
                return await self.get_by_id(user_id)
            update_fields["updated_at"] = datetime.now(timezone.utc)
            await session.execute(
                update(ProfileModel)
                .where(ProfileModel.user_id == user_id)
                .values(**update_fields)
            )
            await session.flush()
            result = await session.execute(
                select(ProfileModel).where(ProfileModel.user_id == user_id)
            )
            return result.scalar_one_or_none()
        return await db_operation("user.update", _update)

    async def delete(self, user_id: str) -> bool:
        async def _delete(session):
            result = await session.execute(
                delete(ProfileModel).where(ProfileModel.user_id == user_id)
            )
            return result.rowcount > 0
        return await db_operation("user.delete", _delete) or False
