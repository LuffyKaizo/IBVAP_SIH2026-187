"""ContextEngine — deterministic rule-based contextual analysis layer.

Analyzes tracked objects for:
- Dwell time inside zones
- Contextual loitering (zone-based, alongside BehaviorEngine)
- Fence proximity
- Movement direction
- Repeated entry

Produces per-track TrackContext and contextual events.
No ML models, no network calls, no database queries per frame.
"""

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from ai.config import settings
from ai.events.engine import Zone


@dataclass
class TrackContext:
    """Per-track contextual state, computed each frame."""
    track_id: int
    object_class: str
    center_x: float          # normalized center x
    center_y: float          # normalized center y (bottom of bbox)
    dwell_seconds: float     # time inside current zone
    current_zone_id: str     # which zone the track is in (or "")
    loitering: bool          # zone-based loitering
    loitering_seconds: float
    fence_proximity: bool    # within warning distance of any fence
    distance_to_fence: float # normalized distance to nearest fence edge
    direction: str           # camera-frame direction
    direction_vector: tuple  # (dx, dy) normalized per frame
    repeated_entry: bool     # entered same zone > N times in window
    entry_count: int         # entries in current window
    zone_severity: str       # severity of the zone being interacted with


@dataclass
class _TrackState:
    """Internal per-track state for temporal analysis."""
    positions: deque = field(default_factory=lambda: deque(maxlen=30))
    zone_entries: dict = field(default_factory=dict)   # zone_id -> [entry_timestamps]
    zone_inside_since: float = 0.0                     # when entered current zone
    current_zone_id: str = ""
    loitering_start: float = 0.0
    loitering_ref_x: float = 0.0
    loitering_ref_y: float = 0.0
    loitering_emitted: bool = False
    dwell_emitted_zone: str = ""       # zone_id for which DWELL was emitted
    fence_proximity_emitted: bool = False
    repeated_entry_emitted_zone: str = ""
    last_direction: str = ""
    last_seen: float = 0.0


def _point_to_polygon_distance(px, py, polygon):
    """Minimum distance from point (px,py) to polygon boundary (normalized coords)."""
    if not polygon or len(polygon) < 2:
        return float("inf")
    min_dist = float("inf")
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]["x"], polygon[i]["y"]
        x2, y2 = polygon[(i + 1) % n]["x"], polygon[(i + 1) % n]["y"]
        dx, dy = x2 - x1, y2 - y1
        len_sq = dx * dx + dy * dy
        if len_sq == 0:
            dist = ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
        else:
            t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            dist = ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
        if dist < min_dist:
            min_dist = dist
    return min_dist


def _compute_direction(positions, min_frames=3):
    """Compute direction string from recent positions deque."""
    if len(positions) < min_frames:
        return "", (0.0, 0.0)

    recent = list(positions)[-min_frames:]
    dx = recent[-1][0] - recent[0][0]
    dy = recent[-1][1] - recent[0][1]

    if abs(dx) < 0.005 and abs(dy) < 0.005:
        return "STATIONARY", (dx, dy)

    if abs(dx) > abs(dy):
        direction = "LEFT_TO_RIGHT" if dx > 0 else "RIGHT_TO_LEFT"
    else:
        direction = "TOP_TO_BOTTOM" if dy > 0 else "BOTTOM_TO_TOP"

    return direction, (dx, dy)


class ContextEngine:
    """Deterministic rule-based contextual analysis layer."""

    def __init__(self):
        self._track_states: dict[int, _TrackState] = {}  # track_id -> state
        self._max_track_age_sec = 30.0  # clean tracks not seen for this long

    def _get_state(self, track_id: int) -> _TrackState:
        if track_id not in self._track_states:
            self._track_states[track_id] = _TrackState()
        return self._track_states[track_id]

    def _cleanup_stale_tracks(self):
        """Remove tracks not seen recently to bound memory."""
        now = time.time()
        stale = [tid for tid, s in self._track_states.items()
                 if now - s.last_seen > self._max_track_age_sec]
        for tid in stale:
            del self._track_states[tid]

    def process_frame(self, tracking_result, camera_id, zones, frame_width=0, frame_height=0):
        """Process a frame's tracking results for contextual analysis.

        Returns:
            (list[TrackContext], list[dict]) — per-track contexts and context events
        """
        now = time.time()
        contexts = []
        events = []
        current_track_ids = set()

        for obj in tracking_result.tracked_objects:
            if obj.class_name not in ("person", "car", "motorcycle", "bus", "truck"):
                continue

            track_id = obj.track_id
            current_track_ids.add(track_id)
            state = self._get_state(track_id)
            state.last_seen = now

            x1, y1, x2, y2 = obj.bbox
            fw = tracking_result.frame_width if tracking_result.frame_width > 0 else (frame_width or 1)
            fh = tracking_result.frame_height if tracking_result.frame_height > 0 else (frame_height or 1)

            center_x = (x1 + x2) / 2 / fw
            center_y = y2 / fh  # bottom-center (ground point)
            state.positions.append((center_x, center_y, now))

            # Determine which zone the track is currently in
            inside_zone = None
            inside_zone_obj = None
            for zone in zones:
                if not zone.enabled or zone.camera_id != camera_id:
                    continue
                if zone.zone_type == "TRIPWIRE_LINE":
                    continue  # tripwire is crossing-based, not membership-based
                from ai.events.engine import point_in_polygon
                if point_in_polygon(center_x, center_y, zone.points):
                    inside_zone = zone
                    inside_zone_obj = zone
                    break

            # === DWELL TIME ===
            if inside_zone:
                if state.current_zone_id != inside_zone.id:
                    # Entered a new zone
                    state.current_zone_id = inside_zone.id
                    state.zone_inside_since = now
                    state.dwell_emitted_zone = ""
                    # Track entry for repeated entry
                    entries = state.zone_entries.setdefault(inside_zone.id, [])
                    entries.append(now)
                    # Trim old entries outside window
                    cutoff = now - settings.CONTEXT_REPEATED_ENTRY_WINDOW_SEC
                    state.zone_entries[inside_zone.id] = [t for t in entries if t > cutoff]

                dwell = now - state.zone_inside_since
                if (dwell >= settings.CONTEXT_DWELL_THRESHOLD_SEC
                        and state.dwell_emitted_zone != inside_zone.id):
                    events.append({
                        "event_id": str(uuid.uuid4())[:8],
                        "event_type": "DWELL_THRESHOLD",
                        "severity": "MEDIUM",
                        "camera_id": camera_id,
                        "zone_id": inside_zone.id,
                        "zone_name": inside_zone.name,
                        "track_id": track_id,
                        "object_class": obj.class_name,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "confidence": obj.confidence,
                        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                        "status": "DETECTED",
                        "dwell_seconds": round(dwell, 1),
                    })
                    state.dwell_emitted_zone = inside_zone.id
            else:
                state.current_zone_id = ""
                state.zone_inside_since = 0.0
                state.dwell_emitted_zone = ""

            # === CONTEXTUAL LOITERING ===
            dwell_time = now - state.zone_inside_since if state.zone_inside_since > 0 else 0
            if inside_zone and not state.loitering_emitted:
                if state.loitering_start == 0:
                    state.loitering_start = now
                    state.loitering_ref_x = center_x
                    state.loitering_ref_y = center_y
                else:
                    displacement = ((center_x - state.loitering_ref_x) ** 2
                                    + (center_y - state.loitering_ref_y) ** 2) ** 0.5
                    loiter_duration = now - state.loitering_start
                    if displacement <= settings.CONTEXT_LOITERING_RADIUS:
                        if loiter_duration >= settings.CONTEXT_LOITERING_THRESHOLD_SEC:
                            events.append({
                                "event_id": str(uuid.uuid4())[:8],
                                "event_type": "LOITERING",
                                "severity": "MEDIUM",
                                "camera_id": camera_id,
                                "zone_id": inside_zone.id,
                                "zone_name": inside_zone.name,
                                "track_id": track_id,
                                "object_class": obj.class_name,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                                "confidence": obj.confidence,
                                "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                                "status": "DETECTED",
                                "loitering_seconds": round(loiter_duration, 1),
                            })
                            state.loitering_emitted = True
                    else:
                        # Moved too far — reset loitering
                        state.loitering_start = now
                        state.loitering_ref_x = center_x
                        state.loitering_ref_y = center_y
            elif not inside_zone:
                state.loitering_start = 0.0
                state.loitering_ref_x = 0.0
                state.loitering_ref_y = 0.0
                state.loitering_emitted = False

            # === FENCE PROXIMITY ===
            min_fence_dist = float("inf")
            for zone in zones:
                if not zone.enabled or zone.camera_id != camera_id:
                    continue
                dist = _point_to_polygon_distance(center_x, center_y, zone.points)
                if dist < min_fence_dist:
                    min_fence_dist = dist

            fence_prox = min_fence_dist <= settings.CONTEXT_FENCE_PROXIMITY_DISTANCE
            if fence_prox and not state.fence_proximity_emitted:
                events.append({
                    "event_id": str(uuid.uuid4())[:8],
                    "event_type": "FENCE_PROXIMITY",
                    "severity": "MEDIUM",
                    "camera_id": camera_id,
                    "zone_id": inside_zone.id if inside_zone else "",
                    "zone_name": inside_zone.name if inside_zone else "",
                    "track_id": track_id,
                    "object_class": obj.class_name,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                    "confidence": obj.confidence,
                    "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                    "status": "DETECTED",
                    "distance_to_fence": round(min_fence_dist, 4),
                })
                state.fence_proximity_emitted = True
            elif not fence_prox:
                state.fence_proximity_emitted = False

            # === DIRECTION ===
            direction, direction_vec = _compute_direction(
                state.positions, settings.CONTEXT_DIRECTION_MIN_FRAMES
            )

            # Determine APPROACHING / MOVING_AWAY if in or near a zone
            if inside_zone and direction != "STATIONARY":
                zone_cx = sum(p["x"] for p in inside_zone.points) / len(inside_zone.points)
                zone_cy = sum(p["y"] for p in inside_zone.points) / len(inside_zone.points)
                prev = state.positions[-2] if len(state.positions) >= 2 else (center_x, center_y, now)
                prev_dist = ((prev[0] - zone_cx) ** 2 + (prev[1] - zone_cy) ** 2) ** 0.5
                curr_dist = ((center_x - zone_cx) ** 2 + (center_y - zone_cy) ** 2) ** 0.5
                if curr_dist < prev_dist:
                    direction = "APPROACHING_FENCE"
                elif curr_dist > prev_dist * 1.05:
                    direction = "MOVING_AWAY"

            # === REPEATED ENTRY ===
            repeated_entry = False
            entry_count = 0
            if inside_zone:
                entries = state.zone_entries.get(inside_zone.id, [])
                cutoff = now - settings.CONTEXT_REPEATED_ENTRY_WINDOW_SEC
                recent_entries = [t for t in entries if t > cutoff]
                entry_count = len(recent_entries)
                if (entry_count >= settings.CONTEXT_REPEATED_ENTRY_COUNT
                        and state.repeated_entry_emitted_zone != inside_zone.id):
                    events.append({
                        "event_id": str(uuid.uuid4())[:8],
                        "event_type": "REPEATED_ENTRY",
                        "severity": "HIGH",
                        "camera_id": camera_id,
                        "zone_id": inside_zone.id,
                        "zone_name": inside_zone.name,
                        "track_id": track_id,
                        "object_class": obj.class_name,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "confidence": obj.confidence,
                        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                        "status": "DETECTED",
                        "entry_count": entry_count,
                    })
                    state.repeated_entry_emitted_zone = inside_zone.id
                    repeated_entry = True
                elif entry_count >= settings.CONTEXT_REPEATED_ENTRY_COUNT:
                    repeated_entry = True
            else:
                state.repeated_entry_emitted_zone = ""

            loitering_duration = now - state.loitering_start if state.loitering_start > 0 else 0

            contexts.append(TrackContext(
                track_id=track_id,
                object_class=obj.class_name,
                center_x=round(center_x, 4),
                center_y=round(center_y, 4),
                dwell_seconds=round(dwell_time, 1),
                current_zone_id=state.current_zone_id,
                loitering=state.loitering_emitted,
                loitering_seconds=round(loitering_duration, 1),
                fence_proximity=fence_prox,
                distance_to_fence=round(min_fence_dist, 4) if min_fence_dist != float("inf") else 1.0,
                direction=direction or "UNKNOWN",
                direction_vector=(round(direction_vec[0], 4), round(direction_vec[1], 4)),
                repeated_entry=repeated_entry,
                entry_count=entry_count,
                zone_severity=inside_zone_obj.severity if inside_zone_obj else "HIGH",
            ))

        # Cleanup stale tracks periodically
        if len(self._track_states) > 100:
            self._cleanup_stale_tracks()

        return contexts, events
