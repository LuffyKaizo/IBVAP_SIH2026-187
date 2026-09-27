"""Tactical geospatial repository — runtime schema, CRUD and default seeding.

Schema policy: no auto-migration at startup and no create_all. Tables are
created idempotently via ensure_schema() (CREATE TABLE IF NOT EXISTS, dialect
compiled) and mirrored by alembic revision 008.
"""
import logging
import secrets
from typing import List, Optional

from sqlalchemy import delete, select, text as sql_text

from ai.db.repositories.base import db_operation
from ai.tactical.models import BufferZoneModel, CameraGeoModel, ZeroLineModel

logger = logging.getLogger("ibvap.tactical")

# Plausible border-sector default placements, seeded ONCE when camera_geo is
# empty so the tactical map has something to show. Operators reposition nodes
# from the UI (PUT /tactical/cameras/{id}/geo) — these are editable defaults,
# not authoritative survey coordinates.
DEFAULT_CAMERA_GEO = {
    "CAM-01": (26.9124, 73.8051, 20.0),
    "CAM-02": (26.9065, 73.8312, 75.0),
    "CAM-03": (26.8998, 73.8559, 130.0),
    "CAM-04": (26.8934, 73.8810, 160.0),
    "CAM-05": (26.9180, 73.8688, 315.0),
    "CAM-06": (26.8877, 73.9050, 45.0),
}
_DEFAULT_FOV_DEG = 60.0
_DEFAULT_RANGE_M = 250.0


def _camera_dict(model: CameraGeoModel) -> dict:
    return {
        "cameraId": model.camera_id,
        "name": model.name,
        "lat": model.lat,
        "lon": model.lon,
        "headingDeg": model.heading_deg,
        "fovDeg": model.fov_deg,
        "rangeM": model.range_m,
        "updatedAt": model.updated_at.isoformat() if model.updated_at else None,
    }


def _zero_line_dict(model: ZeroLineModel) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "cameraId": model.camera_id,
        "points": model.points or [],
        "createdAt": model.created_at.isoformat() if model.created_at else None,
    }


def _buffer_zone_dict(model: BufferZoneModel) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "cameraId": model.camera_id,
        "polygon": model.polygon or [],
        "bufferM": model.buffer_m,
        "createdAt": model.created_at.isoformat() if model.created_at else None,
    }


class TacticalRepository:
    """Async CRUD for the tactical geospatial tables."""

    async def ensure_schema(self) -> bool:
        """Create the tactical tables when missing (idempotent, portable DDL).

        Stale-repair: an earlier experiment may have left tables with the same
        names but incompatible columns (e.g. latitude/longitude vs lat/lon).
        CREATE TABLE IF NOT EXISTS would silently keep those, so any mismatched
        table is RENAMED aside (data preserved, never dropped) and recreated to
        the current model. This is a one-time, table-scoped repair — not a
        general auto-migration.
        """
        from ai.db.session import get_engine
        engine = get_engine()
        if engine is None:
            return False
        try:
            import time
            from sqlalchemy.schema import CreateTable
            async with engine.begin() as conn:
                for model in (CameraGeoModel, ZeroLineModel, BufferZoneModel):
                    table = model.__table__
                    found = await conn.execute(
                        sql_text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                        {"n": table.name},
                    )
                    if found.first():
                        info = await conn.execute(
                            sql_text(f'PRAGMA table_info("{table.name}")'))
                        existing_cols = {row[1] for row in info}
                        expected_cols = {c.name for c in table.columns}
                        missing = expected_cols - existing_cols
                        if missing:
                            stale = f"{table.name}_stale_{int(time.time())}"
                            logger.warning(
                                "[TACTICAL] table %s has stale schema (missing %s) — "
                                "renaming to %s", table.name, sorted(missing), stale)
                            await conn.execute(sql_text(
                                f'ALTER TABLE "{table.name}" RENAME TO "{stale}"'))
                    stmt = str(CreateTable(table, if_not_exists=True)
                               .compile(dialect=engine.dialect))
                    await conn.execute(sql_text(stmt))
            return True
        except Exception as e:
            logger.warning("[TACTICAL] ensure_schema failed: %s: %s",
                           type(e).__name__, e)
            return False

    # ── camera geo ─────────────────────────────────────────────────────

    async def list_cameras(self) -> List[dict]:
        async def _op(session):
            result = await session.execute(select(CameraGeoModel))
            return [_camera_dict(m) for m in result.scalars().all()]
        return await db_operation("tactical.list_cameras", _op) or []

    async def get_camera(self, camera_id: str) -> Optional[dict]:
        async def _op(session):
            model = await session.get(CameraGeoModel, camera_id)
            return _camera_dict(model) if model else None
        return await db_operation("tactical.get_camera", _op)

    async def upsert_camera_geo(self, geo: dict) -> Optional[dict]:
        async def _op(session):
            model = await session.get(CameraGeoModel, geo["cameraId"])
            if model is None:
                model = CameraGeoModel(
                    camera_id=geo["cameraId"],
                    name=geo.get("name"),
                    lat=geo["lat"],
                    lon=geo["lon"],
                    heading_deg=geo.get("headingDeg", 0.0),
                    fov_deg=geo.get("fovDeg", _DEFAULT_FOV_DEG),
                    range_m=geo.get("rangeM", _DEFAULT_RANGE_M),
                )
                session.add(model)
            else:
                model.lat = geo["lat"]
                model.lon = geo["lon"]
                model.heading_deg = geo.get("headingDeg", model.heading_deg)
                model.fov_deg = geo.get("fovDeg", model.fov_deg)
                model.range_m = geo.get("rangeM", model.range_m)
                if geo.get("name"):
                    model.name = geo["name"]
            await session.flush()
            return _camera_dict(model)
        return await db_operation("tactical.upsert_camera_geo", _op)

    async def seed_defaults_if_empty(self, camera_entries: List[dict]) -> int:
        """Seed default placements once (no-op when camera_geo has rows)."""
        if await self.list_cameras():
            return 0
        seeded = 0
        for i, cam in enumerate(camera_entries):
            camera_id = (cam.get("cameraId") or cam.get("camera_id") or "").strip()
            if not camera_id:
                continue
            default = DEFAULT_CAMERA_GEO.get(camera_id)
            if default:
                lat, lon, heading = default
            else:
                # Deterministic fallback arc for cameras outside the defaults.
                lat = 26.9124 + (i * 0.004)
                lon = 73.8051 + (i * 0.006)
                heading = (i * 47.0) % 360.0
            result = await self.upsert_camera_geo({
                "cameraId": camera_id,
                "name": cam.get("name"),
                "lat": lat,
                "lon": lon,
                "headingDeg": heading,
                "fovDeg": _DEFAULT_FOV_DEG,
                "rangeM": _DEFAULT_RANGE_M,
            })
            if result:
                seeded += 1
        if seeded:
            logger.info("[TACTICAL] Seeded default geo for %d cameras", seeded)
        return seeded

    # ── zero lines ─────────────────────────────────────────────────────

    async def list_zero_lines(self) -> List[dict]:
        async def _op(session):
            result = await session.execute(
                select(ZeroLineModel).order_by(ZeroLineModel.created_at)
            )
            return [_zero_line_dict(m) for m in result.scalars().all()]
        return await db_operation("tactical.list_zero_lines", _op) or []

    async def create_zero_line(self, name: str, points: list,
                               camera_id: Optional[str] = None) -> Optional[dict]:
        async def _op(session):
            model = ZeroLineModel(
                id="ZL-" + secrets.token_hex(4),
                name=name,
                camera_id=camera_id,
                points=points,
            )
            session.add(model)
            await session.flush()
            return _zero_line_dict(model)
        return await db_operation("tactical.create_zero_line", _op)

    async def update_zero_line(self, line_id: str, name: str, points: list,
                               camera_id: Optional[str] = None) -> Optional[dict]:
        async def _op(session):
            model = await session.get(ZeroLineModel, line_id)
            if model is None:
                return None
            model.name = name
            model.points = points
            model.camera_id = camera_id
            await session.flush()
            return _zero_line_dict(model)
        return await db_operation("tactical.update_zero_line", _op)

    async def delete_zero_line(self, line_id: str) -> bool:
        async def _op(session):
            result = await session.execute(
                delete(ZeroLineModel).where(ZeroLineModel.id == line_id)
            )
            return result.rowcount > 0
        return await db_operation("tactical.delete_zero_line", _op) or False

    # ── buffer zones ───────────────────────────────────────────────────

    async def list_buffer_zones(self) -> List[dict]:
        async def _op(session):
            result = await session.execute(
                select(BufferZoneModel).order_by(BufferZoneModel.created_at)
            )
            return [_buffer_zone_dict(m) for m in result.scalars().all()]
        return await db_operation("tactical.list_buffer_zones", _op) or []

    async def create_buffer_zone(self, name: str, polygon: list,
                                 buffer_m: Optional[float] = None,
                                 camera_id: Optional[str] = None) -> Optional[dict]:
        async def _op(session):
            model = BufferZoneModel(
                id="BZ-" + secrets.token_hex(4),
                name=name,
                camera_id=camera_id,
                polygon=polygon,
                buffer_m=buffer_m,
            )
            session.add(model)
            await session.flush()
            return _buffer_zone_dict(model)
        return await db_operation("tactical.create_buffer_zone", _op)

    async def update_buffer_zone(self, zone_id: str, name: str, polygon: list,
                                 buffer_m: Optional[float] = None,
                                 camera_id: Optional[str] = None) -> Optional[dict]:
        async def _op(session):
            model = await session.get(BufferZoneModel, zone_id)
            if model is None:
                return None
            model.name = name
            model.polygon = polygon
            model.buffer_m = buffer_m
            model.camera_id = camera_id
            await session.flush()
            return _buffer_zone_dict(model)
        return await db_operation("tactical.update_buffer_zone", _op)

    async def delete_buffer_zone(self, zone_id: str) -> bool:
        async def _op(session):
            result = await session.execute(
                delete(BufferZoneModel).where(BufferZoneModel.id == zone_id)
            )
            return result.rowcount > 0
        return await db_operation("tactical.delete_buffer_zone", _op) or False
