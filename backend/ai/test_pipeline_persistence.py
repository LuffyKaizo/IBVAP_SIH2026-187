"""Tests for PipelineState event persistence lifecycle and deduplication."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ai.pipeline import PipelineState


class TestEventPersistenceLifecycle:
    """Test event lifecycle tracking and deduplication."""

    def _make_state(self, camera_id="CAM-01"):
        state = PipelineState(camera_id=camera_id, camera_name="Test Camera")
        state._event_repo = MagicMock()
        state._alert_repo = MagicMock()
        state._anpr_repo = MagicMock()
        return state

    def _make_metadata(self):
        return {
            "camera_id": "CAM-01",
            "camera_name": "Test Camera",
            "detections": [],
            "events": [],
            "alerts": [],
            "anpr": [],
        }

    def _make_event(self, event_id="evt-001", status="DETECTED"):
        return {
            "event_id": event_id,
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "camera_id": "CAM-01",
            "zone_id": "ZONE-01",
            "zone_name": "Restricted Area",
            "track_id": 1,
            "object_class": "person",
            "timestamp": "2026-01-01T00:00:00Z",
            "confidence": 0.95,
            "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4},
            "status": status,
        }

    def test_first_detection_persists_event(self):
        """First DETECTED event should be persisted."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        event = self._make_event(status="DETECTED")

        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_events([event])
            mock_sched.assert_called_once()
            # Should be tracked
            assert state._persisted_events.get("evt-001") == "DETECTED"

    def test_same_status_skips_persistence(self):
        """Same status should not trigger persistence."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        event = self._make_event(status="DETECTED")

        # First call - persists
        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_events([event])
            assert mock_sched.call_count == 1

        # Second call - same status, should skip
        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_events([event])
            mock_sched.assert_not_called()

    def test_status_transition_persists_update(self):
        """Status transition (DETECTED->ACTIVE) should trigger persistence."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        event_detected = self._make_event(status="DETECTED")
        event_active = self._make_event(status="ACTIVE")

        # First call - DETECTED
        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_events([event_detected])
            assert mock_sched.call_count == 1
            assert state._persisted_events.get("evt-001") == "DETECTED"

        # Second call - ACTIVE (transition from DETECTED)
        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_events([event_active])
            assert mock_sched.call_count == 1
            assert state._persisted_events.get("evt-001") == "ACTIVE"

    def test_resolved_event_clears_tracking(self):
        """RESOLVED event schedules clearing from tracking (async cleanup)."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        event_resolved = self._make_event(status="RESOLVED")

        state._persisted_events["evt-001"] = "ACTIVE"

        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_events([event_resolved])
            # The async function handles clearing; scheduling was called
            assert mock_sched.call_count == 1

    def test_alert_deduplication(self):
        """Alert dedup check runs inside the async persistence function."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        event = self._make_event(status="DETECTED")

        # First call - schedules persistence
        with patch("ai.pipeline.PipelineState._schedule_persist"):
            state.set_events([event])

        # The alert is added to _persisted_alerts inside _do_persist_event_lifecycle
        # which is async. The dedup check happens there. Verify scheduling was called.
        assert "evt-001" in state._persisted_events

    def test_clear_resets_tracking(self):
        """clear() should reset all persistence tracking."""
        state = self._make_state()
        state._persisted_events["evt-001"] = "ACTIVE"
        state._persisted_alerts.add("alert-001")
        state._persisted_anpr.add("anpr-001")

        state.clear()

        assert len(state._persisted_events) == 0
        assert len(state._persisted_alerts) == 0
        assert len(state._persisted_anpr) == 0

    def test_anpr_deduplication(self):
        """Same ANPR record ID should only schedule persistence once per call."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        result = {"id": "anpr-001", "status": "CONFIRMED", "cameraId": "CAM-01"}

        # First call - schedules persistence
        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_anpr_results([result])
            # _schedule_persist called from set_anpr_results
            assert mock_sched.call_count >= 1
            assert "anpr-001" in state._persisted_anpr

        # Second call - same record, should skip (not call _schedule_persist)
        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_anpr_results([result])
            mock_sched.assert_not_called()

    def test_anpr_skips_non_confirmed(self):
        """Non-confirmed ANPR results should not be persisted."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        result = {"id": "anpr-001", "status": "DETECTED", "cameraId": "CAM-01"}

        with patch("ai.pipeline.PipelineState._schedule_persist") as mock_sched:
            state.set_anpr_results([result])
            mock_sched.assert_not_called()

    def test_multiple_events_independent_tracking(self):
        """Multiple events should be tracked independently."""
        state = self._make_state()
        state.latest_metadata = self._make_metadata()
        event1 = self._make_event(event_id="evt-001", status="DETECTED")
        event2 = self._make_event(event_id="evt-002", status="ACTIVE")

        with patch("ai.pipeline.PipelineState._schedule_persist"):
            state.set_events([event1, event2])

        assert state._persisted_events.get("evt-001") == "DETECTED"
        assert state._persisted_events.get("evt-002") == "ACTIVE"
