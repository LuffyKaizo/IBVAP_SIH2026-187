"""Audit log repository for PostgreSQL persistence.

Uses session-per-operation pattern. No shared AsyncSession.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select

from ai.db.models import AuditLogModel
from ai.db.repositories.base import db_operation


class AuditRepository:
    """Async CRUD for audit_logs table with per-operation sessions."""

    async def log(self, action: str, entity_type: str, entity_id: str,
                  details: dict = None, actor: str = None) -> None:
        """Log an audit event. Fire-and-forget — errors are logged but not raised."""
        async def _log(session):
            model = AuditLogModel(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                actor=actor,
                timestamp=datetime.now(timezone.utc),
            )
            session.add(model)
            await session.flush()
            return True
        await db_operation("audit.log", _log)

    async def list_for_entity(self, entity_type: str, entity_id: str,
                              limit: int = 100) -> List[dict]:
        async def _list(session):
            result = await session.execute(
                select(AuditLogModel)
                .where(
                    AuditLogModel.entity_type == entity_type,
                    AuditLogModel.entity_id == entity_id,
                )
                .order_by(AuditLogModel.timestamp.desc())
                .limit(limit)
            )
            return [
                {
                    "id": m.id,
                    "action": m.action,
                    "entity_type": m.entity_type,
                    "entity_id": m.entity_id,
                    "details": m.details,
                    "actor": m.actor,
                    "timestamp": m.timestamp.isoformat() if m.timestamp else "",
                }
                for m in result.scalars().all()
            ]
        return await db_operation("audit.list_entity", _list) or []
