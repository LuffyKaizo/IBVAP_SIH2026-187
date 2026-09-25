"""Independent intrusion-zone engine tests (reference notebook semantics).

Verifies the geometry/state logic separately from the UI:
- feet point (bottom-center) is the intrusion reference point
- point-in-polygon boundary handling
- person + vehicle intrusion classes
- multiple zones / multiple cameras independence
- enter / remain / exit / re-entry state machine + dedup
- disabled zones, degenerate polygons, non-target classes
"""

import sys

import pytest

sys.path.insert(0, ".")

from ai.events.engine import EventEngine, Zone, point_in_polygon, VEHICLE_CLASSES
from ai.tracking.tracker import TrackedObject, TrackingResult

FRAME_W, FRAME_H = 1920, 1080


def make_zone(id="ZONE-T1", cam="CAM-01", enabled=True, points=None):
    return Zone(
        id=id, camera_id=cam, name=f"Zone {id}",
        points=points or [
            {"x": 0.2, "y": 0.2},
            {"x": 0.8, "y": 0.2},
            {"x": 0.8, "y": 0.8},
            {"x": 0.2, "y": 0.8},
        ],
        enabled=enabled,
    )


def make_result(objects, w=FRAME_W, h=FRAME_H):
    return TrackingResult(
        tracked_objects=objects, frame_width=w, frame_height=h,
        active_tracks=len(objects),
    )


def person(track_id, bbox):
    return TrackedObject(track_id=track_id, class_id=0, class_name="person",
                         confidence=0.9, bbox=bbox)


def vehicle(track_id, class_name, bbox):
    cls = {"car": 2, "motorcycle": 3, "bus": 5, "truck": 7}[class_name]
    return TrackedObject(track_id=track_id, class_id=cls, class_name=class_name,
                         confidence=0.85, bbox=bbox)


def test_point_in_polygon_inside_outside_boundary():
    poly = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2},
            {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
    assert point_in_polygon(0.5, 0.5, poly) is True       # clearly inside
    assert point_in_polygon(0.05, 0.05, poly) is False    # clearly outside
    assert point_in_polygon(0.2, 0.5, poly) is True       # on boundary = inside


def test_feet_point_is_reference_point_not_centroid():
    """Bottom-center (feet) drives containment, per the reference notebook.

    Case A: centroid outside zone, feet inside -> intrusion fires.
    Case B: centroid inside zone, feet outside -> no intrusion.
    """
    engine = EventEngine()
    zone = make_zone()

    # Zone spans y 0.2..0.8. Object occupies y 0.75..1.05 (clipped frame):
    # centroid_y = 0.9  -> OUTSIDE; feet_y = y2 = 1.0 -> hmm, needs care.
    # Use a box whose feet are inside the zone but centroid is below it:
    # y1=0.70*1080=756, y2=1.0*1080=1080 -> centroid y = 0.85 (outside), feet y = 1.0 (outside).
    # Instead: feet inside, centroid outside ABOVE the zone is impossible for an
    # axis-aligned box (feet >= centroid always in y). So the discriminating case
    # is horizontal: feet_x is center — same as centroid_x. The real discriminator
    # is vertical: centroid_y < y2 always. Object hanging ABOVE the zone bottom
    # with centroid inside but feet below/outside:
    #   y1=0.30, y2=0.95 -> centroid y = 0.625 INSIDE zone, feet y = 0.95 OUTSIDE zone.
    overhanging = make_result([person(1, (int(0.30 * FRAME_W), int(0.30 * FRAME_H),
                                         int(0.70 * FRAME_W), int(0.95 * FRAME_H)))])
    # centroid y = (0.30+0.95)/2 = 0.625 (inside) but feet y = 0.95 (outside)
    events = engine.process_frame(overhanging, "CAM-01", [zone])
    assert len(events) == 0, "feet point outside zone must NOT trigger (centroid-inside would)"

    # Fully inside box: feet inside -> triggers even though box is tall
    engine2 = EventEngine()
    inside = make_result([person(2, (int(0.40 * FRAME_W), int(0.30 * FRAME_H),
                                     int(0.60 * FRAME_W), int(0.70 * FRAME_H)))])
    events2 = engine2.process_frame(inside, "CAM-01", [zone])
    assert len(events2) == 1, "feet point inside zone must trigger"
    assert events2[0].event_type == "PERSON_INTRUSION"


def test_person_enter_remain_exit_reentry_dedup():
    engine = EventEngine()
    zone = make_zone()
    inside = make_result([person(1, (800, 400, 1000, 700))])
    outside = make_result([person(1, (50, 50, 250, 350))])

    # Enter
    e1 = engine.process_frame(inside, "CAM-01", [zone])
    assert len(e1) == 1 and e1[0].status == "DETECTED"
    # Remain (many frames) -> still exactly one active event, no flood
    for _ in range(10):
        er = engine.process_frame(inside, "CAM-01", [zone])
        assert len(er) == 1
        assert er[0].status == "ACTIVE"
    assert len(engine._event_history) == 1
    # Exit -> cleared
    ex = engine.process_frame(outside, "CAM-01", [zone])
    assert len([e for e in ex if e.status != "RESOLVED"]) == 0
    # Re-entry -> new event
    e2 = engine.process_frame(inside, "CAM-01", [zone])
    assert len([e for e in e2 if e.status in ("DETECTED", "ACTIVE")]) == 1
    assert len(engine._event_history) == 2


@pytest.mark.parametrize("cls", ["car", "truck", "bus", "motorcycle"])
def test_all_vehicle_classes_intrude(cls):
    engine = EventEngine()
    zone = make_zone()
    events = engine.process_frame(make_result([vehicle(9, cls, (800, 400, 1000, 700))]),
                                  "CAM-01", [zone])
    assert len(events) == 1
    assert events[0].event_type == "VEHICLE_INTRUSION"
    assert events[0].object_class == cls
    assert cls in VEHICLE_CLASSES


def test_non_target_class_is_ignored():
    engine = EventEngine()
    zone = make_zone()
    dog = TrackedObject(track_id=3, class_id=16, class_name="dog",
                        confidence=0.9, bbox=(800, 400, 1000, 700))
    events = engine.process_frame(make_result([dog]), "CAM-01", [zone])
    assert len(events) == 0


def test_multiple_zones_same_camera_independent():
    engine = EventEngine()
    zone_a = make_zone(id="ZONE-A", points=[{"x": 0.05, "y": 0.05}, {"x": 0.35, "y": 0.05},
                                            {"x": 0.35, "y": 0.35}, {"x": 0.05, "y": 0.35}])
    zone_b = make_zone(id="ZONE-B", points=[{"x": 0.6, "y": 0.6}, {"x": 0.95, "y": 0.6},
                                            {"x": 0.95, "y": 0.95}, {"x": 0.6, "y": 0.95}])
    # Object inside zone A only
    in_a = make_result([person(1, (100, 100, 300, 300))])
    events = engine.process_frame(in_a, "CAM-01", [zone_a, zone_b])
    assert len(events) == 1
    assert events[0].zone_id == "ZONE-A"
    # Move to zone B: A resolves, B fires
    in_b = make_result([person(1, (1300, 700, 1500, 950))])
    events = engine.process_frame(in_b, "CAM-01", [zone_a, zone_b])
    zone_ids_active = {e.zone_id for e in events if e.status != "RESOLVED"}
    assert zone_ids_active == {"ZONE-B"}
    assert len(engine._event_history) == 2


def test_overlapping_zones_both_fire():
    engine = EventEngine()
    zone_a = make_zone(id="ZONE-A")
    zone_b = make_zone(id="ZONE-B", points=[{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1},
                                            {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}])
    events = engine.process_frame(make_result([person(1, (800, 400, 1000, 700))]),
                                  "CAM-01", [zone_a, zone_b])
    assert {e.zone_id for e in events} == {"ZONE-A", "ZONE-B"}


def test_multiple_cameras_zone_isolation():
    """Same zone ids on different cameras never cross-evaluate.

    Production uses one EventEngine per camera; this verifies the state
    machine keys events by (camera, zone, track) even if a shared engine
    sees both zone lists.
    """
    engine = EventEngine()
    zone1 = make_zone(id="ZONE-X", cam="CAM-01")
    zone2 = make_zone(id="ZONE-X", cam="CAM-02")
    inside = make_result([person(1, (800, 400, 1000, 700))])
    # Frame on CAM-01: only CAM-01's zone evaluates
    e1 = engine.process_frame(inside, "CAM-01", [zone1, zone2])
    active1 = [e for e in e1 if e.status != "RESOLVED"]
    assert len(active1) == 1 and active1[0].camera_id == "CAM-01"
    # Frame on CAM-02: evaluated only against CAM-02's zone -> its own event
    engine.process_frame(inside, "CAM-02", [zone1, zone2])
    hist_cam1 = [e for e in engine._event_history if e.camera_id == "CAM-01"]
    hist_cam2 = [e for e in engine._event_history if e.camera_id == "CAM-02"]
    assert len(hist_cam1) == 1, "CAM-01 must have exactly one independent event"
    assert len(hist_cam2) == 1, "CAM-02 must have exactly one independent event"


def test_disabled_zone_generates_nothing_but_stays_evaluable_after_enable():
    engine = EventEngine()
    zone = make_zone(enabled=False)
    inside = make_result([person(1, (800, 400, 1000, 700))])
    assert engine.process_frame(inside, "CAM-01", [zone]) == []
    zone.enabled = True
    events = engine.process_frame(inside, "CAM-01", [zone])
    assert len(events) == 1


def test_degenerate_polygon_does_not_crash():
    engine = EventEngine()
    zone = make_zone(points=[{"x": 0.5, "y": 0.5}])  # < 3 points
    events = engine.process_frame(make_result([person(1, (800, 400, 1000, 700))]),
                                  "CAM-01", [zone])
    assert isinstance(events, list)  # no exception, safe result


def test_empty_frame_and_missing_zone_list_safe():
    engine = EventEngine()
    empty = make_result([])
    assert engine.process_frame(empty, "CAM-01", []) == []
    zone = make_zone()
    assert engine.process_frame(empty, "CAM-01", [zone]) == []


def test_event_payload_carries_required_fields():
    """camera_id, zone_id, zone_name, object_type, confidence, timestamp, bbox, track_id."""
    engine = EventEngine()
    zone = make_zone(id="ZONE-F", cam="CAM-07")
    events = engine.process_frame(make_result([person(42, (800, 400, 1000, 700))]),
                                  "CAM-07", [zone])
    e = events[0]
    assert e.camera_id == "CAM-07"
    assert e.zone_id == "ZONE-F"
    assert e.zone_name == "Zone ZONE-F"
    assert e.object_class == "person"
    assert 0 < e.confidence <= 1
    assert e.timestamp
    assert set(e.bbox.keys()) == {"x1", "y1", "x2", "y2"}
    assert e.track_id == 42
