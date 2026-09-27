"""Tactical geospatial layer tests (spec PART 10): geometry, routes and
idempotent runtime schema creation."""
import asyncio
import sys

import pytest

sys.path.insert(0, ".")

from fastapi import HTTPException

from ai.tactical import routes as tactical_routes
from ai.tactical.geometry import (
    great_circle_m,
    meters_to_degrees,
    sector_polygon,
    validate_lat_lon,
    validate_points,
)
from ai.tactical.repository import DEFAULT_CAMERA_GEO, TacticalRepository


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── geometry ───────────────────────────────────────────────────────────

def test_validate_lat_lon_accepts_valid_coordinates():
    assert validate_lat_lon(26.9, 73.8) == []
    assert validate_lat_lon(-33.9, 151.2) == []


def test_validate_lat_lon_flags_out_of_range_and_junk():
    assert "lat_out_of_range" in validate_lat_lon(91.0, 0.0)
    assert "lon_out_of_range" in validate_lat_lon(0.0, 181.0)
    assert validate_lat_lon("abc", 0.0) == ["not_numeric"]
    assert validate_lat_lon(float("nan"), 0.0) == ["not_finite"]


def test_sector_polygon_shape_and_range():
    lat, lon = 26.9, 73.8
    pts = sector_polygon(lat, lon, heading_deg=90.0, fov_deg=60.0, range_m=500.0,
                         segments=12)
    assert pts[0] == {"lat": lat, "lon": lon}   # apex
    assert len(pts) == 14                       # apex + 12 arc + closing? -> 1+13
    # Every arc point is ~range_m from the apex
    for p in pts[1:]:
        dist = great_circle_m(lat, lon, p["lat"], p["lon"])
        assert 490.0 <= dist <= 510.0


def test_sector_polygon_heading_north_and_east():
    lat, lon = 26.9, 73.8
    north = sector_polygon(lat, lon, heading_deg=0.0, fov_deg=40.0, range_m=300.0)
    # Mid-arc point due north of apex: higher latitude, same longitude
    mid = north[len(north) // 2]
    assert mid["lat"] > lat
    assert abs(mid["lon"] - lon) < 1e-4

    east = sector_polygon(lat, lon, heading_deg=90.0, fov_deg=40.0, range_m=300.0)
    mid_e = east[len(east) // 2]
    assert mid_e["lon"] > lon
    assert abs(mid_e["lat"] - lat) < 1e-4


def test_sector_polygon_clamps_fov_and_range():
    pts = sector_polygon(26.9, 73.8, heading_deg=0.0, fov_deg=999.0, range_m=0.0)
    # fov clamped below 360; range 0/None falls back to the 250m default
    assert all(-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180 for p in pts)
    dist = great_circle_m(pts[0]["lat"], pts[0]["lon"], pts[1]["lat"], pts[1]["lon"])
    assert 245.0 <= dist <= 255.0
    pts_none = sector_polygon(26.9, 73.8, heading_deg=0.0, fov_deg=60.0, range_m=None)
    dist_none = great_circle_m(pts_none[0]["lat"], pts_none[0]["lon"],
                               pts_none[1]["lat"], pts_none[1]["lon"])
    assert 245.0 <= dist_none <= 255.0


def test_meters_to_degrees_scale():
    dlat, dlon = meters_to_degrees(1113.2, ref_lat=0.0)
    assert 0.009 <= dlat <= 0.011     # ~1113.2m / 111320 m/deg ≈ 0.01
    assert abs(dlat - dlon) < 1e-6    # at equator lat/lon degrees match


def test_validate_points_line_and_polygon():
    line = [{"lat": 26.9, "lon": 73.8}, {"lat": 26.91, "lon": 73.81}]
    assert validate_points(line, min_points=2) == []
    assert "too_few_points" in validate_points([line[0]], min_points=2)
    dup = [{"lat": 26.9, "lon": 73.8}, {"lat": 26.9, "lon": 73.8},
           {"lat": 26.91, "lon": 73.81}]
    assert "duplicate_point" in validate_points(dup, min_points=3)
    # Polygon with 3 entries but only 2 unique points
    assert "too_few_unique_points" in validate_points(dup, min_points=3, closed=True)
    assert "point_not_object" in validate_points([1, 2, 3], min_points=3)


# ── routes (fake repos) ────────────────────────────────────────────────

class FakeTacticalRepo:
    def __init__(self, geos=None):
        self.geos = list(geos or [])
        self.zero_lines = []
        self.buffer_zones = []

    async def list_cameras(self):
        return list(self.geos)

    async def seed_defaults_if_empty(self, entries):
        if self.geos:
            return 0
        for i, e in enumerate(entries):
            self.geos.append({
                "cameraId": e["cameraId"], "name": e.get("name"),
                "lat": 26.9 + i * 0.01, "lon": 73.8 + i * 0.01,
                "headingDeg": 0.0, "fovDeg": 60.0, "rangeM": 250.0,
            })
        return len(self.geos)

    async def list_zero_lines(self):
        return list(self.zero_lines)

    async def list_buffer_zones(self):
        return list(self.buffer_zones)

    async def upsert_camera_geo(self, geo):
        for g in self.geos:
            if g["cameraId"] == geo["cameraId"]:
                g.update(geo)
                return dict(g)
        self.geos.append(dict(geo))
        return dict(geo)

    async def create_zero_line(self, name, points, camera_id=None):
        row = {"id": "ZL-TEST01", "name": name, "cameraId": camera_id,
               "points": points, "createdAt": None}
        self.zero_lines.append(row)
        return row

    async def update_zero_line(self, line_id, name, points, camera_id=None):
        for z in self.zero_lines:
            if z["id"] == line_id:
                z.update({"name": name, "points": points, "cameraId": camera_id})
                return dict(z)
        return None

    async def delete_zero_line(self, line_id):
        before = len(self.zero_lines)
        self.zero_lines = [z for z in self.zero_lines if z["id"] != line_id]
        return len(self.zero_lines) < before

    async def create_buffer_zone(self, name, polygon, buffer_m=None, camera_id=None):
        row = {"id": "BZ-TEST01", "name": name, "cameraId": camera_id,
               "polygon": polygon, "bufferM": buffer_m, "createdAt": None}
        self.buffer_zones.append(row)
        return row

    async def update_buffer_zone(self, zone_id, name, polygon, buffer_m=None,
                                 camera_id=None):
        for z in self.buffer_zones:
            if z["id"] == zone_id:
                z.update({"name": name, "polygon": polygon, "bufferM": buffer_m,
                          "cameraId": camera_id})
                return dict(z)
        return None

    async def delete_buffer_zone(self, zone_id):
        before = len(self.buffer_zones)
        self.buffer_zones = [z for z in self.buffer_zones if z["id"] != zone_id]
        return len(self.buffer_zones) < before


class FakeCameraRepo:
    async def list_all(self):
        return [
            {"cameraId": "CAM-01", "name": "North Gate"},
            {"cameraId": "CAM-02", "name": "East Fence"},
        ]


@pytest.fixture
def fake_env(monkeypatch):
    repo = FakeTacticalRepo()
    tactical_routes.init_tactical_routes(repo, FakeCameraRepo())
    yield repo
    tactical_routes.init_tactical_routes(None, None)


def test_overview_seeds_defaults_and_computes_cones(fake_env):
    data = _run(tactical_routes.tactical_overview())
    assert len(data["cameras"]) == 2
    first = data["cameras"][0]
    assert first["placed"] is True
    assert first["cameraId"] == "CAM-01"
    assert first["name"] == "North Gate"
    # cone: apex + arc segments
    assert len(first["cone"]) > 10
    assert data["zeroLines"] == []
    assert data["bufferZones"] == []
    # Second call must NOT re-seed
    _run(tactical_routes.tactical_overview())
    assert len(fake_env.geos) == 2


def test_put_camera_geo_rejects_bad_coordinates(fake_env):
    body = tactical_routes.CameraGeoBody(lat=999.0, lon=73.8)
    with pytest.raises(HTTPException) as exc:
        _run(tactical_routes.put_camera_geo("CAM-01", body))
    assert exc.value.status_code == 422
    assert "lat_out_of_range" in str(exc.value.detail)


def test_put_camera_geo_persists_and_returns_cone(fake_env):
    body = tactical_routes.CameraGeoBody(
        lat=26.95, lon=73.85, headingDeg=45.0, fovDeg=90.0, rangeM=400.0)
    result = _run(tactical_routes.put_camera_geo("CAM-01", body))
    assert result["lat"] == 26.95
    assert result["placed"] is True
    assert len(result["cone"]) > 10
    assert any(g["cameraId"] == "CAM-01" and g["lat"] == 26.95 for g in fake_env.geos)


def test_create_zero_line_validation_and_success(fake_env):
    with pytest.raises(HTTPException) as exc:
        _run(tactical_routes.create_zero_line(
            tactical_routes.ZeroLineBody(name="Line A",
                                         points=[{"lat": 26.9, "lon": 73.8}])))
    assert exc.value.status_code == 422

    ok = _run(tactical_routes.create_zero_line(
        tactical_routes.ZeroLineBody(name="Line A", points=[
            {"lat": 26.9, "lon": 73.8}, {"lat": 26.95, "lon": 73.9},
        ])))
    assert ok["id"] == "ZL-TEST01"
    assert len(ok["points"]) == 2
    assert _run(tactical_routes.delete_zero_line("ZL-TEST01")) == {"deleted": "ZL-TEST01"}
    with pytest.raises(HTTPException) as exc:
        _run(tactical_routes.delete_zero_line("ZL-TEST01"))
    assert exc.value.status_code == 404


def test_update_zero_line_and_404(fake_env):
    _run(tactical_routes.create_zero_line(
        tactical_routes.ZeroLineBody(name="Line A", points=[
            {"lat": 26.9, "lon": 73.8}, {"lat": 26.95, "lon": 73.9},
        ])))
    updated = _run(tactical_routes.update_zero_line(
        "ZL-TEST01",
        tactical_routes.ZeroLineBody(name="Line A v2", points=[
            {"lat": 26.9, "lon": 73.8}, {"lat": 26.94, "lon": 73.88},
            {"lat": 26.96, "lon": 73.92},
        ])))
    assert updated["name"] == "Line A v2"
    assert len(updated["points"]) == 3
    with pytest.raises(HTTPException) as exc:
        _run(tactical_routes.update_zero_line(
            "ZL-MISSING",
            tactical_routes.ZeroLineBody(name="x", points=[
                {"lat": 26.9, "lon": 73.8}, {"lat": 26.95, "lon": 73.9}])))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        _run(tactical_routes.update_zero_line(
            "ZL-TEST01",
            tactical_routes.ZeroLineBody(name="x", points=[{"lat": 26.9, "lon": 73.8}])))
    assert exc.value.status_code == 422


def test_create_buffer_zone_validation_and_lifecycle(fake_env):
    same = [{"lat": 26.9, "lon": 73.8}] * 3
    with pytest.raises(HTTPException) as exc:
        _run(tactical_routes.create_buffer_zone(
            tactical_routes.BufferZoneBody(name="Zone A", polygon=same)))
    assert exc.value.status_code == 422

    ok = _run(tactical_routes.create_buffer_zone(
        tactical_routes.BufferZoneBody(name="Zone A", polygon=[
            {"lat": 26.9, "lon": 73.8}, {"lat": 26.9, "lon": 73.85},
            {"lat": 26.93, "lon": 73.85},
        ], bufferM=100.0)))
    assert ok["id"] == "BZ-TEST01"
    assert ok["bufferM"] == 100.0
    updated = _run(tactical_routes.update_buffer_zone(
        "BZ-TEST01",
        tactical_routes.BufferZoneBody(name="Zone A2", polygon=[
            {"lat": 26.9, "lon": 73.8}, {"lat": 26.9, "lon": 73.86},
            {"lat": 26.94, "lon": 73.86},
        ], bufferM=150.0)))
    assert updated["name"] == "Zone A2"
    assert updated["bufferM"] == 150.0
    with pytest.raises(HTTPException) as exc:
        _run(tactical_routes.update_buffer_zone(
            "BZ-MISSING",
            tactical_routes.BufferZoneBody(name="x", polygon=[
                {"lat": 26.9, "lon": 73.8}, {"lat": 26.9, "lon": 73.85},
                {"lat": 26.93, "lon": 73.85}])))
    assert exc.value.status_code == 404
    assert _run(tactical_routes.delete_buffer_zone("BZ-TEST01")) == {"deleted": "BZ-TEST01"}


# ── runtime schema (idempotent DDL) ────────────────────────────────────

def test_ensure_schema_is_idempotent_on_sqlite(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    import ai.db.session as db_session

    engine = create_async_engine("sqlite+aiosqlite://")
    monkeypatch.setattr(db_session, "_engine", engine)

    repo = TacticalRepository()
    try:
        assert _run(repo.ensure_schema()) is True
        assert _run(repo.ensure_schema()) is True  # second run: no error

        async def _tables():
            from sqlalchemy import text
            async with engine.connect() as conn:
                res = await conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table'"))
                return {row[0] for row in res}
        tables = _run(_tables())
        assert {"camera_geo", "tactical_zero_lines", "tactical_buffer_zones"} <= tables
    finally:
        _run(engine.dispose())


def test_ensure_schema_renames_stale_tables_and_recreates(monkeypatch):
    """Stale same-name tables with incompatible columns are renamed aside
    (data preserved) and recreated to the current model."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import ai.db.session as db_session

    engine = create_async_engine("sqlite+aiosqlite://")
    monkeypatch.setattr(db_session, "_engine", engine)

    async def _seed_stale():
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE camera_geo (camera_id TEXT PRIMARY KEY, "
                "latitude FLOAT, longitude FLOAT)"))
            await conn.execute(text(
                "INSERT INTO camera_geo (camera_id, latitude, longitude) "
                "VALUES ('CAM-99', 12.0, 77.0)"))

    repo = TacticalRepository()
    try:
        _run(_seed_stale())
        assert _run(repo.ensure_schema()) is True

        async def _inspect():
            from sqlalchemy import text
            async with engine.connect() as conn:
                cols = {row[1] for row in await conn.execute(
                    text('PRAGMA table_info("camera_geo")'))}
                names = {row[0] for row in await conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'camera_geo_stale_%'"))}
                stale_rows = 0
                if names:
                    stale_rows = (await conn.execute(text(
                        f'SELECT COUNT(*) FROM "{next(iter(names))}"'))).scalar()
                return cols, names, stale_rows

        cols, stale_names, stale_rows = _run(_inspect())
        # Fresh table matches the model
        assert {"camera_id", "name", "lat", "lon", "heading_deg",
                "fov_deg", "range_m", "updated_at"} <= cols
        # Stale table preserved under a new name with its data intact
        assert len(stale_names) == 1
        assert stale_rows == 1
    finally:
        _run(engine.dispose())


def test_default_camera_geo_covers_six_cameras():
    assert set(DEFAULT_CAMERA_GEO) >= {"CAM-01", "CAM-05", "CAM-06"}
    for lat, lon, heading in DEFAULT_CAMERA_GEO.values():
        assert validate_lat_lon(lat, lon) == []
        assert 0.0 <= heading < 360.0
