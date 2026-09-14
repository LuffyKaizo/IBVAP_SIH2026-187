"""Behavior analytics engine for IBVAP."""

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ai.config import settings


def is_night_time(hour):
    start, end = settings.NIGHT_START, settings.NIGHT_END
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


@dataclass
class TrackPosition:
    x: float
    y: float
    timestamp: float


@dataclass
class LoiteringState:
    positions: deque = field(default_factory=deque)
    reference_x: float = 0.0
    reference_y: float = 0.0
    first_seen: float = 0.0
    is_loitering: bool = False
    event_id: str = ""


@dataclass
class NightMovementState:
    is_moving: bool = False
    event_id: str = ""
    last_positions: deque = field(default_factory=deque)


class BehaviorEngine:
    def __init__(self):
        self._loitering = {}
        self._night_movement = {}
        self._suspicious = {}
        self._max_positions = settings.POSITION_HISTORY_MAX

    def _track_key(self, camera_id, track_id):
        return camera_id + ":" + str(track_id)

    def _cleanup_track(self, key):
        self._loitering.pop(key, None)
        self._night_movement.pop(key, None)
        self._suspicious.pop(key, None)

    def _get_loitering_state(self, key):
        if key not in self._loitering:
            self._loitering[key] = LoiteringState(positions=deque(maxlen=self._max_positions))
        return self._loitering[key]

    def _get_night_state(self, key):
        if key not in self._night_movement:
            self._night_movement[key] = NightMovementState(last_positions=deque(maxlen=10))
        return self._night_movement[key]

    def _compute_displacement(self, positions):
        if len(positions) < 2:
            return 0.0
        rx, ry = positions[0].x, positions[0].y
        md = 0.0
        for p in positions:
            d = ((p.x - rx)**2 + (p.y - ry)**2) ** 0.5
            if d > md:
                md = d
        return md

    def _compute_recent_displacement(self, positions, window=5):
        if len(positions) < 2:
            return 0.0
        recent = list(positions)[-window:]
        # Displacement of the most recent step only
        p1, p2 = recent[-2], recent[-1]
        return ((p2.x - p1.x)**2 + (p2.y - p1.y)**2) ** 0.5

    def _make_event(self, etype, sev, cam, tid, cls, obj, now, status, **extra):
        x1, y1, x2, y2 = obj.bbox
        ev = {
            "event_id": str(uuid.uuid4())[:8],
            "event_type": etype,
            "severity": sev,
            "camera_id": cam,
            "zone_id": "",
            "zone_name": "",
            "track_id": tid,
            "object_class": cls,
            "timestamp": now.isoformat(),
            "confidence": obj.confidence,
            "bbox": {"x1": round(x1,1), "y1": round(y1,1), "x2": round(x2,1), "y2": round(y2,1)},
            "status": status,
        }
        ev.update(extra)
        return ev

    def process_frame(self, tracking_result, camera_id, now=None):
        if now is None:
            now = datetime.now(timezone.utc)
        events = []
        current_track_ids = set()
        t = now.timestamp()
        for obj in tracking_result.tracked_objects:
            tid = obj.track_id
            cn = obj.class_name
            current_track_ids.add(tid)
            x1, y1, x2, y2 = obj.bbox
            fw, fh = tracking_result.frame_width, tracking_result.frame_height
            nx = (x1 + x2) / 2 / fw if fw > 0 else 0
            ny = y2 / fh if fh > 0 else 0
            key = self._track_key(camera_id, tid)
            pos = TrackPosition(x=nx, y=ny, timestamp=t)
            lev = self._check_loitering(key, tid, camera_id, cn, pos, obj, now)
            if lev:
                events.append(lev)
            nev = self._check_night_movement(key, tid, camera_id, cn, pos, obj, now)
            if nev:
                events.append(nev)
        for key in list(self._loitering.keys()):
            if int(key.split(":")[1]) not in current_track_ids:
                self._cleanup_track(key)
        return events

    def _check_loitering(self, key, tid, cam, cn, pos, obj, now):
        st = self._get_loitering_state(key)
        st.positions.append(pos)
        if st.first_seen == 0:
            st.first_seen = pos.timestamp
            st.reference_x = pos.x
            st.reference_y = pos.y
        disp = self._compute_displacement(st.positions)
        dur = pos.timestamp - st.first_seen
        threshold = settings.LOITERING_THRESHOLD_SECONDS
        mov_thresh = settings.LOITERING_MOVEMENT_THRESHOLD
        should = disp < mov_thresh and dur >= threshold
        reason = "Low movement for %d+ seconds (disp: %.4f)" % (threshold, disp)
        if should and not st.is_loitering:
            st.is_loitering = True
            st.event_id = str(uuid.uuid4())[:8]
            return self._make_event("LOITERING", "MEDIUM", cam, tid, cn, obj, now, "DETECTED",
                event_id=st.event_id, duration_seconds=round(dur,1), displacement=round(disp,4), reason=reason)
        elif should and st.is_loitering:
            return self._make_event("LOITERING", "MEDIUM", cam, tid, cn, obj, now, "ACTIVE",
                event_id=st.event_id, duration_seconds=round(dur,1), displacement=round(disp,4), reason=reason)
        elif not should and st.is_loitering:
            eid = st.event_id
            # Remove state entirely so re-entry creates fresh episode
            self._loitering.pop(key, None)
            return self._make_event("LOITERING", "MEDIUM", cam, tid, cn, obj, now, "RESOLVED",
                event_id=eid, reason="Movement increased")
        return None

    def _check_night_movement(self, key, tid, cam, cn, pos, obj, now):
        hour = now.hour
        night = is_night_time(hour)
        st = self._get_night_state(key)
        st.last_positions.append(pos)
        disp = self._compute_recent_displacement(st.last_positions, window=5)
        moving = disp > settings.MOVEMENT_THRESHOLD
        if night and moving and not st.is_moving:
            st.is_moving = True
            st.event_id = str(uuid.uuid4())[:8]
            return self._make_event("NIGHT_MOVEMENT", "HIGH", cam, tid, cn, obj, now, "DETECTED",
                event_id=st.event_id, reason="Movement during night hours (%02d:00)" % hour)
        elif night and moving and st.is_moving:
            return self._make_event("NIGHT_MOVEMENT", "HIGH", cam, tid, cn, obj, now, "ACTIVE",
                event_id=st.event_id, reason="Movement during night hours (%02d:00)" % hour)
        elif st.is_moving and (not night or not moving):
            eid = st.event_id
            st.is_moving = False
            st.event_id = ""
            return self._make_event("NIGHT_MOVEMENT", "HIGH", cam, tid, cn, obj, now, "RESOLVED",
                event_id=eid, reason="Night movement ended")
        return None

    def evaluate_suspicious(self, all_events, camera_id, now=None):
        if now is None:
            now = datetime.now(timezone.utc)
        sus_events = []
        track_events = {}
        for ev in all_events:
            tid = ev.get("track_id", -1)
            track_events.setdefault(tid, []).append(ev)
        for tid, events in track_events.items():
            etypes = {e["event_type"] for e in events}
            reasons = []
            sev = "HIGH"
            if "NIGHT_MOVEMENT" in etypes:
                reasons.append("NIGHT_MOVEMENT")
            if "LOITERING" in etypes and ("PERSON_INTRUSION" in etypes or "VEHICLE_INTRUSION" in etypes):
                reasons.extend(["LOITERING", "RESTRICTED_ZONE"])
            if "NIGHT_MOVEMENT" in etypes and ("PERSON_INTRUSION" in etypes or "VEHICLE_INTRUSION" in etypes):
                if "NIGHT_MOVEMENT" not in reasons:
                    reasons.append("NIGHT_MOVEMENT")
                reasons.append("RESTRICTED_ZONE")
                sev = "CRITICAL"
            if "PERSON_INTRUSION" in etypes and is_night_time(now.hour):
                if "RESTRICTED_ZONE" not in reasons:
                    reasons.append("RESTRICTED_ZONE")
                reasons.append("NIGHTTIME")
                sev = "CRITICAL"
            if not reasons:
                continue
            sk = camera_id + ":" + str(tid)
            det = events[0]
            if sk in self._suspicious:
                ex = self._suspicious[sk]
                active = any(e["status"] in ("DETECTED", "ACTIVE") for e in events)
                if active:
                    ex["reasons"] = list(set(reasons))
                    ex["severity"] = sev
                    ex["timestamp"] = now.isoformat()
                    ex["status"] = "ACTIVE"
                    ex["bbox"] = det.get("bbox", {})
                    sus_events.append(ex)
                else:
                    ex["status"] = "RESOLVED"
                    ex["timestamp"] = now.isoformat()
                    sus_events.append(ex)
                    del self._suspicious[sk]
            else:
                sus = {
                    "event_id": str(uuid.uuid4())[:8],
                    "event_type": "SUSPICIOUS_ACTIVITY",
                    "severity": sev,
                    "camera_id": camera_id,
                    "zone_id": "",
                    "zone_name": "",
                    "track_id": tid,
                    "object_class": det.get("object_class", "unknown"),
                    "timestamp": now.isoformat(),
                    "confidence": det.get("confidence", 0),
                    "bbox": det.get("bbox", {}),
                    "status": "DETECTED",
                    "reasons": list(set(reasons)),
                }
                self._suspicious[sk] = sus
                sus_events.append(sus)
        for sk in list(self._suspicious.keys()):
            if int(sk.split(":")[1]) not in track_events:
                s = self._suspicious[sk]
                s["status"] = "RESOLVED"
                s["timestamp"] = now.isoformat()
                sus_events.append(s)
                del self._suspicious[sk]
        return sus_events

    def resolve_all(self):
        self._loitering.clear()
        self._night_movement.clear()
        for s in self._suspicious.values():
            s["status"] = "RESOLVED"
        self._suspicious.clear()

