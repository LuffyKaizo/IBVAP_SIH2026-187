"""Incident report tests (spec PART 9): HTML rendering + JSON payload with
embedded evidence images and SHA-256 chain of custody."""
import asyncio
import sys

import pytest

sys.path.insert(0, ".")

from ai.reports import routes as report_routes


class _EventRepo:
    def __init__(self, event):
        self._event = event

    async def get(self, event_id):
        return self._event


class _AlertRepo:
    def __init__(self, alert):
        self._alert = alert

    async def get(self, alert_id):
        return self._alert


class _EvidenceRepo:
    def __init__(self, rows):
        self._rows = rows

    async def list_for_event(self, event_id):
        return list(self._rows)


class _Store:
    def __init__(self, data=b"\xff\xd8fakejpeg"):
        self._data = data

    def load(self, path):
        return self._data


def _event():
    return {
        "event_id": "evt-900",
        "event_type": "PERSON_INTRUSION",
        "severity": "CRITICAL",
        "camera_id": "CAM-05",
        "zone_id": "ZONE-A",
        "zone_name": "Gate 3 <Restricted>",
        "track_id": 7,
        "object_class": "person",
        "timestamp": "2026-09-27T10:00:00Z",
        "confidence": 0.87,
        "bbox": {"x1": 10, "y1": 20, "x2": 30, "y2": 40},
        "status": "ACTIVE",
    }


def _rows():
    return [
        {"id": "EVD-target", "eventId": "evt-900", "evidenceType": "TARGET_CROP",
         "timestamp": "2026-09-27T10:00:01Z", "fileSize": 2048,
         "mimeType": "image/jpeg", "filePath": "CAM-05/evt-900/EVD-target.jpg",
         "sha256Hash": "b" * 64, "integrityStatus": "VALID",
         "metadata": {"frame_width": 640, "frame_height": 480,
                      "crop_rect": [6, 14, 34, 46], "object_class": "person"}},
        {"id": "EVD-snap", "eventId": "evt-900", "evidenceType": "SNAPSHOT",
         "timestamp": "2026-09-27T10:00:00Z", "fileSize": 4096,
         "mimeType": "image/jpeg", "filePath": "CAM-05/evt-900/EVD-snap.jpg",
         "sha256Hash": "a" * 64, "integrityStatus": "VALID",
         "metadata": {"frame_width": 640, "frame_height": 480}},
    ]


def _setup():
    report_routes.init_report_routes(
        _EventRepo(_event()),
        _AlertRepo({"id": "ALT-AI-evt-900", "title": "Intrusion Zone Breach",
                    "severity": "CRITICAL", "zone": "Gate 3",
                    "reason": "Centroid crossed zone boundary",
                    "status": "ACTIVE", "trackId": "#7", "confidence": 87}),
        _EvidenceRepo(_rows()),
        _Store(),
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_json_payload_orders_artifacts_and_embeds_images():
    _setup()
    payload = _run(report_routes._build_payload("evt-900"))
    assert payload["eventId"] == "evt-900"
    assert [a["type"] for a in payload["artifacts"]] == ["SNAPSHOT", "TARGET_CROP"]
    assert payload["artifacts"][0]["sha256"] == "a" * 64
    assert payload["artifacts"][0]["dataUri"].startswith("data:image/jpeg;base64,")
    assert payload["incident"]["objectClass"] == "person"
    assert payload["incident"]["bbox"] == {"x1": 10, "y1": 20, "x2": 30, "y2": 40}
    assert payload["alert"]["title"] == "Intrusion Zone Breach"


def test_json_payload_missing_event_returns_none():
    report_routes.init_report_routes(
        _EventRepo(None), _AlertRepo(None), _EvidenceRepo([]), _Store())
    assert _run(report_routes._build_payload("nope")) is None


def test_html_report_contains_evidence_and_sha256():
    _setup()
    payload = _run(report_routes._build_payload("evt-900"))
    page = report_routes._render_html(payload)
    assert "IBVAP" in page
    assert "evt-900" in page
    assert "a" * 64 in page          # SNAPSHOT hash in chain of custody
    assert "b" * 64 in page          # TARGET_CROP hash
    assert "data:image/jpeg;base64," in page
    assert "Intrusion Zone Breach" in page
    # HTML-escaped zone name from the event
    assert "Gate 3 &lt;Restricted&gt;" in page
    assert "<Restricted>" not in page
    # All three section headers present
    assert "Incident Summary" in page
    assert "Evidence Artifacts (2)" in page
    assert "Chain of Custody" in page


def test_html_report_without_evidence_still_renders():
    report_routes.init_report_routes(
        _EventRepo(_event()), _AlertRepo(None), _EvidenceRepo([]), _Store())
    payload = _run(report_routes._build_payload("evt-900"))
    page = report_routes._render_html(payload)
    assert "No evidence artifacts recorded." in page
    assert "evt-900" in page


def test_html_report_escapes_alert_fields():
    _setup()
    report_routes.init_report_routes(
        _EventRepo(_event()),
        _AlertRepo({"id": "ALT-AI-evt-900", "title": "<script>xss</script>",
                    "reason": "&amp; boom", "status": "ACTIVE"}),
        _EvidenceRepo([]), _Store())
    payload = _run(report_routes._build_payload("evt-900"))
    page = report_routes._render_html(payload)
    assert "<script>xss</script>" not in page
    assert "&lt;script&gt;" in page
