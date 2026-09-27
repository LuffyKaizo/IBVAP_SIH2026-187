"""Tactical geospatial map API routes (spec PART 10).

GET  /tactical/overview                     — cameras + cones + lines + zones
PUT  /tactical/cameras/{camera_id}/geo      — place/adjust a camera node
POST /tactical/zero-lines                   — create a Zero Line
PUT  /tactical/zero-lines/{id}              — edit a Zero Line
DEL  /tactical/zero-lines/{id}              — delete a Zero Line
POST /tactical/buffer-zones                 — create a Buffer Exclusion Zone
PUT  /tactical/buffer-zones/{id}            — edit a Buffer Exclusion Zone
DEL  /tactical/buffer-zones/{id}            — delete a Buffer Exclusion Zone

Reads require ZONE_READ; mutations require ZONE_WRITE (ADMIN/OPERATOR).
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai.auth.deps import require_permission
from ai.auth.models import Permission, UserContext
from ai.tactical.geometry import sector_polygon, validate_lat_lon, validate_points

router = APIRouter(prefix="/tactical", tags=["tactical"])

# Set by main.py at startup
_tactical_repo = None
_camera_repo = None


def init_tactical_routes(tactical_repo, camera_repo=None):
    global _tactical_repo, _camera_repo
    _tactical_repo = tactical_repo
    _camera_repo = camera_repo


class CameraGeoBody(BaseModel):
    lat: float
    lon: float
    headingDeg: float = Field(0.0, ge=0.0, lt=360.0)
    fovDeg: float = Field(60.0, gt=0.0, lt=360.0)
    rangeM: float = Field(250.0, gt=0.0, le=50000.0)
    name: Optional[str] = None


class ZeroLineBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    points: list
    cameraId: Optional[str] = None


class BufferZoneBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    polygon: list
    bufferM: Optional[float] = Field(None, ge=0.0, le=10000.0)
    cameraId: Optional[str] = None


def _camera_entry(geo: Optional[dict], name: Optional[str] = None) -> dict:
    if geo:
        entry = dict(geo)
        entry.setdefault("placed", True)
        if not entry.get("name") and name:
            entry["name"] = name
        entry["cone"] = sector_polygon(
            entry["lat"], entry["lon"],
            entry.get("headingDeg", 0.0), entry.get("fovDeg", 60.0),
            entry.get("rangeM", 250.0),
        )
        return entry
    return {
        "cameraId": None, "name": name, "placed": False,
        "lat": None, "lon": None, "headingDeg": 0.0,
        "fovDeg": 60.0, "rangeM": 250.0, "cone": [],
    }


async def _all_camera_names() -> dict:
    """camera_id -> name from the camera registry (for seeding + unplaced)."""
    if not _camera_repo:
        return {}
    try:
        cameras = await _camera_repo.list_all()
    except Exception:
        return {}
    names = {}
    for cam in cameras or []:
        if isinstance(cam, dict):
            cid = cam.get("cameraId") or cam.get("camera_id")
            nm = cam.get("name")
        else:
            cid = getattr(cam, "camera_id", None)
            nm = getattr(cam, "name", None)
        if cid:
            names[cid] = nm
    return names


@router.get("/overview")
async def tactical_overview(
    _user: UserContext = Depends(require_permission(Permission.ZONE_READ)),
):
    """Full tactical picture: camera nodes (with computed coverage cones),
    Zero Lines and Buffer Exclusion Zones. Unplaced cameras are included
    with placed=false so the UI can prompt for placement."""
    if not _tactical_repo:
        return {"cameras": [], "zeroLines": [], "bufferZones": [],
                "updatedAt": datetime.now(timezone.utc).isoformat()}

    names = await _all_camera_names()
    geos = await _tactical_repo.list_cameras()

    # Seed defaults once so the map is usable out of the box.
    if not geos and names:
        await _tactical_repo.seed_defaults_if_empty(
            [{"cameraId": cid, "name": nm} for cid, nm in names.items()]
        )
        geos = await _tactical_repo.list_cameras()

    by_id = {g["cameraId"]: g for g in geos}
    cameras = []
    for cid, nm in names.items():
        cameras.append(_camera_entry(by_id.get(cid), nm))
    # Include geo rows whose camera is no longer in the registry.
    for g in geos:
        if g["cameraId"] not in names:
            cameras.append(_camera_entry(g, g.get("name")))

    zero_lines = await _tactical_repo.list_zero_lines()
    buffer_zones = await _tactical_repo.list_buffer_zones()
    return {
        "cameras": cameras,
        "zeroLines": zero_lines,
        "bufferZones": buffer_zones,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.put("/cameras/{camera_id}/geo")
async def put_camera_geo(
    camera_id: str,
    body: CameraGeoBody,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    """Place or adjust a camera node (position, heading, FOV, range)."""
    if not _tactical_repo:
        raise HTTPException(status_code=503, detail="Tactical layer unavailable")
    issues = validate_lat_lon(body.lat, body.lon)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "Invalid coordinates", "issues": issues,
        })
    names = await _all_camera_names()
    result = await _tactical_repo.upsert_camera_geo({
        "cameraId": camera_id,
        "name": body.name or names.get(camera_id),
        "lat": body.lat,
        "lon": body.lon,
        "headingDeg": body.headingDeg,
        "fovDeg": body.fovDeg,
        "rangeM": body.rangeM,
    })
    if result is None:
        raise HTTPException(status_code=503, detail="Failed to persist camera geo")
    result["placed"] = True
    result["cone"] = sector_polygon(
        result["lat"], result["lon"],
        result["headingDeg"], result["fovDeg"], result["rangeM"],
    )
    return result


@router.post("/zero-lines", status_code=201)
async def create_zero_line(
    body: ZeroLineBody,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    if not _tactical_repo:
        raise HTTPException(status_code=503, detail="Tactical layer unavailable")
    issues = validate_points(body.points, min_points=2, closed=False)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "Invalid Zero Line geometry", "issues": issues,
        })
    normalized = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in body.points]
    result = await _tactical_repo.create_zero_line(
        body.name.strip(), normalized, body.cameraId
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Failed to persist Zero Line")
    return result


@router.put("/zero-lines/{line_id}")
async def update_zero_line(
    line_id: str,
    body: ZeroLineBody,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    if not _tactical_repo:
        raise HTTPException(status_code=503, detail="Tactical layer unavailable")
    issues = validate_points(body.points, min_points=2, closed=False)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "Invalid Zero Line geometry", "issues": issues,
        })
    normalized = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in body.points]
    result = await _tactical_repo.update_zero_line(
        line_id, body.name.strip(), normalized, body.cameraId
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Zero Line not found")
    return result


@router.delete("/zero-lines/{line_id}")
async def delete_zero_line(
    line_id: str,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    if not _tactical_repo:
        raise HTTPException(status_code=503, detail="Tactical layer unavailable")
    if not await _tactical_repo.delete_zero_line(line_id):
        raise HTTPException(status_code=404, detail="Zero Line not found")
    return {"deleted": line_id}


@router.post("/buffer-zones", status_code=201)
async def create_buffer_zone(
    body: BufferZoneBody,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    if not _tactical_repo:
        raise HTTPException(status_code=503, detail="Tactical layer unavailable")
    issues = validate_points(body.polygon, min_points=3, closed=True)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "Invalid Buffer Zone geometry", "issues": issues,
        })
    normalized = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in body.polygon]
    result = await _tactical_repo.create_buffer_zone(
        body.name.strip(), normalized, body.bufferM, body.cameraId
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Failed to persist Buffer Zone")
    return result


@router.put("/buffer-zones/{zone_id}")
async def update_buffer_zone(
    zone_id: str,
    body: BufferZoneBody,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    if not _tactical_repo:
        raise HTTPException(status_code=503, detail="Tactical layer unavailable")
    issues = validate_points(body.polygon, min_points=3, closed=True)
    if issues:
        raise HTTPException(status_code=422, detail={
            "message": "Invalid Buffer Zone geometry", "issues": issues,
        })
    normalized = [{"lat": float(p["lat"]), "lon": float(p["lon"])} for p in body.polygon]
    result = await _tactical_repo.update_buffer_zone(
        zone_id, body.name.strip(), normalized, body.bufferM, body.cameraId
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Buffer Zone not found")
    return result


@router.delete("/buffer-zones/{zone_id}")
async def delete_buffer_zone(
    zone_id: str,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    if not _tactical_repo:
        raise HTTPException(status_code=503, detail="Tactical layer unavailable")
    if not await _tactical_repo.delete_buffer_zone(zone_id):
        raise HTTPException(status_code=404, detail="Buffer Zone not found")
    return {"deleted": zone_id}
