"""Blockchain anchor ORM model and repository.

Stores blockchain anchoring records in PostgreSQL.
The blockchain_anchors table is the authoritative operational representation
of the application's relationship to the ledger.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import Column, Text, Integer, Float, TIMESTAMP, ForeignKey, Index
from sqlalchemy.orm import Session

from ai.db.models import Base, _utcnow
from ai.db.repositories.base import db_operation

logger = logging.getLogger("ibvap.blockchain")


# ──────────────────────────────────────────────────────────────
# ORM Model
# ──────────────────────────────────────────────────────────────

class BlockchainAnchorModel(Base):
    """SQLAlchemy model for blockchain_anchors table."""
    __tablename__ = "blockchain_anchors"

    anchor_id = Column(Text, primary_key=True)
    evidence_id = Column(
        Text,
        ForeignKey("evidence.evidence_id", ondelete="SET NULL"),
        nullable=True,
    )
    sha256_hash = Column(Text, nullable=False)
    record_hash = Column(Text, nullable=False)
    tx_hash = Column(Text, nullable=False)
    block_number = Column(Integer, nullable=False, default=0)
    previous_hash = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="PENDING")
    confirmation_time_ms = Column(Float, nullable=False, default=0.0)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    confirmed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_anchor_evidence_id", "evidence_id"),
        Index("idx_anchor_status", "status"),
        Index("idx_anchor_created_at", "created_at"),
    )


# ──────────────────────────────────────────────────────────────
# Repository
# ──────────────────────────────────────────────────────────────

class BlockchainAnchorRepository:
    """Async repository for blockchain anchor CRUD operations."""

    async def create(
        self,
        anchor_id: str,
        evidence_id: str,
        sha256_hash: str,
        record_hash: str,
        tx_hash: str,
        block_number: int = 0,
        previous_hash: str = "",
        status: str = "PENDING",
        confirmation_time_ms: float = 0.0,
    ) -> Optional[dict]:
        """Create a new anchor record. Returns created dict or None."""

        async def _create(session: Session):
            now = datetime.now(timezone.utc)
            row = BlockchainAnchorModel(
                anchor_id=anchor_id,
                evidence_id=evidence_id,
                sha256_hash=sha256_hash,
                record_hash=record_hash,
                tx_hash=tx_hash,
                block_number=block_number,
                previous_hash=previous_hash,
                status=status,
                confirmation_time_ms=confirmation_time_ms,
                created_at=now,
                confirmed_at=now if status == "CONFIRMED" else None,
            )
            session.add(row)
            session.commit()
            return _to_dict(row)

        return await db_operation("blockchain_anchor.create", _create)

    async def get_by_id(self, anchor_id: str) -> Optional[dict]:
        """Get an anchor by ID. Returns dict or None."""

        async def _get(session: Session):
            row = session.query(BlockchainAnchorModel).filter(
                BlockchainAnchorModel.anchor_id == anchor_id
            ).first()
            if row is None:
                return None
            return _to_dict(row)

        return await db_operation("blockchain_anchor.get_by_id", _get)

    async def get_by_evidence(self, evidence_id: str) -> Optional[dict]:
        """Get the canonical anchor for an evidence record. Returns dict or None."""

        async def _get(session: Session):
            row = session.query(BlockchainAnchorModel).filter(
                BlockchainAnchorModel.evidence_id == evidence_id,
                BlockchainAnchorModel.status.in_(["PENDING", "CONFIRMED"]),
            ).order_by(BlockchainAnchorModel.created_at.desc()).first()
            if row is None:
                return None
            return _to_dict(row)

        return await db_operation("blockchain_anchor.get_by_evidence", _get)

    async def update_status(
        self,
        anchor_id: str,
        status: str,
        block_number: int = None,
        confirmation_time_ms: float = None,
    ) -> bool:
        """Update anchor status. Returns True on success."""

        async def _update(session: Session):
            row = session.query(BlockchainAnchorModel).filter(
                BlockchainAnchorModel.anchor_id == anchor_id
            ).first()
            if row is None:
                return False
            row.status = status
            if status == "CONFIRMED":
                row.confirmed_at = datetime.now(timezone.utc)
            if block_number is not None:
                row.block_number = block_number
            if confirmation_time_ms is not None:
                row.confirmation_time_ms = confirmation_time_ms
            session.commit()
            return True

        return await db_operation("blockchain_anchor.update_status", _update) or False

    async def list_pending(self, limit: int = 20) -> List[dict]:
        """List anchors with PENDING status."""

        async def _list(session: Session):
            rows = session.query(BlockchainAnchorModel).filter(
                BlockchainAnchorModel.status == "PENDING"
            ).order_by(BlockchainAnchorModel.created_at.asc()).limit(limit).all()
            return [_to_dict(r) for r in rows]

        return await db_operation("blockchain_anchor.list_pending", _list) or []

    async def count_by_status(self) -> dict:
        """Count anchors grouped by status."""

        async def _count(session: Session):
            from sqlalchemy import func
            rows = session.query(
                BlockchainAnchorModel.status,
                func.count(BlockchainAnchorModel.anchor_id),
            ).group_by(BlockchainAnchorModel.status).all()
            return {status: count for status, count in rows}

        return await db_operation("blockchain_anchor.count_by_status", _count) or {}

    async def list_recent(self, limit: int = 10) -> List[dict]:
        """List most recent anchors."""

        async def _list(session: Session):
            rows = session.query(BlockchainAnchorModel).order_by(
                BlockchainAnchorModel.created_at.desc()
            ).limit(limit).all()
            return [_to_dict(r) for r in rows]

        return await db_operation("blockchain_anchor.list_recent", _list) or []


def _to_dict(row: BlockchainAnchorModel) -> dict:
    """Convert ORM model to dict. Matches API naming conventions."""
    return {
        "anchorId": row.anchor_id,
        "evidenceId": row.evidence_id,
        "sha256Hash": row.sha256_hash,
        "recordHash": row.record_hash,
        "txHash": row.tx_hash,
        "blockNumber": row.block_number,
        "previousHash": row.previous_hash,
        "status": row.status,
        "confirmationTimeMs": row.confirmation_time_ms,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "confirmedAt": row.confirmed_at.isoformat() if row.confirmed_at else None,
    }
