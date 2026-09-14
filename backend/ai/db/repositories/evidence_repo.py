"""Evidence repository — persists evidence metadata to PostgreSQL."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai.db.models import EvidenceModel
from ai.db.repositories.base import db_operation


def _parse_timestamp(ts):
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _to_dict(row: EvidenceModel) -> dict:
    return {
        "id": row.evidence_id,
        "eventId": row.event_id,
        "alertId": row.alert_id,
        "cameraId": row.camera_id,
        "evidenceType": row.evidence_type,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "filePath": row.file_path,
        "fileSize": row.file_size,
        "mimeType": row.mime_type,
        "sha256Hash": row.sha256_hash,
        "integrityStatus": row.integrity_status,
        "metadata": row.evidence_metadata,
        "createdBy": row.created_by,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


class EvidenceRepository:

    async def create(self, evidence: dict) -> Optional[dict]:
        async def _op(session):
            row = EvidenceModel(
                evidence_id=evidence["id"],
                event_id=evidence.get("eventId"),
                alert_id=evidence.get("alertId"),
                camera_id=evidence["cameraId"],
                evidence_type=evidence["evidenceType"],
                timestamp=_parse_timestamp(evidence.get("timestamp")),
                file_path=evidence["filePath"],
                file_size=evidence["fileSize"],
                mime_type=evidence["mimeType"],
                sha256_hash=evidence["sha256Hash"],
                integrity_status=evidence.get("integrityStatus", "VALID"),
                evidence_metadata=evidence.get("metadata"),
                created_by=evidence.get("createdBy"),
            )
            session.add(row)
            await session.flush()
            return _to_dict(row)
        return await db_operation("evidence.create", _op)

    async def get(self, evidence_id: str) -> Optional[dict]:
        async def _op(session):
            result = await session.execute(
                select(EvidenceModel).where(EvidenceModel.evidence_id == evidence_id)
            )
            row = result.scalar_one_or_none()
            return _to_dict(row) if row else None
        return await db_operation("evidence.get", _op)

    async def list_for_event(self, event_id: str) -> List[dict]:
        async def _op(session):
            result = await session.execute(
                select(EvidenceModel)
                .where(EvidenceModel.event_id == event_id)
                .order_by(EvidenceModel.created_at.desc())
            )
            return [_to_dict(r) for r in result.scalars().all()]
        return await db_operation("evidence.list_for_event", _op) or []

    async def list_for_camera(self, camera_id: str, limit: int = 100) -> List[dict]:
        async def _op(session):
            result = await session.execute(
                select(EvidenceModel)
                .where(EvidenceModel.camera_id == camera_id)
                .order_by(EvidenceModel.created_at.desc())
                .limit(limit)
            )
            return [_to_dict(r) for r in result.scalars().all()]
        return await db_operation("evidence.list_for_camera", _op) or []

    async def list_recent(self, limit: int = 50) -> List[dict]:
        async def _op(session):
            result = await session.execute(
                select(EvidenceModel)
                .order_by(EvidenceModel.created_at.desc())
                .limit(limit)
            )
            return [_to_dict(r) for r in result.scalars().all()]
        return await db_operation("evidence.list_recent", _op) or []

    async def update_integrity(self, evidence_id: str, status: str) -> bool:
        async def _op(session):
            result = await session.execute(
                update(EvidenceModel)
                .where(EvidenceModel.evidence_id == evidence_id)
                .values(integrity_status=status)
            )
            return result.rowcount > 0
        return await db_operation("evidence.update_integrity", _op) or False

    async def delete(self, evidence_id: str) -> bool:
        async def _op(session):
            result = await session.execute(
                delete(EvidenceModel).where(EvidenceModel.evidence_id == evidence_id)
            )
            return result.rowcount > 0
        return await db_operation("evidence.delete", _op) or False

    async def count(self) -> int:
        async def _op(session):
            result = await session.execute(select(EvidenceModel.evidence_id))
            return len(result.all())
        return await db_operation("evidence.count", _op) or 0
