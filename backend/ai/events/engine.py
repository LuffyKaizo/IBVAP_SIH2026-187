"""Virtual fence / restricted zone intrusion detection event engine.

Provides:
- Point-in-polygon test (ray casting)
- Tripwire line-crossing detection
- Zone management
- Intrusion event lifecycle (DETECTED -> ACTIVE -> RESOLVED)
- Event deduplication
- Orphan auto-resolve after configurable frame tolerance
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from ai.config import settings


@dataclass
class Zone:
    """A restricted zone polygon or tripwire on a camera view."""
    id: str
    camera_id: str
    name: str
    points: list[dict]  # [{"x": 0.1, "y": 0.2}, ...] normalized 0-1
    enabled: bool = True
    severity: str = "CRITICAL"
    zone_type: str = "POLYGON_ZONE"  # POLYGON_ZONE | TRIPWIRE_LINE
    rule: str = "RESTRICTED_ENTRY"  # RESTRICTED_ENTRY | BI_DIRECTIONAL | LOITERING_ONLY


@dataclass
class SecurityEvent:
    """A security intrusion event."""
    event_id: str
    event_type: str  # PERSON_INTRUSION | VEHICLE_INTRUSION
    severity: str  # CRITICAL | HIGH
    camera_id: str
    zone_id: str
    zone_name: str
    track_id: int
    object_class: str
    timestamp: str
    confidence: float
    bbox: dict
    status: str = "DETECTED"  # DETECTED | ACTIVE | RESOLVED


def point_in_polygon(x, y, polygon):
    """Ray casting algorithm for point-in-polygon test.

    Returns True if point (x, y) is inside the polygon.
    Boundary contact is treated as inside.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["x"], polygon[i]["y"]
        xj, yj = polygon[j]["x"], polygon[j]["y"]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _cross_product_sign(ax, ay, bx, by, px, py):
    """Compute cross product of vectors AB and AP.
    Returns > 0 if P is left of AB, < 0 if right, 0 if on line.
    """
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def tripwire_crossed(prev_x, prev_y, curr_x, curr_y, line_start, line_end):
    """Check if movement from (prev_x,prev_y) to (curr_x,curr_y) crosses a tripwire line.

    Uses cross product sign change to detect line crossing.
    Returns True if the path crosses the line.
    """
    d1 = _cross_product_sign(
        line_start["x"], line_start["y"],
        line_end["x"], line_end["y"],
        prev_x, prev_y,
    )
    d2 = _cross_product_sign(
        line_start["x"], line_start["y"],
        line_end["x"], line_end["y"],
        curr_x, curr_y,
    )
    # Sign change means crossing (including on-line = 0)
    return (d1 > 0 and d2 <= 0) or (d1 <= 0 and d2 > 0)


# Vehicle class names that count as vehicle intrusion
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle"}


class EventEngine:
    """Processes tracked objects against configured zones and generates intrusion events.

    Handles:
    - Polygon zone intrusion detection (point-in-polygon)
    - Tripwire line-crossing detection
    - Event lifecycle (DETECTED -> ACTIVE -> RESOLVED)
    - Deduplication (one event per track per zone entry)
    - Track loss tolerance with configurable frame counter
    """

    def __init__(self):
        self._active_events: dict[str, SecurityEvent] = {}  # key -> event
        self._event_history: list[SecurityEvent] = []
        self._track_zone_state: dict[str, bool] = {}  # "track_id:zone_id" -> was_inside
        self._track_prev_position: dict[str, tuple] = {}  # "track_id:zone_id" -> (x, y)
        self._track_missing_frames: dict[str, int] = {}  # event_key -> frames missing
        self._orphan_resolve_frames = settings.ORPHAN_RESOLVE_FRAMES

    def _make_key(self, track_id, zone_id, event_type):
        return f"{track_id}:{zone_id}:{event_type}"

    def process_frame(self, tracking_result, camera_id, zones):
        """Process a frame's tracking results against configured zones.

        Returns list of active SecurityEvent objects.
        """
        now = datetime.now(timezone.utc).isoformat()
        current_track_ids = set()
        active_events = []

        for obj in tracking_result.tracked_objects:
            if obj.class_name not in VEHICLE_CLASSES and obj.class_name != "person":
                continue

            track_id = obj.track_id
            current_track_ids.add(track_id)

            # Use ground point (bottom-center of bbox) for zone testing
            x1, y1, x2, y2 = obj.bbox
            ground_x = (x1 + x2) / 2
            ground_y = y2

            for zone in zones:
                if not zone.enabled or zone.camera_id != camera_id:
                    continue

                # Convert ground point to normalized coordinates
                norm_x = ground_x / tracking_result.frame_width if tracking_result.frame_width > 0 else 0
                norm_y = ground_y / tracking_result.frame_height if tracking_result.frame_height > 0 else 0

                if zone.zone_type == "TRIPWIRE_LINE" and len(zone.points) >= 2:
                    self._process_tripwire(track_id, obj, zone, camera_id,
                                           norm_x, norm_y, now, active_events)
                else:
                    self._process_polygon(track_id, obj, zone, camera_id,
                                          norm_x, norm_y, now, active_events)

        # Orphan auto-resolve: events for tracks missing too many frames
        keys_to_check = list(self._active_events.keys())
        for key in keys_to_check:
            event = self._active_events[key]
            track_id = event.track_id
            if track_id not in current_track_ids:
                self._track_missing_frames[key] = self._track_missing_frames.get(key, 0) + 1
                if self._track_missing_frames[key] >= self._orphan_resolve_frames:
                    event.status = "RESOLVED"
                    event.timestamp = now
                    del self._active_events[key]
                    self._track_missing_frames.pop(key, None)
            else:
                self._track_missing_frames.pop(key, None)

        # Return all currently active events
        for event in self._active_events.values():
            active_events.append(event)

        return active_events

    def _process_polygon(self, track_id, obj, zone, camera_id, norm_x, norm_y, now, active_events):
        """Process a tracked object against a polygon zone."""
        x1, y1, x2, y2 = obj.bbox
        is_inside = point_in_polygon(norm_x, norm_y, zone.points)
        state_key = self._make_key(track_id, zone.id, "")
        was_inside = self._track_zone_state.get(state_key, False)

        if is_inside and not was_inside:
            event_type = "PERSON_INTRUSION" if obj.class_name == "person" else "VEHICLE_INTRUSION"
            severity = "CRITICAL" if event_type == "PERSON_INTRUSION" else "HIGH"
            event_key = self._make_key(track_id, zone.id, event_type)

            if event_key not in self._active_events:
                event = SecurityEvent(
                    event_id=str(uuid.uuid4())[:8],
                    event_type=event_type,
                    severity=severity,
                    camera_id=camera_id,
                    zone_id=zone.id,
                    zone_name=zone.name,
                    track_id=track_id,
                    object_class=obj.class_name,
                    timestamp=now,
                    confidence=obj.confidence,
                    bbox={"x1": round(x1, 1), "y1": round(y1, 1),
                          "x2": round(x2, 1), "y2": round(y2, 1)},
                    status="DETECTED",
                )
                self._active_events[event_key] = event
                self._event_history.append(event)
            else:
                self._active_events[event_key].status = "ACTIVE"
                self._active_events[event_key].timestamp = now
                self._active_events[event_key].confidence = obj.confidence
                self._active_events[event_key].bbox = {
                    "x1": round(x1, 1), "y1": round(y1, 1),
                    "x2": round(x2, 1), "y2": round(y2, 1),
                }

        elif is_inside and was_inside:
            event_type = 'PERSON_INTRUSION' if obj.class_name == 'person' else 'VEHICLE_INTRUSION'
            event_key = self._make_key(track_id, zone.id, event_type)
            if event_key in self._active_events:
                self._active_events[event_key].status = 'ACTIVE'
                self._active_events[event_key].timestamp = now
                self._active_events[event_key].confidence = obj.confidence
                self._active_events[event_key].bbox = {
                    'x1': round(x1, 1), 'y1': round(y1, 1),
                    'x2': round(x2, 1), 'y2': round(y2, 1),
                }
        elif not is_inside and was_inside:
            event_type = 'PERSON_INTRUSION' if obj.class_name == 'person' else 'VEHICLE_INTRUSION'
            event_key = self._make_key(track_id, zone.id, event_type)
            if event_key in self._active_events:
                self._active_events[event_key].status = 'RESOLVED'
                self._active_events[event_key].timestamp = now
                del self._active_events[event_key]
        self._track_zone_state[state_key] = is_inside

    def _process_tripwire(self, track_id, obj, zone, camera_id, norm_x, norm_y, now, active_events):
        """Process a tracked object against a tripwire line zone."""
        x1, y1, x2, y2 = obj.bbox
        pos_key = f"{track_id}:{zone.id}"
        prev_pos = self._track_prev_position.get(pos_key)

        if prev_pos is not None:
            prev_x, prev_y = prev_pos
            crossed = tripwire_crossed(
                prev_x, prev_y, norm_x, norm_y,
                zone.points[0], zone.points[1],
            )
            if crossed:
                event_type = "PERSON_INTRUSION" if obj.class_name == "person" else "VEHICLE_INTRUSION"
                severity = "CRITICAL" if zone.severity == "CRITICAL" else "HIGH"
                event_key = self._make_key(track_id, zone.id, event_type)

                if event_key not in self._active_events:
                    event = SecurityEvent(
                        event_id=str(uuid.uuid4())[:8],
                        event_type=event_type,
                        severity=severity,
                        camera_id=camera_id,
                        zone_id=zone.id,
                        zone_name=zone.name,
                        track_id=track_id,
                        object_class=obj.class_name,
                        timestamp=now,
                        confidence=obj.confidence,
                        bbox={"x1": round(x1, 1), "y1": round(y1, 1),
                              "x2": round(x2, 1), "y2": round(y2, 1)},
                        status="DETECTED",
                    )
                    self._active_events[event_key] = event
                    self._event_history.append(event)
                    active_events.append(event)

        self._track_prev_position[pos_key] = (norm_x, norm_y)

    def resolve_all(self):
        """Resolve all active events — called on pipeline restart."""
        for key, event in self._active_events.items():
            event.status = "RESOLVED"
        self._active_events.clear()
        self._track_zone_state.clear()
        self._track_prev_position.clear()
        self._track_missing_frames.clear()

    def get_history(self):
        """Return event history."""
        return list(self._event_history)

    def get_active_events(self):
        """Return currently active events."""
        return list(self._active_events.values())
