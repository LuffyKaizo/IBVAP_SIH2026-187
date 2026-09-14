"""Unit tests for virtual fence, intrusion detection, and event engine."""

import sys
sys.path.insert(0, ".")

from ai.events.engine import EventEngine, Zone, point_in_polygon, VEHICLE_CLASSES
from ai.tracking.tracker import TrackedObject, TrackingResult


def make_zone(id="ZONE-01", cam="CAM-01", enabled=True):
    return Zone(
        id=id, camera_id=cam, name="Test Zone",
        points=[
            {"x": 0.2, "y": 0.2},
            {"x": 0.8, "y": 0.2},
            {"x": 0.8, "y": 0.8},
            {"x": 0.2, "y": 0.8},
        ],
        enabled=enabled,
    )


def make_track(track_id, class_name, bbox, frame_w=1920, frame_h=1080):
    cls_id = {"person": 0, "car": 2, "truck": 7}.get(class_name, 0)
    return TrackingResult(
        tracked_objects=[TrackedObject(
            track_id=track_id, class_id=cls_id, class_name=class_name,
            confidence=0.9, bbox=bbox,
        )],
        frame_width=frame_w, frame_height=frame_h, active_tracks=1,
    )


def test_point_in_polygon():
    poly = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
    assert point_in_polygon(0.5, 0.5, poly) == True   # center inside
    assert point_in_polygon(0.1, 0.1, poly) == False   # outside
    assert point_in_polygon(0.9, 0.9, poly) == False   # outside
    assert point_in_polygon(0.5, 0.15, poly) == False  # above zone
    assert point_in_polygon(0.5, 0.2, poly) == True    # boundary = inside
    print("  PASS: point_in_polygon")


def test_person_outside_zone():
    engine = EventEngine()
    zone = make_zone()
    # Person at (100, 100) on 1920x1080 -> normalized (0.052, 0.093) -> outside zone
    track = make_track(1, "person", (50, 50, 200, 200))
    events = engine.process_frame(track, "CAM-01", [zone])
    assert len(events) == 0
    print("  PASS: person outside zone -> no event")


def test_person_enters_zone():
    engine = EventEngine()
    zone = make_zone()
    # Person at (600, 400) on 1920x1080 -> normalized (0.365, 0.426) -> inside zone
    track = make_track(1, "person", (500, 300, 700, 500))
    events = engine.process_frame(track, "CAM-01", [zone])
    assert len(events) == 1
    assert events[0].event_type == "PERSON_INTRUSION"
    assert events[0].severity == "CRITICAL"
    assert events[0].status == "DETECTED"
    assert events[0].track_id == 1
    print("  PASS: person enters zone -> PERSON_INTRUSION")


def test_no_duplicate_events():
    engine = EventEngine()
    zone = make_zone()
    track = make_track(1, "person", (500, 300, 700, 500))
    # Frame 1: enter
    events1 = engine.process_frame(track, "CAM-01", [zone])
    assert len(events1) == 1
    # Frame 2: still inside
    events2 = engine.process_frame(track, "CAM-01", [zone])
    assert len(events2) == 1
    assert events2[0].status == "ACTIVE"
    # Frame 3: still inside
    events3 = engine.process_frame(track, "CAM-01", [zone])
    assert len(events3) == 1
    print("  PASS: no duplicate events while inside")


def test_person_exits_zone():
    engine = EventEngine()
    zone = make_zone()
    # Enter
    track_in = make_track(1, "person", (500, 300, 700, 500))
    engine.process_frame(track_in, "CAM-01", [zone])
    # Exit
    track_out = make_track(1, "person", (50, 50, 200, 200))
    events = engine.process_frame(track_out, "CAM-01", [zone])
    # After exit, no active events (track is still present but outside)
    active = [e for e in events if e.status != "RESOLVED"]
    assert len(active) == 0
    print("  PASS: person exits -> event resolved")


def test_person_reenters():
    engine = EventEngine()
    zone = make_zone()
    # Enter
    track_in = make_track(1, "person", (500, 300, 700, 500))
    engine.process_frame(track_in, "CAM-01", [zone])
    # Exit
    track_out = make_track(1, "person", (50, 50, 200, 200))
    engine.process_frame(track_out, "CAM-01", [zone])
    # Re-enter
    track_in2 = make_track(1, "person", (500, 300, 700, 500))
    events = engine.process_frame(track_in2, "CAM-01", [zone])
    active = [e for e in events if e.status in ("DETECTED", "ACTIVE")]
    assert len(active) == 1
    print("  PASS: person re-enters -> new event")


def test_vehicle_enters():
    engine = EventEngine()
    zone = make_zone()
    track = make_track(2, "car", (500, 300, 700, 500))
    events = engine.process_frame(track, "CAM-01", [zone])
    assert len(events) == 1
    assert events[0].event_type == "VEHICLE_INTRUSION"
    assert events[0].severity == "HIGH"
    print("  PASS: vehicle enters -> VEHICLE_INTRUSION")


def test_disabled_zone():
    engine = EventEngine()
    zone = make_zone(enabled=False)
    track = make_track(1, "person", (500, 300, 700, 500))
    events = engine.process_frame(track, "CAM-01", [zone])
    assert len(events) == 0
    print("  PASS: disabled zone -> no event")


def test_wrong_camera():
    engine = EventEngine()
    zone = make_zone(cam="CAM-01")
    track = make_track(1, "person", (500, 300, 700, 500))
    events = engine.process_frame(track, "CAM-02", [zone])
    assert len(events) == 0
    print("  PASS: wrong camera -> no event")


def test_multiple_objects():
    engine = EventEngine()
    zone = make_zone()
    t1 = TrackedObject(track_id=1, class_id=0, class_name="person", confidence=0.9, bbox=(500, 300, 700, 500))
    t2 = TrackedObject(track_id=2, class_id=2, class_name="car", confidence=0.85, bbox=(600, 350, 800, 550))
    track = TrackingResult(tracked_objects=[t1, t2], frame_width=1920, frame_height=1080, active_tracks=2)
    events = engine.process_frame(track, "CAM-01", [zone])
    assert len(events) == 2
    types = {e.event_type for e in events}
    assert "PERSON_INTRUSION" in types
    assert "VEHICLE_INTRUSION" in types
    print("  PASS: multiple objects -> independent events")


def test_track_loss_no_spam():
    engine = EventEngine()
    zone = make_zone()
    # Enter
    track_in = make_track(1, "person", (500, 300, 700, 500))
    engine.process_frame(track_in, "CAM-01", [zone])
    # Track disappears (empty frame)
    empty = TrackingResult(tracked_objects=[], frame_width=1920, frame_height=1080, active_tracks=0)
    events = engine.process_frame(empty, "CAM-01", [zone])
    # No duplicate events created
    active = [e for e in events if e.status in ("DETECTED", "ACTIVE")]
    assert len(active) <= 1  # event still exists but no new ones
    print("  PASS: track loss -> no duplicate spam")


def test_expired_track():
    engine = EventEngine()
    zone = make_zone()
    # Enter then track disappears for many frames
    track_in = make_track(1, "person", (500, 300, 700, 500))
    engine.process_frame(track_in, "CAM-01", [zone])
    empty = TrackingResult(tracked_objects=[], frame_width=1920, frame_height=1080, active_tracks=0)
    for _ in range(50):
        engine.process_frame(empty, "CAM-01", [zone])
    # Old event should not produce new intrusions
    active = [e for e in engine.get_active_events() if e.track_id == 1]
    # Event may still be in active_events (not auto-resolved yet) but no new events
    assert len(engine._event_history) == 1  # only one event ever created
    print("  PASS: expired track -> no new events")


def test_pipeline_restart():
    engine = EventEngine()
    zone = make_zone()
    track = make_track(1, "person", (500, 300, 700, 500))
    engine.process_frame(track, "CAM-01", [zone])
    # Simulate pipeline restart
    engine.resolve_all()
    assert len(engine.get_active_events()) == 0
    # New session
    events = engine.process_frame(track, "CAM-01", [zone])
    assert len(events) == 1
    assert events[0].status == "DETECTED"
    print("  PASS: pipeline restart -> clean state")


def test_video_restart():
    """Old track IDs should not leak into new video session."""
    engine = EventEngine()
    zone = make_zone()
    # Session 1
    track = make_track(1, 'person', (500, 300, 700, 500))
    engine.process_frame(track, 'CAM-01', [zone])
    # Simulate video restart (resolve + clear)
    engine.resolve_all()
    # Session 2 with new track IDs
    track2 = make_track(100, 'person', (500, 300, 700, 500))
    events = engine.process_frame(track2, 'CAM-01', [zone])
    active = [e for e in events if e.status in ('DETECTED', 'ACTIVE')]
    assert len(active) == 1
    assert events[0].track_id == 100
    assert events[0].status == 'DETECTED'
    print('  PASS: video restart -> new track IDs, clean state')


def main():
    tests = [
        test_point_in_polygon,
        test_person_outside_zone,
        test_person_enters_zone,
        test_no_duplicate_events,
        test_person_exits_zone,
        test_person_reenters,
        test_vehicle_enters,
        test_disabled_zone,
        test_wrong_camera,
        test_multiple_objects,
        test_track_loss_no_spam,
        test_expired_track,
        test_pipeline_restart,
        test_video_restart,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print('  FAIL: %s -> %s' % (t.__name__, e))
            failed += 1
    print('')
    print('================================')
    print('Results: %d passed, %d failed' % (passed, failed))
    print('================================')
    if failed > 0:
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main()
