"""ANPR record repository for PostgreSQL persistence.

Uses session-per-operation pattern. No shared AsyncSession.
Includes ON CONFLICT for safe upserts.
"""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai.db.models import AnprRecordModel
from ai.db.repositories.base import db_operation


class AnprRepository:
    """Async CRUD for anpr_records table with per-operation sessions."""

    def _to_dict(self, model: AnprRecordModel) -> dict:
        return {
            "id": model.record_id,
            "trackId": model.track_id,
            "cameraId": model.camera_id,
            "vehicleClass": model.vehicle_class,
            "rawOcrText": model.raw_plate_text,
            "plateText": model.normalized_plate,
            "correctedPlate": model.corrected_plate,
            "ocrConfidence": model.ocr_confidence,
            "plateConfidence": model.plate_confidence,
            "corrected": model.corrected,
            "vehicleBbox": model.vehicle_bbox,
            "plateBbox": model.plate_bbox,
            "status": model.status,
            "timestamp": model.timestamp.isoformat() if model.timestamp else "",
            "formatStatus": model.format_status,
            "correctionNote": model.correction_note,
            "observationCount": model.observation_count,
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

    async def create(self, result: dict) -> Optional[dict]:
        """Insert a new ANPR record. Uses ON CONFLICT DO NOTHING for safety."""
        async def _create(session):
            ts = self._parse_timestamp(result.get("timestamp", ""))
            stmt = pg_insert(AnprRecordModel).values(
                record_id=result.get("id", ""),
                camera_id=result.get("cameraId", ""),
                track_id=result.get("trackId", -1),
                vehicle_class=result.get("vehicleClass", "car"),
                raw_plate_text=result.get("rawOcrText"),
                normalized_plate=result.get("plateText"),
                corrected_plate=result.get("correctedPlate"),
                ocr_confidence=result.get("ocrConfidence"),
                plate_confidence=result.get("plateConfidence"),
                corrected=result.get("corrected", False),
                vehicle_bbox=result.get("vehicleBbox"),
                plate_bbox=result.get("plateBbox"),
                status=result.get("status", "DETECTED"),
                timestamp=ts,
                format_status=result.get("formatStatus"),
                correction_note=result.get("correctionNote"),
                observation_count=result.get("observationCount", 0),
            ).on_conflict_do_nothing(index_elements=["record_id"])
            await session.execute(stmt)
            await session.flush()
            return result
        return await db_operation("anpr.create", _create)

    async def get(self, record_id: str) -> Optional[dict]:
        async def _get(session):
            result = await session.execute(
                select(AnprRecordModel).where(AnprRecordModel.record_id == record_id)
            )
            model = result.scalar_one_or_none()
            return self._to_dict(model) if model else None
        return await db_operation("anpr.get", _get)

    async def list_for_camera(self, camera_id: str, limit: int = 100) -> List[dict]:
        async def _list(session):
            result = await session.execute(
                select(AnprRecordModel)
                .where(AnprRecordModel.camera_id == camera_id)
                .order_by(AnprRecordModel.timestamp.desc())
                .limit(limit)
            )
            return [self._to_dict(m) for m in result.scalars().all()]
        return await db_operation("anpr.list_camera", _list) or []

    async def list_recent(self, limit: int = 50) -> List[dict]:
        async def _list(session):
            result = await session.execute(
                select(AnprRecordModel)
                .order_by(AnprRecordModel.timestamp.desc())
                .limit(limit)
            )
            return [self._to_dict(m) for m in result.scalars().all()]
        return await db_operation("anpr.list_recent", _list) or []
