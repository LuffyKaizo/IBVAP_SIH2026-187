"""Edge node ORM model and repository.

Stores Edge node identities with bcrypt-hashed secrets.
Plaintext secrets are NEVER stored or logged.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Column, Text, TIMESTAMP, Index
from sqlalchemy.orm import Session

from ai.db.models import Base, _utcnow
from ai.db.repositories.base import db_operation

logger = logging.getLogger("ibvap.edge")


# ──────────────────────────────────────────────────────────────
# ORM Model
# ──────────────────────────────────────────────────────────────

class EdgeNodeModel(Base):
    """SQLAlchemy model for edge_nodes table."""
    __tablename__ = "edge_nodes"

    node_id = Column(Text, primary_key=True)
    secret_hash = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
    last_seen_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_edge_node_id", "node_id", unique=True),
    )


# ──────────────────────────────────────────────────────────────
# Repository
# ──────────────────────────────────────────────────────────────

class EdgeNodeRepository:
    """Async repository for Edge node CRUD operations."""

    async def get_by_id(self, node_id: str) -> Optional[dict]:
        """Get an Edge node by ID. Returns dict or None."""

        async def _get(session: Session):
            row = session.query(EdgeNodeModel).filter(
                EdgeNodeModel.node_id == node_id
            ).first()
            if row is None:
                return None
            return {
                "node_id": row.node_id,
                "secret_hash": row.secret_hash,
                "display_name": row.display_name,
                "enabled": row.enabled,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "last_seen_at": row.last_seen_at,
            }

        return await db_operation("edge_node.get_by_id", _get)

    async def create(
        self,
        node_id: str,
        secret_hash: str,
        display_name: str = "",
        enabled: bool = True,
    ) -> Optional[dict]:
        """Create a new Edge node. Returns created dict or None."""

        async def _create(session: Session):
            now = datetime.now(timezone.utc)
            row = EdgeNodeModel(
                node_id=node_id,
                secret_hash=secret_hash,
                display_name=display_name or node_id,
                enabled=enabled,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            return {
                "node_id": row.node_id,
                "secret_hash": row.secret_hash,
                "display_name": row.display_name,
                "enabled": row.enabled,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "last_seen_at": row.last_seen_at,
            }

        return await db_operation("edge_node.create", _create)

    async def update_last_seen(self, node_id: str) -> None:
        """Update last_seen_at timestamp. Throttled externally."""

        async def _update(session: Session):
            row = session.query(EdgeNodeModel).filter(
                EdgeNodeModel.node_id == node_id
            ).first()
            if row:
                row.last_seen_at = datetime.now(timezone.utc)
                row.updated_at = datetime.now(timezone.utc)
                session.commit()

        await db_operation("edge_node.update_last_seen", _update)

    async def set_enabled(self, node_id: str, enabled: bool) -> None:
        """Enable or disable an Edge node."""

        async def _set(session: Session):
            row = session.query(EdgeNodeModel).filter(
                EdgeNodeModel.node_id == node_id
            ).first()
            if row:
                row.enabled = enabled
                row.updated_at = datetime.now(timezone.utc)
                session.commit()

        await db_operation("edge_node.set_enabled", _set)

    async def list_all(self) -> list[dict]:
        """List all Edge nodes."""

        async def _list(session: Session):
            rows = session.query(EdgeNodeModel).all()
            return [
                {
                    "node_id": r.node_id,
                    "display_name": r.display_name,
                    "enabled": r.enabled,
                    "created_at": r.created_at,
                    "last_seen_at": r.last_seen_at,
                }
                for r in rows
            ]

        return await db_operation("edge_node.list_all", _list) or []

    async def delete(self, node_id: str) -> None:
        """Delete an Edge node."""

        async def _delete(session: Session):
            row = session.query(EdgeNodeModel).filter(
                EdgeNodeModel.node_id == node_id
            ).first()
            if row:
                session.delete(row)
                session.commit()

        await db_operation("edge_node.delete", _delete)
