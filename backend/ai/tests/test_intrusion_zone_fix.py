"""Tests for intrusion zone fix: alert dedup, messages, target-crop evidence,
and removal of the implicit full-frame default zone."""
import asyncio
import sys

import numpy as np
import pytest

sys.path.insert(0, ".")

from ai.config import settings
from ai.main import _build_default_zones, _is_legacy_default_zone, _LEGACY_DEFAULT_ZONE_STRIP
from ai.pipeline import PipelineState


def make_event(**overrides):
    base = {
        "event_id": "evt-001",
        "event_type": "PERSON_INTRUSION",
        "severity": "CRITICAL",
        "camera_id": "CAM-05",
        "zone_id": "ZONE-A",
        "zone_name": "Gate 3 Restricted Area",
        "track_id": 2,
        "object_class": "person",
        "timestamp": "2026-09-26T10:00:00Z",
        "confidence": 0.8,
        "bbox": {"x1": 100, "y1": 200, "x2": 300, "y2": 500},
        "status": "DETECTED",
    }
    base.update(overrides)
    return base


# ── Default zones ──────────────────────────────────────────────────────

def test_build_default_zones_is_empty():
    """No camera ever gets an implicit full-frame zone (root-cause fix)."""
    for cam in ("CAM-01", "CAM-02", "CAM-99"):
        assert _build_default_zones(cam) == []


def test_legacy_default_zone_detection():
    legacy = {"points": [
        {"x": 0.10, "y": 0.20}, {"x": 0.90, "y": 0.20},
        {"x": 0.90, "y": 0.90}, {"x": 0.10, "y": 0.90},
    ], "name": "Restricted Border Area"}
    assert _is_legacy_default_zone(legacy) is True

    strip = {"points": [dict(p) for p in _LEGACY_DEFAULT_ZONE_STRIP],
             "name": "Restricted Border Area"}
    assert _is_legacy_default_zone(strip) is False

    operator = {"points": [{"x": 0.2, "y": 0.3}, {"x": 0.5, "y": 0.3},
                           {"x": 0.5, "y": 0.6}, {"x": 0.2, "y": 0.6}],
                "name": "Operator Zone"}
    assert _is_legacy_default_zone(operator) is False

    assert _is_legacy_default_zone({"points": [], "name": ""}) is False
    assert _is_legacy_default_zone({"points": [{"x": 0, "y": 0}]}) is False


# ── Alert title + message ─────────────────────────────────────────────

def test_intrusion_alert_title_and_message():
    alert = PipelineState._event_to_alert(make_event(), camera_name="SOUTH GATE")
    assert alert["title"] == "Intrusion Zone Breach"
    assert alert["message"] == (
        "Person #2 entered Intrusion Zone 'Gate 3 Restricted Area' on CAM-05."
    )


def test_vehicle_intrusion_alert_title_and_message():
    alert = PipelineState._event_to_alert(make_event(
        event_type="VEHICLE_INTRUSION", object_class="truck",
        track_id=7, zone_name="Runway Strip"))
    assert alert["title"] == "Intrusion Zone Breach"
    assert alert["message"] == (
        "Truck #7 entered Intrusion Zone 'Runway Strip' on CAM-05."
    )


def test_loitering_event_has_spec_message():
    """Spec §13: loitering alerts carry the exact operator-facing sentence."""
    alert = PipelineState._event_to_alert(make_event(event_type="LOITERING"))
    assert alert["message"] == "Person #2 loitering near CAM-05."
    assert alert["title"] == "Perimeter Loitering Detected"
    # Three-section model: loitering is always LOW regardless of input severity
    assert alert["severity"] == "LOW"


# ── Three-section severity model ──────────────────────────────────────

def test_three_section_severity_model():
    """Spec: person entry -> CRITICAL, vehicle entry -> MEDIUM, loitering ->
    LOW; HIGH never reaches an alert regardless of input severity."""
    person = PipelineState._event_to_alert(make_event())
    vehicle = PipelineState._event_to_alert(make_event(
        event_type="VEHICLE_INTRUSION", severity="HIGH", object_class="truck"))
    loiter = PipelineState._event_to_alert(
        make_event(event_type="LOITERING", severity="MEDIUM"))
    night = PipelineState._event_to_alert(
        make_event(event_type="NIGHT_MOVEMENT", severity="HIGH"))
    unknown = PipelineState._event_to_alert(
        make_event(event_type="CUSTOM_EVENT", severity="HIGH"))

    assert person["severity"] == "CRITICAL"
    assert vehicle["severity"] == "MEDIUM"
    assert loiter["severity"] == "LOW"
    assert night["severity"] == "MEDIUM"
    assert unknown["severity"] == "MEDIUM"
    for alert in (person, vehicle, loiter, night, unknown):
        assert alert["severity"] in ("CRITICAL", "MEDIUM", "LOW")


# ── Event-id keyed dedup ──────────────────────────────────────────────

def test_same_event_id_updates_not_creates():
    state = PipelineState()
    ev = make_event(status="DETECTED")
    alert = PipelineState._event_to_alert(ev)

    action, existing = state._should_create_or_escalate(ev, alert)
    assert action == "CREATE"
    state._record_alert(ev, alert)

    # ACTIVE frame of the same episode -> UPDATE
    ev2 = make_event(status="ACTIVE")
    action, existing = state._should_create_or_escalate(
        ev2, PipelineState._event_to_alert(ev2))
    assert action == "UPDATE"
    assert existing["id"] == alert["id"]

    # RESOLVED frame of the same episode -> UPDATE
    ev3 = make_event(status="RESOLVED")
    action, _ = state._should_create_or_escalate(
        ev3, PipelineState._event_to_alert(ev3))
    assert action == "UPDATE"


def test_reentry_with_new_event_id_creates_new_alert():
    """A fresh entry after leaving the zone must produce a new alert
    (old time-window dedup blocked this because first_seen never expired)."""
    state = PipelineState()
    first = make_event(event_id="entry-1")
    alert1 = PipelineState._event_to_alert(first)
    action, _ = state._should_create_or_escalate(first, alert1)
    assert action == "CREATE"
    state._record_alert(first, alert1)

    # Same track, same type, new episode -> CREATE again
    reentry = make_event(event_id="entry-2", status="DETECTED")
    action, _ = state._should_create_or_escalate(
        reentry, PipelineState._event_to_alert(reentry))
    assert action == "CREATE"


def test_different_zones_same_track_create_independent_alerts():
    state = PipelineState()
    zone_a = make_event(event_id="e-a", zone_id="ZONE-A", zone_name="Zone A")
    zone_b = make_event(event_id="e-b", zone_id="ZONE-B", zone_name="Zone B")
    for ev in (zone_a, zone_b):
        alert = PipelineState._event_to_alert(ev)
        action, _ = state._should_create_or_escalate(ev, alert)
        assert action == "CREATE"
        state._record_alert(ev, alert)


def test_escalation_still_works_within_event():
    """A severity rise within one episode still escalates the alert.

    Uses SUSPICIOUS_ACTIVITY because the spec pins intrusion/loitering/night
    severities to fixed values; suspicious activity keeps the risk-driven
    HIGH->CRITICAL progression that exercises the escalation path.
    """
    state = PipelineState()
    low = make_event(event_type="SUSPICIOUS_ACTIVITY", severity="HIGH")
    alert_low = PipelineState._event_to_alert(low)
    assert alert_low["severity"] == "MEDIUM"  # HIGH normalized to the 3-section model
    assert state._should_create_or_escalate(low, alert_low)[0] == "CREATE"
    state._record_alert(low, alert_low)

    high = make_event(event_type="SUSPICIOUS_ACTIVITY", severity="CRITICAL")
    action, existing = state._should_create_or_escalate(
        high, PipelineState._event_to_alert(high))
    assert action == "ESCALATE"
    assert existing["id"] == alert_low["id"]


def test_events_without_event_id_use_window_fallback():
    state = PipelineState()
    ev = make_event(event_id="")
    alert = PipelineState._event_to_alert(ev)
    assert state._should_create_or_escalate(ev, alert)[0] == "CREATE"
    state._record_alert(ev, alert)
    assert state._should_create_or_escalate(ev, alert)[0] == "UPDATE"


def test_alert_by_event_dict_is_bounded():
    state = PipelineState()
    for i in range(2100):
        ev = make_event(event_id="id-%d" % i)
        state._record_alert(ev, PipelineState._event_to_alert(ev))
    assert len(state._alert_by_event) <= 2000


def test_clear_resets_event_alert_map():
    state = PipelineState()
    ev = make_event()
    state._record_alert(ev, PipelineState._event_to_alert(ev))
    assert state._alert_by_event
    state.clear()
    assert not state._alert_by_event


# ── Target-crop evidence ──────────────────────────────────────────────

def _frame(w=640, h=480, value=40):
    return np.full((h, w, 3), value, dtype=np.uint8)


def _run_async(coro):
    """Run a coroutine without breaking global loop state for later tests
    (asyncio.run() closes and clears the current event loop, which makes
    subsequent tests fail with 'no current event loop')."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_target_crop_contains_red_box_and_is_smaller_than_frame():
    frame = _frame()
    crop = PipelineState._build_target_crop(frame, make_event())
    assert crop is not None
    fh, fw = frame.shape[:2]
    ch, cw = crop.shape[:2]
    assert ch < fh and cw < fw
    # Red pixels present (OpenCV arrays are BGR: channel 0 = B, channel 2 = R)
    r = crop[:, :, 2].astype(int)
    g = crop[:, :, 1].astype(int)
    b = crop[:, :, 0].astype(int)
    red_mask = (r > 150) & (b < 100) & (g < 100)
    assert red_mask.sum() > 50


def test_target_crop_margin_expands_bounds():
    frame = _frame()
    bbox = {"x1": 100, "y1": 100, "x2": 200, "y2": 200}
    crop = PipelineState._build_target_crop(frame, make_event(bbox=bbox))
    # 100px box + 20% margin each side = 140px (+/- rounding)
    assert 130 <= crop.shape[1] <= 150
    assert 130 <= crop.shape[0] <= 150


def test_target_crop_clamps_to_frame_edges():
    frame = _frame()
    bbox = {"x1": -50, "y1": -50, "x2": 80, "y2": 80}
    crop = PipelineState._build_target_crop(frame, make_event(bbox=bbox))
    assert crop is not None
    assert crop.shape[0] <= frame.shape[0]
    assert crop.shape[1] <= frame.shape[1]


def test_target_crop_invalid_inputs_return_none():
    frame = _frame()
    assert PipelineState._build_target_crop(None, make_event()) is None
    assert PipelineState._build_target_crop(frame, make_event(bbox={})) is None
    assert PipelineState._build_target_crop(
        frame, make_event(bbox={"x1": 300, "y1": 300, "x2": 100, "y2": 100})) is None
    assert PipelineState._build_target_crop(
        frame, make_event(bbox={"x1": 10, "y1": 10, "x2": 12, "y2": 12})) is None
    # Non-numpy frame (e.g. FakeFrame in other tests)
    class FakeFrame:
        shape = (480, 640, 3)
    assert PipelineState._build_target_crop(FakeFrame(), make_event()) is None


def test_target_crop_uses_configured_margin():
    assert 0.0 <= settings.EVIDENCE_TARGET_CROP_MARGIN <= 0.5


class _FakeEvidenceCapture:
    def __init__(self):
        self.calls = []

    async def capture_snapshot(self, event_dict, frame, actor="SYSTEM",
                               jpeg_quality=None, evidence_type="SNAPSHOT",
                               metadata_extra=None):
        self.calls.append((evidence_type, frame.shape if frame is not None else None))
        return {"id": "EVD-%d" % len(self.calls), "evidenceType": evidence_type}


def test_intrusion_capture_writes_snapshot_then_target_crop():
    state = PipelineState()
    capture = _FakeEvidenceCapture()
    state._evidence_capture = capture
    state._sync_manager = None
    frame = _frame()
    result = _run_async(state._capture_and_enqueue_sync(make_event(), frame))
    types = [c[0] for c in capture.calls]
    assert types == ["SNAPSHOT", "TARGET_CROP"]
    # SNAPSHOT is the full frame; TARGET_CROP is the smaller annotated crop
    assert capture.calls[0][1] == frame.shape
    assert capture.calls[1][1][0] < frame.shape[0]
    assert result["evidenceType"] == "TARGET_CROP"


def test_non_intrusion_event_captures_only_full_snapshot():
    state = PipelineState()
    capture = _FakeEvidenceCapture()
    state._evidence_capture = capture
    state._sync_manager = None
    _run_async(state._capture_and_enqueue_sync(
        make_event(event_type="LOITERING"), _frame()))
    assert [c[0] for c in capture.calls] == ["SNAPSHOT"]
