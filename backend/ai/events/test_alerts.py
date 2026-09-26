"""Deterministic tests for AI event -> alert integration in the pipeline."""
import sys
sys.path.insert(0, ".")

from ai.pipeline import PipelineState


class FakeFrame:
    def __init__(self, w=1920, h=1080):
        self.shape = (h, w, 3)
    def copy(self):
        return self


class FakeTrackObj:
    def __init__(self, track_id, class_name, confidence, bbox):
        self.track_id = track_id
        self.class_id = 0
        self.class_name = class_name
        self.confidence = confidence
        self.bbox = bbox


class FakeTracking:
    def __init__(self, objects, active_tracks=1, total_time_ms=40.0, frame_index=1):
        self.tracked_objects = objects
        self.active_tracks = active_tracks
        self.total_time_ms = total_time_ms
        self.frame_index = frame_index


def make_event(**overrides):
    base = {
        "event_id": "abc12345",
        "event_type": "PERSON_INTRUSION",
        "severity": "CRITICAL",
        "camera_id": "CAM-01",
        "zone_id": "ZONE-01",
        "zone_name": "Restricted Border Area",
        "track_id": 12,
        "object_class": "person",
        "timestamp": "2026-09-04T12:00:00Z",
        "confidence": 0.91,
        "bbox": {"x1": 100, "y1": 200, "x2": 300, "y2": 500},
        "status": "DETECTED",
    }
    base.update(overrides)
    return base


passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  PASS:", name)
    else:
        failed += 1
        print("  FAIL:", name, detail)


# TEST 1: PERSON_INTRUSION -> CRITICAL alert
print("\n--- TEST 1: PERSON_INTRUSION -> CRITICAL alert ---")
alert = PipelineState._event_to_alert(make_event(), camera_name="BOP NORTH MAIN GATE")
check("alert ID starts with ALT-AI-", alert["id"].startswith("ALT-AI-"))
check("eventType is BORDER_INTRUSION", alert["eventType"] == "BORDER_INTRUSION")
check("severity is CRITICAL", alert["severity"] == "CRITICAL")
check("cameraId is CAM-01", alert["cameraId"] == "CAM-01")
check("cameraName is set", alert["cameraName"] == "BOP NORTH MAIN GATE")
check("trackId is #12", alert["trackId"] == "#12")
check("confidence is 91", alert["confidence"] == 91)
check("zone is Restricted Border Area", alert["zone"] == "Restricted Border Area")
check("title is set", len(alert["title"]) > 0)
check("reason is set", len(alert["reason"]) > 0)
check("evidenceChecklist has items", len(alert["evidenceChecklist"]) >= 2)
check("status is DETECTED", alert["status"] == "DETECTED")
check("source is AI", alert["source"] == "AI")

# TEST 2: VEHICLE_INTRUSION -> MEDIUM alert
print("\n--- TEST 2: VEHICLE_INTRUSION -> MEDIUM alert ---")
alert = PipelineState._event_to_alert(make_event(
    event_type="VEHICLE_INTRUSION", severity="MEDIUM", object_class="car", track_id=7))
check("eventType is RESTRICTED_ZONE_VEHICLE", alert["eventType"] == "RESTRICTED_ZONE_VEHICLE")
check("severity is MEDIUM", alert["severity"] == "MEDIUM")
check("trackId is #7", alert["trackId"] == "#7")

# TEST 3: LOITERING -> LOW alert
print("\n--- TEST 3: LOITERING -> LOW alert ---")
alert = PipelineState._event_to_alert(make_event(
    event_type="LOITERING", severity="LOW", track_id=3,
    reason="Low movement for 30+ seconds (disp: 0.012)"))
check("eventType is LOITERING", alert["eventType"] == "LOITERING")
check("severity is LOW", alert["severity"] == "LOW")
check("reason contains loitering info", "Low movement" in alert["reason"])
check("message is spec loitering text", alert["message"] == "Person #3 loitering near CAM-01.")

# TEST 4: NIGHT_MOVEMENT -> MEDIUM alert (HIGH normalized at the alert boundary)
print("\n--- TEST 4: NIGHT_MOVEMENT -> MEDIUM alert ---")
alert = PipelineState._event_to_alert(make_event(
    event_type="NIGHT_MOVEMENT", severity="HIGH", track_id=5,
    reason="Movement during night hours (23:00)"))
check("eventType is NIGHT_MOVEMENT", alert["eventType"] == "NIGHT_MOVEMENT")
check("severity is MEDIUM", alert["severity"] == "MEDIUM")

# TEST 5: SUSPICIOUS_ACTIVITY with reasons
print("\n--- TEST 5: SUSPICIOUS_ACTIVITY with reasons ---")
alert = PipelineState._event_to_alert(make_event(
    event_type="SUSPICIOUS_ACTIVITY", severity="CRITICAL", track_id=12,
    reasons=["NIGHT_MOVEMENT", "RESTRICTED_ZONE"]))
check("eventType is SUSPICIOUS_ACTIVITY", alert["eventType"] == "SUSPICIOUS_ACTIVITY")
check("severity is CRITICAL", alert["severity"] == "CRITICAL")
check("reason includes NIGHT_MOVEMENT", "NIGHT_MOVEMENT" in alert["reason"])
check("reason includes RESTRICTED_ZONE", "RESTRICTED_ZONE" in alert["reason"])
check("evidence includes rule triggers", any("Rule triggered" in e for e in alert["evidenceChecklist"]))

# TEST 6: set_events produces alerts
print("\n--- TEST 6: set_events produces alerts in metadata ---")
state = PipelineState()
frame = FakeFrame()
tracking = FakeTracking([FakeTrackObj(1, "person", 0.91, (100, 200, 300, 500))])
state.update(frame, tracking, "CAM-01")
check("metadata exists after update", state.latest_metadata is not None)
check("no alerts before set_events", "alerts" not in state.latest_metadata or len(state.latest_metadata.get("alerts", [])) == 0)
state.set_events([make_event()])
check("alerts field exists after set_events", "alerts" in state.latest_metadata)
check("alerts has 1 item", len(state.latest_metadata["alerts"]) == 1)
check("alert has source AI", state.latest_metadata["alerts"][0]["source"] == "AI")

# TEST 7: Unknown event type passes through
print("\n--- TEST 7: Unknown event type passes through ---")
alert = PipelineState._event_to_alert(make_event(event_type="UNKNOWN_TYPE"))
check("unknown type passes through", alert["eventType"] == "UNKNOWN_TYPE")

# TEST 8: Missing zone_name defaults to Default Zone
print("\n--- TEST 8: Missing zone_name ---")
alert = PipelineState._event_to_alert(make_event(zone_name=""))
check("empty zone_name defaults to Default Zone", alert["zone"] == "Default Zone")

# TEST 9: Camera name mapping
print("\n--- TEST 9: Camera name mapping ---")
alert = PipelineState._event_to_alert(make_event(camera_id="CAM-04"), camera_name="SECTOR WEST FENCE LINE")
check("CAM-04 maps to SECTOR WEST FENCE LINE", alert["cameraName"] == "SECTOR WEST FENCE LINE")

# TEST 10: Unknown camera falls back to camera_id
alert = PipelineState._event_to_alert(make_event(camera_id="CAM-99"), camera_name="")
check("unknown camera falls back to CAM-99", alert["cameraName"] == "CAM-99")

# TEST 11: clear() removes alerts
print("\n--- TEST 11: PipelineState.clear() removes alerts ---")
state.set_events([make_event()])
check("alerts exist before clear", len(state.latest_metadata.get("alerts", [])) > 0)
state.clear()
check("metadata is None after clear", state.latest_metadata is None)

# TEST 12: Multiple events produce multiple alerts
print("\n--- TEST 12: Multiple events -> multiple alerts ---")
state = PipelineState()
state.update(frame, tracking, "CAM-01")
events = [
    make_event(event_type="PERSON_INTRUSION", event_id="e1", track_id=1, confidence=0.9, status="ACTIVE"),
    make_event(event_type="VEHICLE_INTRUSION", event_id="e2", track_id=2, confidence=0.85, status="ACTIVE"),
]
state.set_events(events)
check("2 alerts from 2 events", len(state.latest_metadata["alerts"]) == 2)
types = {a["eventType"] for a in state.latest_metadata["alerts"]}
check("both types present", types == {"BORDER_INTRUSION", "RESTRICTED_ZONE_VEHICLE"})

# Summary
print("\n" + "=" * 50)
print("Results: %d passed, %d failed" % (passed, failed))
print("=" * 50)
if failed > 0:
    sys.exit(1)
