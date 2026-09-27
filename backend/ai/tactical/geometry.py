"""Tactical geospatial geometry (spec PART 10).

All coordinates are WGS84 decimal degrees. Coverage cones are computed
server-side so the map, tests and API consumers share one implementation.
"""
import math
from typing import List, Optional

EARTH_RADIUS_M = 6371008.8  # mean Earth radius

LAT_MIN, LAT_MAX = -90.0, 90.0
LON_MIN, LON_MAX = -180.0, 180.0


def validate_lat_lon(lat, lon) -> List[str]:
    """Return a list of coordinate issues (empty when valid)."""
    issues: List[str] = []
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return ["not_numeric"]
    if not math.isfinite(lat) or not math.isfinite(lon):
        return ["not_finite"]
    if not (LAT_MIN <= lat <= LAT_MAX):
        issues.append("lat_out_of_range")
    if not (LON_MIN <= lon <= LON_MAX):
        issues.append("lon_out_of_range")
    return issues


def meters_to_degrees(meters: float, ref_lat: float):
    """Approximate (dlat, dlon) for a north/east offset in meters."""
    dlat = (meters / 111320.0)
    cos_lat = math.cos(math.radians(ref_lat)) or 1e-9
    dlon = meters / (111320.0 * cos_lat)
    return dlat, dlon


def destination_point(lat: float, lon: float, bearing_deg: float, distance_m: float):
    """Spherical destination point from (lat, lon) along a bearing."""
    delta = distance_m / EARTH_RADIUS_M
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    sin_phi2 = max(-1.0, min(1.0, sin_phi2))
    phi2 = math.asin(sin_phi2)
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * sin_phi2,
    )
    return math.degrees(phi2), math.degrees(lam2)


def great_circle_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two coordinates (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def sector_polygon(
    lat: float,
    lon: float,
    heading_deg: float,
    fov_deg: float,
    range_m: float,
    segments: int = 24,
) -> List[dict]:
    """Camera coverage cone as a closed polygon: apex + FOV arc.

    heading_deg: 0 = north, clockwise. fov_deg clamped to (0, 360).
    Returns [{"lat", "lon"}, ...] — apex first, arc points, implicit close.
    """
    fov = max(1.0, min(float(fov_deg or 60.0), 359.0))
    rng = max(1.0, float(range_m or 250.0))
    segments = max(4, int(segments))
    half = fov / 2.0
    start = float(heading_deg or 0.0) - half
    end = float(heading_deg or 0.0) + half
    points = [{"lat": lat, "lon": lon}]
    for i in range(segments + 1):
        bearing = start + (end - start) * i / segments
        plat, plon = destination_point(lat, lon, bearing, rng)
        points.append({"lat": round(plat, 7), "lon": round(plon, 7)})
    return points


def validate_points(points, min_points: int, closed: bool = False) -> List[str]:
    """Validate a coordinate list for a line (min_points) or polygon."""
    if not isinstance(points, list) or len(points) < min_points:
        return ["too_few_points"]
    issues: List[str] = []
    seen = set()
    for p in points:
        if not isinstance(p, dict):
            return ["point_not_object"]
        point_issues = validate_lat_lon(p.get("lat"), p.get("lon"))
        if point_issues:
            issues.extend(point_issues)
            break
        key = (round(float(p.get("lat")), 7), round(float(p.get("lon")), 7))
        if key in seen:
            issues.append("duplicate_point")
        seen.add(key)
    if closed and len(seen) < max(3, min_points):
        issues.append("too_few_unique_points")
    return issues
