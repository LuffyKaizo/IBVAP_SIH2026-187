"""Source-frame bounding-box geometry for evidence generation.

The authoritative detection coordinates always live in SOURCE FRAME pixel
space (spec PART 2): x1/y1/x2/y2 plus class, track_id, confidence, camera,
timestamp and zone are carried by the event dict from YOLOv8n -> ByteTrack ->
EventEngine. This module validates, clamps and expands those boxes for
evidence cropping (PART 5) and reports diagnostics (PART 12).

Coordinate-space invariant:
    bbox values are pixels of the exact event frame (frame_width x frame_height).
    Normalized (0..1) coordinates are rejected as invalid here — never silently
    scaled — so a coordinate-space bug surfaces in the log instead of producing
    a wrong crop.
"""

import logging
from typing import Any, List, Optional, Sequence, Tuple

logger = logging.getLogger("ibvap.evidence")

# Smallest usable crop (pixels). Anything below this is a degenerate box.
MIN_CROP_PX = 8


def parse_bbox(bbox: Any) -> Optional[Tuple[float, float, float, float]]:
    """Parse an event bbox (dict form) into a float 4-tuple. None when absent/invalid."""
    if bbox is None:
        return None
    if isinstance(bbox, dict):
        try:
            return (
                float(bbox.get("x1")),
                float(bbox.get("y1")),
                float(bbox.get("x2")),
                float(bbox.get("y2")),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(bbox, (tuple, list)) and len(bbox) == 4:
        try:
            return float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        except (TypeError, ValueError):
            return None
    return None


def validate_bbox(
    x1: float, y1: float, x2: float, y2: float, frame_w: int, frame_h: int
) -> List[str]:
    """Return a list of coordinate problems (empty list = valid, spec PART 12).

    Flags: degenerate ordering, out-of-frame coordinates, sub-pixel / tiny
    boxes, and normalized-looking coordinates (values all <= 1 on a frame far
    larger than 1px) which indicate a coordinate-space mix-up.
    """
    issues: List[str] = []
    if frame_w <= 0 or frame_h <= 0:
        issues.append("unknown_frame_size")
        return issues
    if not all(map(_is_finite, (x1, y1, x2, y2))):
        issues.append("non_finite")
        return issues
    if x1 >= x2:
        issues.append("x1>=x2")
    if y1 >= y2:
        issues.append("y1>=y2")
    if x1 < 0 or y1 < 0:
        issues.append("negative_origin")
    if x2 > frame_w or y2 > frame_h:
        issues.append("outside_frame")
    if x2 - x1 < MIN_CROP_PX or y2 - y1 < MIN_CROP_PX:
        issues.append("too_small")
    if frame_w > 16 and frame_h > 16 and max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.0:
        # A box entirely within [0,1] on a normal-size frame is almost
        # certainly normalized 0..1 coordinates leaking into pixel space.
        issues.append("looks_normalized")
    return issues


def _is_finite(v: float) -> bool:
    return v == v and abs(v) != float("inf")


def clamp_bbox(
    x1: float, y1: float, x2: float, y2: float, frame_w: int, frame_h: int
) -> Tuple[int, int, int, int]:
    """Clamp a box into the frame with integer pixel coordinates."""
    cx1 = max(0, min(frame_w, int(round(x1))))
    cy1 = max(0, min(frame_h, int(round(y1))))
    cx2 = max(0, min(frame_w, int(round(x2))))
    cy2 = max(0, min(frame_h, int(round(y2))))
    return cx1, cy1, cx2, cy2


def crop_rect(
    bbox: Any,
    frame_w: int,
    frame_h: int,
    margin: float,
) -> Tuple[Optional[Tuple[int, int, int, int]], dict]:
    """Compute the target-crop rectangle (source-frame pixels) for a bbox.

    Expands the full detection box by `margin` (fraction of bbox size) on each
    side, clamps to the frame (PART 5) and returns diagnostics (PART 12).

    Returns (rect, diagnostics). rect is None when the box cannot produce a
    usable crop; diagnostics always describes what happened.
    """
    m = max(0.0, min(float(margin or 0.0), 0.5))
    diagnostics: dict = {
        "frame_width": frame_w,
        "frame_height": frame_h,
        "margin": m,
        "bbox_px": None,
        "crop_px": None,
        "clamped": False,
        "issues": [],
    }
    parsed = parse_bbox(bbox)
    if parsed is None:
        diagnostics["issues"].append("missing_bbox")
        return None, diagnostics
    x1, y1, x2, y2 = parsed
    diagnostics["bbox_px"] = [round(v, 1) for v in (x1, y1, x2, y2)]

    issues = validate_bbox(x1, y1, x2, y2, frame_w, frame_h)
    # Negative/outside coordinates are recoverable by clamping; the rest are not.
    fatal = [i for i in issues if i not in ("negative_origin", "outside_frame")]
    diagnostics["issues"] = issues
    if fatal:
        return None, diagnostics

    dx = (x2 - x1) * m
    dy = (y2 - y1) * m
    ex1, ey1, ex2, ey2 = x1 - dx, y1 - dy, x2 + dx, y2 + dy
    cx1, cy1, cx2, cy2 = clamp_bbox(ex1, ey1, ex2, ey2, frame_w, frame_h)
    diagnostics["clamped"] = (
        cx1 != ex1 or cy1 != ey1 or cx2 != ex2 or cy2 != ey2
    ) or x1 < 0 or y1 < 0 or x2 > frame_w or y2 > frame_h
    if cx2 - cx1 < MIN_CROP_PX or cy2 - cy1 < MIN_CROP_PX:
        diagnostics["issues"].append("crop_too_small_after_clamp")
        return None, diagnostics
    rect = (cx1, cy1, cx2, cy2)
    diagnostics["crop_px"] = list(rect)
    return rect, diagnostics


def log_diagnostics(event_dict: dict, diagnostics: dict, artifact: str = "target_crop") -> None:
    """Emit one compact evidence-geometry line per event (not per frame)."""
    event_id = (event_dict or {}).get("event_id", "?")
    issues = diagnostics.get("issues") or []
    level = logging.INFO if issues else logging.DEBUG
    logger.log(
        level,
        "[EVIDENCE-GEOM] %s event=%s frame=%sx%s bbox=%s crop=%s clamped=%s issues=%s",
        artifact,
        event_id,
        diagnostics.get("frame_width"),
        diagnostics.get("frame_height"),
        diagnostics.get("bbox_px"),
        diagnostics.get("crop_px"),
        diagnostics.get("clamped"),
        ",".join(issues) if issues else "none",
    )
