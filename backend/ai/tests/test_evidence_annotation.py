"""Evidence annotation + full evidence-set tests (spec PART 6/7/8/11/12)."""
import asyncio
import sys

import numpy as np
import pytest

sys.path.insert(0, ".")

from ai.config import settings
from ai.evidence.annotate import annotate_full_frame, build_target_crop, event_label
from ai.pipeline import PipelineState


def _frame(w=640, h=480):
    return np.zeros((h, w, 3), dtype=np.uint8)


def make_event(**overrides):
    base = {
        "event_id": "evt-ann",
        "event_type": "PERSON_INTRUSION",
        "severity": "CRITICAL",
        "camera_id": "CAM-05",
        "zone_id": "ZONE-A",
        "zone_name": "Gate 3 Restricted Area",
        "track_id": 18,
        "object_class": "person",
        "timestamp": "2026-09-27T10:00:00Z",
        "confidence": 0.48,
        "bbox": {"x1": 100, "y1": 100, "x2": 300, "y2": 400},
        "status": "DETECTED",
    }
    base.update(overrides)
    return base


def _is_red(pixel):
    b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
    return r > 120 and b < 120 and g < 120


# ── labels (PART 7) ────────────────────────────────────────────────────

def test_event_label_mapping():
    assert event_label({"event_type": "PERSON_INTRUSION"}) == "INTRUSION"
    assert event_label({"event_type": "VEHICLE_INTRUSION"}) == "INTRUSION"
    assert event_label({"event_type": "LOITERING"}) == "LOITERING"
    assert event_label({"event_type": "NIGHT_MOVEMENT"}) == "NIGHT MOVEMENT"
    assert event_label({"event_type": "SUSPICIOUS_ACTIVITY"}) == "SUSPICIOUS ACTIVITY"
    assert event_label({"event_type": "WEIRD_NEW_TYPE"}) == "WEIRD NEW TYPE"


# ── annotated full frame (PART 7) ──────────────────────────────────────

def test_annotate_full_frame_returns_copy_not_mutating_original():
    frame = _frame()
    annotated = annotate_full_frame(frame, make_event())
    assert annotated is not None
    assert annotated.shape == frame.shape
    assert annotated is not frame
    # Original untouched (evidence integrity of the source frame)
    assert frame[100, 150].sum() == 0


def test_annotate_draws_box_on_exact_detection():
    frame = _frame()
    annotated = annotate_full_frame(frame, make_event())
    # Top edge of the detection box (y=100) is red
    assert _is_red(annotated[100, 150])
    # Left/right edges at x=100 / x=300
    assert _is_red(annotated[250, 100])
    assert _is_red(annotated[250, 300])
    # Outside the box stays black (no stray drawings)
    assert not _is_red(annotated[450, 600])


def test_annotate_full_frame_rejects_bad_inputs():
    assert annotate_full_frame(None, make_event()) is None
    assert annotate_full_frame(_frame(), make_event(bbox={})) is None
    assert annotate_full_frame(_frame(), make_event(
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.6})) is None  # normalized
    class FakeFrame:
        shape = (480, 640, 3)
    assert annotate_full_frame(FakeFrame(), make_event()) is None


def test_annotate_clamps_out_of_frame_box():
    annotated = annotate_full_frame(_frame(), make_event(
        bbox={"x1": -50, "y1": 60, "x2": 80, "y2": 900}))
    assert annotated is not None
    assert annotated.shape == (480, 640, 3)


def test_annotate_emphasizes_only_the_alerting_track():
    """TEST 5: one box for the alerting track — never every object."""
    frame = _frame()
    annotated = annotate_full_frame(frame, make_event())
    # A point far from the alerting box (where another object could be) is untouched.
    assert not _is_red(annotated[430, 550])
    assert not _is_red(annotated[50, 550])


# ── target focus crop (PART 4/5/8) ─────────────────────────────────────

def test_target_crop_contains_full_body_plus_margin():
    frame = _frame()
    crop, rect, diag = build_target_crop(frame, make_event(), margin=0.2)
    assert crop is not None
    # bbox 200x300 + 20% margin each side -> 280x420
    assert rect == (60, 40, 340, 460)
    assert crop.shape[:2] == (420, 280)
    assert diag["issues"] == []


def test_target_crop_draws_box_on_exact_detection_inside_crop():
    frame = _frame()
    crop, rect, _ = build_target_crop(frame, make_event(), margin=0.2)
    # Crop origin (60,40); detection left edge x=100 -> crop col 40, mid row 200
    assert _is_red(crop[200, 40])
    # Detection right edge x=300 -> crop col 240
    assert _is_red(crop[200, 240])
    # Margin context (crop col 5) is inside crop but outside the detection box
    assert not _is_red(crop[400, 5])


def test_target_crop_shows_context_margin_around_target():
    frame = np.full((480, 640, 3), 7, dtype=np.uint8)
    crop, rect, _ = build_target_crop(frame, make_event(), margin=0.2)
    # Crop is larger than the raw detection (200x300 -> 280x420)
    assert crop.shape[1] > 200
    assert crop.shape[0] > 300
    # Context pixels (frame value 7) survive at the crop edge
    assert int(crop[-1, -1][0]) in (7,) or _is_red(crop[-1, -1])


def test_target_crop_rejects_invalid_bbox_and_frame():
    assert build_target_crop(None, make_event(), 0.2)[0] is None
    assert build_target_crop(_frame(), make_event(bbox={}), 0.2)[0] is None
    assert build_target_crop(_frame(), make_event(
        bbox={"x1": 500, "y1": 100, "x2": 200, "y2": 400}), 0.2)[0] is None


def test_target_crop_never_exceeds_frame():
    crop, rect, _ = build_target_crop(
        _frame(), make_event(bbox={"x1": -100, "y1": -100, "x2": 620, "y2": 460}),
        margin=0.5)
    assert crop is not None
    assert crop.shape[0] <= 480
    assert crop.shape[1] <= 640


# ── alert carries authoritative source-frame target data (PART 2) ──────

def test_event_to_alert_includes_source_frame_target():
    event = make_event(frame_width=640, frame_height=480)
    alert = PipelineState._event_to_alert(event, "Gate Camera")
    assert alert["eventId"] == "evt-ann"
    assert alert["bbox"] == {"x1": 100, "y1": 100, "x2": 300, "y2": 400}
    assert alert["frameWidth"] == 640
    assert alert["frameHeight"] == 480
    assert alert["objectClass"] == "person"
    # Legacy fields intact
    assert alert["trackId"] == "#18"
    assert alert["confidence"] == 48


def test_set_events_attaches_frame_dims_and_bbox():
    state = PipelineState(camera_id="CAM-01")
    state.latest_metadata = {"frame_width": 1920, "frame_height": 1080,
                             "events": [], "alerts": []}
    state._evidence_capture = None
    state._event_repo = None
    state._alert_repo = None
    event = make_event()
    state.set_events([event])
    stored = state.latest_metadata["events"][0]
    assert stored["frame_width"] == 1920
    assert stored["frame_height"] == 1080
    alert = state.latest_metadata["alerts"][0]
    assert alert["bbox"] == event["bbox"]
    assert alert["frameWidth"] == 1920


# ── capture set wiring (PART 6) ────────────────────────────────────────

class _RecordingCapture:
    def __init__(self):
        self.calls = []

    async def capture_snapshot(self, event_dict, frame, actor="SYSTEM",
                               jpeg_quality=None, evidence_type="SNAPSHOT",
                               metadata_extra=None):
        self.calls.append({
            "type": evidence_type,
            "shape": getattr(frame, "shape", None),
            "meta": metadata_extra or {},
            "event": event_dict,
        })
        return {"id": "EVD-%d" % len(self.calls), "evidenceType": evidence_type,
                "metadata": metadata_extra or {}}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_capture_set_metadata_carries_frame_dims_and_crop_rect():
    state = PipelineState()
    cap = _RecordingCapture()
    state._evidence_capture = cap
    state._sync_manager = None
    _run(state._capture_and_enqueue_sync(make_event(), _frame()))
    types = [c["type"] for c in cap.calls]
    assert types == ["SNAPSHOT", "ANNOTATED", "TARGET_CROP"]
    for call in cap.calls:
        assert call["meta"]["frame_width"] == 640
        assert call["meta"]["frame_height"] == 480
        assert call["event"]["bbox"]["x1"] == 100  # source-frame bbox flows through
    target = cap.calls[2]
    assert target["meta"]["crop_rect"] == [60, 40, 340, 460]
    assert target["meta"]["is_target_crop"] is True
    assert cap.calls[1]["meta"]["is_annotated"] is True


def test_capture_set_vehicles_and_loitering_all_covered():
    state = PipelineState()
    cap = _RecordingCapture()
    state._evidence_capture = cap
    state._sync_manager = None
    for etype in ("VEHICLE_INTRUSION", "LOITERING", "NIGHT_MOVEMENT"):
        cap.calls.clear()
        _run(state._capture_and_enqueue_sync(
            make_event(event_type=etype, object_class="car"), _frame()))
        assert [c["type"] for c in cap.calls] == ["SNAPSHOT", "ANNOTATED", "TARGET_CROP"], etype
