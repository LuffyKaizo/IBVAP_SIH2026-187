"""Authoritative annotation rendering for evidence images (spec PART 7/8).

Draws the source-frame detection box and its labels onto the EXACT event
frame so evidence makes the triggering object immediately obvious:

- annotate_full_frame(): original frame + red bbox + label banner
  (event label, class #track, confidence, camera, timestamp, zone).
- build_target_crop(): full-body bbox crop expanded by a configurable margin,
  clamped to the frame, with the box + banner baked in.

Only the main YOLOv8n/ByteTrack bounding box is ever drawn — never a face
box and never an ANPR plate box (PART 8).
"""

from typing import List, Optional, Tuple

import cv2
import numpy as np

from ai.evidence.geometry import crop_rect, log_diagnostics

# Event type -> operator-facing label line (PART 7 annotation).
_EVENT_LABELS = {
    "PERSON_INTRUSION": "INTRUSION",
    "VEHICLE_INTRUSION": "INTRUSION",
    "BORDER_INTRUSION": "INTRUSION",
    "RESTRICTED_ZONE_VEHICLE": "INTRUSION",
    "LOITERING": "LOITERING",
    "NIGHT_MOVEMENT": "NIGHT MOVEMENT",
    "SUSPICIOUS_ACTIVITY": "SUSPICIOUS ACTIVITY",
}

_BOX_COLOR = (0, 0, 255)  # BGR red
_BANNER_ALPHA = 0.75


def event_label(event_dict: dict) -> str:
    etype = str(event_dict.get("event_type") or "")
    return _EVENT_LABELS.get(etype, etype.replace("_", " ").upper() or "ALERT")


def _format_lines(event_dict: dict) -> List[str]:
    """Label lines: EVENT / CLASS #track conf% / camera time / zone name."""
    lines = [event_label(event_dict)]
    cls = str(event_dict.get("object_class") or "target")
    cls = cls[:1].upper() + cls[1:]
    track_id = int(event_dict.get("track_id", -1) if event_dict.get("track_id") is not None else -1)
    conf = float(event_dict.get("confidence", 0) or 0)
    if track_id >= 0:
        lines.append("%s #%d  %d%%" % (cls, track_id, round(conf * 100)))
    else:
        lines.append("%s  %d%%" % (cls, round(conf * 100)))
    camera = str(event_dict.get("camera_id") or "")
    ts = str(event_dict.get("timestamp") or "")
    time_part = ts.split("T")[-1][:8] if ts else ""
    stamp = " · ".join(p for p in (camera, time_part) if p)
    if stamp:
        lines.append(stamp)
    zone = str(event_dict.get("zone_name") or "")
    if zone:
        lines.append(zone)
    return lines


def _draw_banner(img: np.ndarray, lines: List[str], origin: Tuple[int, int]) -> None:
    """Semi-transparent red banner with white text at `origin` (top-left)."""
    h, w = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.45, min(1.0, min(h, w) / 900.0 + 0.2))
    thickness = max(1, int(round(scale * 2)))
    sizes = [cv2.getTextSize(t, font, scale, thickness)[0] for t in lines]
    banner_w = min(w, max(s[0] for s in sizes) + 14)
    banner_h = min(h, sum(s[1] for s in sizes) + 8 * len(lines) + 6)
    ox = max(0, min(w - banner_w, origin[0]))
    oy = max(0, min(h - banner_h, origin[1]))
    overlay = img.copy()
    cv2.rectangle(overlay, (ox, oy), (ox + banner_w, oy + banner_h), (0, 0, 255), -1)
    cv2.addWeighted(overlay, _BANNER_ALPHA, img, 1 - _BANNER_ALPHA, 0, img)
    y = oy + 4
    for text, (tw, th) in zip(lines, sizes):
        if y + th + 2 > oy + banner_h:
            break
        cv2.putText(img, text, (ox + 7, y + th), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
        y += th + 8


def annotate_full_frame(frame: np.ndarray, event_dict: dict) -> Optional[np.ndarray]:
    """Exact event frame + authoritative red bbox + label banner (PART 7).

    Returns an annotated copy, or None when the frame/bbox are unusable.
    The box is the full source-frame detection box of the alerting track —
    only that track is emphasized, never every object in the scene (TEST 5).
    """
    try:
        if frame is None or not isinstance(frame, np.ndarray):
            return None
        h, w = frame.shape[:2]
        rect, diag = crop_rect(event_dict.get("bbox"), w, h, margin=0.0)
        log_diagnostics(event_dict, diag, artifact="annotated_frame")
        if rect is None:
            return None
        x1, y1, x2, y2 = rect
        img = frame.copy()
        thickness = max(2, int(round(min(h, w) / 400.0)))
        cv2.rectangle(img, (x1, y1), (x2, y2), _BOX_COLOR, thickness)
        lines = _format_lines(event_dict)
        # Banner above the box when there is room, otherwise just below it.
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = max(0.45, min(1.0, min(h, w) / 900.0 + 0.2))
        thickness_t = max(1, int(round(scale * 2)))
        banner_h = sum(cv2.getTextSize(t, font, scale, thickness_t)[0][1] for t in lines) + 8 * len(lines) + 6
        banner_w = min(w, max(cv2.getTextSize(t, font, scale, thickness_t)[0][0] for t in lines) + 14)
        ox = x1 if x1 + banner_w <= w else max(0, w - banner_w)
        oy = y1 - banner_h - 4 if y1 - banner_h - 4 >= 0 else min(h - banner_h, y2 + 4)
        _draw_banner(img, lines, (ox, oy))
        return img
    except Exception:
        return None


def build_target_crop(
    frame: np.ndarray, event_dict: dict, margin: float
) -> Tuple[Optional[np.ndarray], Optional[Tuple[int, int, int, int]], dict]:
    """Full-body target crop with safe margin + baked-in box/labels (PART 4/5/8).

    Crops the FULL detection bbox (person: whole body, vehicle: whole vehicle
    — never face-only, never plate-only), expands by `margin` per side, clamps
    to the frame and draws the red box + banner on the crop pixels.

    Returns (crop, crop_rect, diagnostics). crop is None when unusable.
    """
    empty_diag = {"issues": ["no_frame"], "frame_width": 0, "frame_height": 0}
    if frame is None or not isinstance(frame, np.ndarray):
        return None, None, empty_diag
    h, w = frame.shape[:2]
    rect, diag = crop_rect(event_dict.get("bbox"), w, h, margin)
    log_diagnostics(event_dict, diag, artifact="target_crop")
    if rect is None:
        return None, None, diag
    x1, y1, x2, y2 = rect
    crop = frame[y1:y2, x1:x2].copy()
    ch, cw = crop.shape[:2]

    # Red box on the EXACT detection (crop-local coords), not the expanded
    # crop border — the margin stays as visible context around the target.
    exact, _ = crop_rect(event_dict.get("bbox"), w, h, margin=0.0)
    if exact is not None:
        ex1, ey1, ex2, ey2 = exact
        cv2.rectangle(crop, (ex1 - x1, ey1 - y1), (ex2 - x1, ey2 - y1), _BOX_COLOR, 2)
    else:
        cv2.rectangle(crop, (1, 1), (cw - 2, ch - 2), _BOX_COLOR, 2)
    _draw_banner(crop, _format_lines(event_dict), (1, 1))
    return crop, rect, diag
