"""Unit tests for loitering, night movement, and suspicious activity."""

import sys
sys.path.insert(0, ".")

from datetime import datetime, timezone, timedelta
from ai.events.behavior import BehaviorEngine, is_night_time
from ai.events.engine import EventEngine, Zone
from ai.tracking.tracker import TrackedObject, TrackingResult
from ai.config import settings


def make_track(track_id, class_name, bbox, frame_w=1920, frame_h=1080):
    cls_id = {"person": 0, "car": 2, "truck": 7}.get(class_name, 0)
    return TrackingResult(
        tracked_objects=[TrackedObject(
            track_id=track_id, class_id=cls_id, class_name=class_name,
            confidence=0.9, bbox=bbox,
        )],
        frame_width=frame_w, frame_height=frame_h, active_tracks=1,
    )


def make_zone(id="ZONE-01", cam="CAM-01"):
    return Zone(
        id=id, camera_id=cam, name="Test Zone",
        points=[{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2},
                {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
    )


def make_time(hour, minute=0, second=0):
    return datetime(2026, 9, 4, hour, minute, second, tzinfo=timezone.utc)

# === LOITERING TESTS ===

def test_person_moves_significantly():
    eng = BehaviorEngine()
    t = make_time(12, 0)
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    t2 = t + timedelta(seconds=35)
    ev = eng.process_frame(make_track(1, "person", (1500, 300, 1700, 500)), "CAM-01", now=t2)
    loiter = [e for e in ev if e["event_type"] == "LOITERING"]
    assert len(loiter) == 0
    print("  PASS: person moves significantly")

def test_person_stationary_short_time():
    eng = BehaviorEngine()
    t = make_time(12, 0)
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    t2 = t + timedelta(seconds=10)
    ev = eng.process_frame(make_track(1, "person", (502, 301, 702, 501)), "CAM-01", now=t2)
    loiter = [e for e in ev if e["event_type"] == "LOITERING"]
    assert len(loiter) == 0
    print("  PASS: stationary short time")

def test_person_loitering_detected():
    eng = BehaviorEngine()
    t = make_time(12, 0)
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    t2 = t + timedelta(seconds=35)
    ev = eng.process_frame(make_track(1, "person", (502, 301, 702, 501)), "CAM-01", now=t2)
    loiter = [e for e in ev if e["event_type"] == "LOITERING"]
    assert len(loiter) == 1
    assert loiter[0]["status"] == "DETECTED"
    assert loiter[0]["severity"] == "LOW"
    print("  PASS: loitering detected")
def test_no_duplicate_loitering():
    eng = BehaviorEngine()
    t = make_time(12, 0)
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    t2 = t + timedelta(seconds=35)
    ev2 = eng.process_frame(make_track(1, "person", (502, 301, 702, 501)), "CAM-01", now=t2)
    assert any(e["event_type"] == "LOITERING" and e["status"] == "DETECTED" for e in ev2)
    t3 = t + timedelta(seconds=40)
    ev3 = eng.process_frame(make_track(1, "person", (503, 302, 703, 502)), "CAM-01", now=t3)
    loiter3 = [e for e in ev3 if e["event_type"] == "LOITERING"]
    assert len(loiter3) == 1
    assert loiter3[0]["status"] == "ACTIVE"
    print("  PASS: no duplicate loitering")

def test_loitering_resolves():
    eng = BehaviorEngine()
    t = make_time(12, 0)
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    eng.process_frame(make_track(1, "person", (502, 301, 702, 501)), "CAM-01", now=t + timedelta(seconds=35))
    ev = eng.process_frame(make_track(1, "person", (1500, 300, 1700, 500)), "CAM-01", now=t + timedelta(seconds=36))
    loiter = [e for e in ev if e["event_type"] == "LOITERING"]
    assert len(loiter) == 1
    assert loiter[0]["status"] == "RESOLVED"
    print("  PASS: loitering resolves")

def test_loitering_reentry():
    eng = BehaviorEngine()
    t = make_time(12, 0)
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    eng.process_frame(make_track(1, "person", (502, 301, 702, 501)), "CAM-01", now=t + timedelta(seconds=35))
    eng.process_frame(make_track(1, "person", (1500, 300, 1700, 500)), "CAM-01", now=t + timedelta(seconds=36))
    # Re-entry at t+100, loiter again for 35s
    t_re = t + timedelta(seconds=100)
    eng.process_frame(make_track(1, "person", (502, 301, 702, 501)), "CAM-01", now=t_re)
    ev = eng.process_frame(make_track(1, "person", (503, 302, 703, 502)), "CAM-01", now=t_re + timedelta(seconds=35))
    loiter = [e for e in ev if e["event_type"] == "LOITERING"]
    assert len(loiter) == 1
    assert loiter[0]["status"] == "DETECTED"
    print("  PASS: loitering reentry")
# === NIGHT MOVEMENT TESTS ===

def test_daytime_moving_person():
    eng = BehaviorEngine()
    t = make_time(12, 0)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    night = [e for e in ev if e["event_type"] == "NIGHT_MOVEMENT"]
    assert len(night) == 0
    print("  PASS: daytime moving person -> no night movement")

def test_night_moving_person():
    eng = BehaviorEngine()
    t = make_time(23, 0)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    night = [e for e in ev if e["event_type"] == "NIGHT_MOVEMENT"]
    assert len(night) == 1
    assert night[0]["status"] == "DETECTED"
    assert night[0]["severity"] == "HIGH"
    print("  PASS: night moving person -> NIGHT_MOVEMENT")

def test_midnight_movement():
    eng = BehaviorEngine()
    t = make_time(0, 30)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    night = [e for e in ev if e["event_type"] == "NIGHT_MOVEMENT"]
    assert len(night) == 1
    print("  PASS: midnight movement -> NIGHT_MOVEMENT")

def test_early_morning_movement():
    eng = BehaviorEngine()
    t = make_time(4, 59)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    night = [e for e in ev if e["event_type"] == "NIGHT_MOVEMENT"]
    assert len(night) == 1
    print("  PASS: 04:59 movement -> NIGHT_MOVEMENT")

def test_dawn_no_night_movement():
    eng = BehaviorEngine()
    t = make_time(5, 0)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    night = [e for e in ev if e["event_type"] == "NIGHT_MOVEMENT"]
    assert len(night) == 0
    print("  PASS: 05:00 -> no night movement")

def test_night_stationary_person():
    eng = BehaviorEngine()
    t = make_time(23, 30)
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (501, 301, 701, 501)), "CAM-01", now=t + timedelta(seconds=1))
    night = [e for e in ev if e["event_type"] == "NIGHT_MOVEMENT"]
    assert len(night) == 0
    print("  PASS: night stationary -> no night movement")
# === SUSPICIOUS ACTIVITY TESTS ===

def test_night_movement_suspicious():
    eng = BehaviorEngine()
    t = make_time(23, 0)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    sus = eng.evaluate_suspicious(ev, "CAM-01", now=t + timedelta(seconds=1))
    active_sus = [s for s in sus if s["event_type"] == "SUSPICIOUS_ACTIVITY" and s["status"] in ("DETECTED", "ACTIVE")]
    assert len(active_sus) == 1
    assert active_sus[0]["severity"] == "HIGH"
    assert "NIGHT_MOVEMENT" in active_sus[0]["reasons"]
    print("  PASS: night movement -> suspicious activity")

def test_loitering_in_zone_suspicious():
    eng_b = BehaviorEngine()
    eng_e = EventEngine()
    zone = make_zone()
    t = make_time(12, 0)
    # Person enters zone (intrusion)
    tr1 = make_track(1, "person", (600, 400, 800, 600))
    zone_ev = eng_e.process_frame(tr1, "CAM-01", [zone])
    # Person stays (loitering)
    for i in range(36):
        t_f = t + timedelta(seconds=i)
        eng_b.process_frame(tr1, "CAM-01", now=t_f)
    # Final frame: loitering + intrusion
    t_final = t + timedelta(seconds=36)
    zone_ev2 = eng_e.process_frame(tr1, "CAM-01", [zone])
    bev = eng_b.process_frame(tr1, "CAM-01", now=t_final)
    all_ev_raw = zone_ev + zone_ev2 + bev
    all_ev = [e.__dict__ if hasattr(e, 'event_type') and not isinstance(e, dict) else e for e in all_ev_raw]
    sus = eng_b.evaluate_suspicious(all_ev, "CAM-01", now=t_final)
    sus_types = [s for s in sus if s["event_type"] == "SUSPICIOUS_ACTIVITY"
                 and s["status"] in ("DETECTED", "ACTIVE")]
    assert len(sus_types) >= 1
    assert "LOITERING" in sus_types[0]["reasons"]
    assert "RESTRICTED_ZONE" in sus_types[0]["reasons"]
    print("  PASS: loitering + zone -> suspicious")

def test_night_movement_in_zone_suspicious():
    eng_b = BehaviorEngine()
    eng_e = EventEngine()
    zone = make_zone()
    t = make_time(23, 0)
    tr = make_track(1, "person", (600, 400, 800, 600))
    zone_ev = eng_e.process_frame(tr, "CAM-01", [zone])
    eng_b.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    bev = eng_b.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    all_ev = zone_ev + bev
    all_ev_dicts = [e.__dict__ if hasattr(e, 'event_type') and not isinstance(e, dict) else e for e in all_ev]
    sus = eng_b.evaluate_suspicious(all_ev_dicts, "CAM-01", now=t + timedelta(seconds=1))
    sus_types = [s for s in sus if s["event_type"] == "SUSPICIOUS_ACTIVITY"
                 and s["status"] in ("DETECTED", "ACTIVE")]
    assert len(sus_types) >= 1
    assert "NIGHT_MOVEMENT" in sus_types[0]["reasons"]
    assert "RESTRICTED_ZONE" in sus_types[0]["reasons"]
    assert sus_types[0]["severity"] == "CRITICAL"
    print("  PASS: night + zone -> CRITICAL suspicious")

def test_daytime_normal_no_suspicious():
    eng_b = BehaviorEngine()
    t = make_time(12, 0)
    eng_b.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    bev = eng_b.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    sus = eng_b.evaluate_suspicious(bev, "CAM-01", now=t + timedelta(seconds=1))
    assert len(sus) == 0
    print("  PASS: daytime normal -> no suspicious")

def test_two_tracks_independent():
    eng = BehaviorEngine()
    t = make_time(23, 0)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    eng.process_frame(make_track(2, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    ev1 = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    ev2 = eng.process_frame(make_track(2, "person", (501, 301, 701, 501)), "CAM-01", now=t + timedelta(seconds=1))
    all_ev = ev1 + ev2
    sus = eng.evaluate_suspicious(all_ev, "CAM-01", now=t + timedelta(seconds=1))
    for s in sus:
        if s["event_type"] == "SUSPICIOUS_ACTIVITY":
            assert s["track_id"] in (1, 2)
    print("  PASS: two tracks independent suspicious")
# === RESTART TESTS ===

def test_resolve_all_clears_behavior():
    eng = BehaviorEngine()
    t = make_time(23, 0)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    # Create some loitering state
    eng.process_frame(make_track(1, "person", (500, 300, 700, 500)), "CAM-01", now=t)
    for i in range(36):
        eng.process_frame(make_track(1, "person", (502, 301, 702, 501)), "CAM-01", now=t + timedelta(seconds=i))
    eng.resolve_all()
    assert len(eng._loitering) == 0
    assert len(eng._night_movement) == 0
    assert len(eng._suspicious) == 0
    print("  PASS: resolve_all clears behavior state")

def test_night_movement_resolves():
    eng = BehaviorEngine()
    t = make_time(23, 0)
    eng.process_frame(make_track(1, "person", (100, 100, 300, 300)), "CAM-01", now=t)
    ev = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=1))
    nm = [e for e in ev if e["event_type"] == "NIGHT_MOVEMENT" and e["status"] in ("DETECTED","ACTIVE")]
    assert len(nm) == 1
    # Person stops moving (same position)
    ev2 = eng.process_frame(make_track(1, "person", (200, 100, 400, 300)), "CAM-01", now=t + timedelta(seconds=2))
    nm_all = [e for e in ev2 if e["event_type"] == "NIGHT_MOVEMENT"]
    nm_resolved = [e for e in nm_all if e["status"] == "RESOLVED"]
    assert len(nm_resolved) == 1
    print("  PASS: night movement resolves")

# === MAIN ===

def main():
    tests = [
        # Loitering
        test_person_moves_significantly,
        test_person_stationary_short_time,
        test_person_loitering_detected,
        test_no_duplicate_loitering,
        test_loitering_resolves,
        test_loitering_reentry,
        # Night
        test_daytime_moving_person,
        test_night_moving_person,
        test_midnight_movement,
        test_early_morning_movement,
        test_dawn_no_night_movement,
        test_night_stationary_person,
        test_night_movement_resolves,
        # Suspicious
        test_night_movement_suspicious,
        test_loitering_in_zone_suspicious,
        test_night_movement_in_zone_suspicious,
        test_daytime_normal_no_suspicious,
        test_two_tracks_independent,
        # Restart
        test_resolve_all_clears_behavior,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print("  FAIL: %s -> %s" % (t.__name__, e))
            failed += 1
    print("")
    print("================================")
    print("Results: %d passed, %d failed" % (passed, failed))
    print("================================")
    if failed > 0:
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()
