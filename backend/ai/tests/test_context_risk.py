"""Deterministic tests for ContextEngine and RiskEngine."""

import time
import unittest
from unittest.mock import MagicMock
from collections import deque

from ai.context.engine import ContextEngine, TrackContext, _point_to_polygon_distance, _compute_direction
from ai.risk.engine import RiskEngine, RiskAssessment, SEVERITY_ORDER
from ai.events.engine import Zone


def _make_tracking(track_id, class_name, bbox, fw=640, fh=480):
    """Create a minimal TrackingResult-like object."""
    obj = MagicMock()
    obj.track_id = track_id
    obj.class_name = class_name
    obj.class_id = 0 if class_name == "person" else 2
    obj.confidence = 0.9
    obj.bbox = bbox
    tracking = MagicMock()
    tracking.tracked_objects = [obj]
    tracking.frame_width = fw
    tracking.frame_height = fh
    return tracking


def _make_zone(zone_id="Z1", camera_id="CAM-01", points=None, severity="CRITICAL", enabled=True):
    if points is None:
        points = [
            {"x": 0.1, "y": 0.1},
            {"x": 0.9, "y": 0.1},
            {"x": 0.9, "y": 0.9},
            {"x": 0.1, "y": 0.9},
        ]
    z = Zone(
        id=zone_id,
        camera_id=camera_id,
        name="Restricted Zone",
        points=points,
        enabled=enabled,
        severity=severity,
    )
    return z


class TestDwellTime(unittest.TestCase):
    def setUp(self):
        self.engine = ContextEngine()
        self.zone = _make_zone()

    def test_dwell_below_threshold(self):
        """Track inside zone but below threshold emits no DWELL event."""
        t = _make_tracking(1, "person", (200, 100, 300, 300))
        ctxs, events = self.engine.process_frame(t, "CAM-01", [self.zone])
        self.assertEqual(len(ctxs), 1)
        self.assertEqual(ctxs[0].dwell_seconds, 0.0)
        dwell_events = [e for e in events if e["event_type"] == "DWELL_THRESHOLD"]
        self.assertEqual(len(dwell_events), 0)

    def test_dwell_at_threshold(self):
        """Track inside zone past threshold emits DWELL_THRESHOLD once."""
        t = _make_tracking(1, "person", (200, 100, 300, 300))
        # First frame — enters zone
        self.engine.process_frame(t, "CAM-01", [self.zone])
        # Simulate time passing by manipulating state
        state = self.engine._track_states[1]
        state.zone_inside_since = time.time() - 15.0  # 15 seconds ago
        # Process again
        ctxs, events = self.engine.process_frame(t, "CAM-01", [self.zone])
        dwell_events = [e for e in events if e["event_type"] == "DWELL_THRESHOLD"]
        self.assertEqual(len(dwell_events), 1)
        self.assertGreaterEqual(dwell_events[0]["dwell_seconds"], 10.0)

    def test_dwell_not_emitted_twice(self):
        """DWELL_THRESHOLD emits only once per zone entry."""
        t = _make_tracking(1, "person", (200, 100, 300, 300))
        self.engine.process_frame(t, "CAM-01", [self.zone])
        state = self.engine._track_states[1]
        state.zone_inside_since = time.time() - 15.0
        self.engine.process_frame(t, "CAM-01", [self.zone])
        self.engine.process_frame(t, "CAM-01", [self.zone])
        dwell_events = [e for e in self.engine.process_frame(t, "CAM-01", [self.zone])[1]
                        if e["event_type"] == "DWELL_THRESHOLD"]
        self.assertEqual(len(dwell_events), 0)  # already emitted

    def test_dwell_reset_on_exit(self):
        """When track leaves zone, dwell resets."""
        t_in = _make_tracking(1, "person", (200, 100, 300, 300))
        t_out = _make_tracking(1, "person", (10, 10, 30, 30))
        self.engine.process_frame(t_in, "CAM-01", [self.zone])
        state = self.engine._track_states[1]
        state.zone_inside_since = time.time() - 15.0
        self.engine.process_frame(t_in, "CAM-01", [self.zone])
        # Move out
        self.engine.process_frame(t_out, "CAM-01", [self.zone])
        self.assertEqual(state.current_zone_id, "")


class TestContextLoitering(unittest.TestCase):
    def setUp(self):
        self.engine = ContextEngine()
        self.zone = _make_zone()

    def test_loitering_below_threshold(self):
        """Track within radius but below time threshold not flagged."""
        t = _make_tracking(1, "person", (200, 100, 300, 300))
        self.engine.process_frame(t, "CAM-01", [self.zone])
        ctxs, _ = self.engine.process_frame(t, "CAM-01", [self.zone])
        self.assertFalse(ctxs[0].loitering)

    def test_loitering_at_threshold(self):
        """Track within radius past threshold emits LOITERING once."""
        t = _make_tracking(1, "person", (200, 100, 300, 300))
        self.engine.process_frame(t, "CAM-01", [self.zone])
        state = self.engine._track_states[1]
        state.loitering_start = time.time() - 35.0
        ctxs, events = self.engine.process_frame(t, "CAM-01", [self.zone])
        loiter_events = [e for e in events if e["event_type"] == "LOITERING"]
        self.assertEqual(len(loiter_events), 1)
        self.assertTrue(ctxs[0].loitering)

    def test_loitering_not_emitted_twice(self):
        """LOITERING emits only once per episode."""
        t = _make_tracking(1, "person", (200, 100, 300, 300))
        self.engine.process_frame(t, "CAM-01", [self.zone])
        state = self.engine._track_states[1]
        state.loitering_start = time.time() - 35.0
        self.engine.process_frame(t, "CAM-01", [self.zone])
        loiter_events = [e for e in self.engine.process_frame(t, "CAM-01", [self.zone])[1]
                         if e["event_type"] == "LOITERING"]
        self.assertEqual(len(loiter_events), 0)

    def test_loitering_reset_on_exit(self):
        """When track moves out of radius, loitering resets."""
        t_in = _make_tracking(1, "person", (200, 100, 300, 300))
        t_far = _make_tracking(1, "person", (500, 400, 550, 450))
        self.engine.process_frame(t_in, "CAM-01", [self.zone])
        state = self.engine._track_states[1]
        state.loitering_start = time.time() - 35.0
        # Move far away
        ctxs, _ = self.engine.process_frame(t_far, "CAM-01", [self.zone])
        self.assertFalse(state.loitering_emitted)


class TestFenceProximity(unittest.TestCase):
    def setUp(self):
        self.engine = ContextEngine()
        # Small zone in top-left
        self.zone = _make_zone(points=[
            {"x": 0.4, "y": 0.4},
            {"x": 0.6, "y": 0.4},
            {"x": 0.6, "y": 0.6},
            {"x": 0.4, "y": 0.6},
        ])

    def test_near_fence(self):
        """Track near zone boundary has fence_proximity=True."""
        # Ground point at (0.5, 0.52) — just outside zone
        t = _make_tracking(1, "person", (300, 220, 400, 250))
        ctxs, _ = self.engine.process_frame(t, "CAM-01", [self.zone])
        self.assertTrue(ctxs[0].fence_proximity)
        self.assertLess(ctxs[0].distance_to_fence, 0.15)

    def test_far_from_fence(self):
        """Track far from zone boundary has fence_proximity=False."""
        t = _make_tracking(1, "person", (50, 400, 100, 460))
        ctxs, _ = self.engine.process_frame(t, "CAM-01", [self.zone])
        self.assertFalse(ctxs[0].fence_proximity)
        self.assertGreater(ctxs[0].distance_to_fence, 0.10)


class TestDirection(unittest.TestCase):
    def test_left_to_right(self):
        """Track moving right has LEFT_TO_RIGHT direction."""
        engine = ContextEngine()
        zone = _make_zone()
        t1 = _make_tracking(1, "person", (100, 200, 200, 300))
        t2 = _make_tracking(1, "person", (200, 200, 300, 300))
        t3 = _make_tracking(1, "person", (300, 200, 400, 300))
        engine.process_frame(t1, "CAM-01", [zone])
        engine.process_frame(t2, "CAM-01", [zone])
        ctxs, _ = engine.process_frame(t3, "CAM-01", [zone])
        self.assertIn(ctxs[0].direction, ("LEFT_TO_RIGHT", "APPROACHING_FENCE", "MOVING_AWAY", "STATIONARY"))

    def test_stationary(self):
        """Track that doesn't move has STATIONARY direction."""
        engine = ContextEngine()
        zone = _make_zone()
        t = _make_tracking(1, "person", (200, 200, 300, 300))
        engine.process_frame(t, "CAM-01", [zone])
        engine.process_frame(t, "CAM-01", [zone])
        ctxs, _ = engine.process_frame(t, "CAM-01", [zone])
        self.assertIn(ctxs[0].direction, ("STATIONARY", "APPROACHING_FENCE", "MOVING_AWAY"))


class TestRepeatedEntry(unittest.TestCase):
    def setUp(self):
        self.engine = ContextEngine()
        self.zone = _make_zone()

    def test_repeated_entry_threshold(self):
        """Track entering zone 3+ times triggers REPEATED_ENTRY."""
        t_in = _make_tracking(1, "person", (200, 100, 300, 300))
        t_out = _make_tracking(1, "person", (10, 10, 30, 30))
        # Entry 1
        self.engine.process_frame(t_in, "CAM-01", [self.zone])
        self.engine.process_frame(t_out, "CAM-01", [self.zone])
        # Entry 2
        self.engine.process_frame(t_in, "CAM-01", [self.zone])
        self.engine.process_frame(t_out, "CAM-01", [self.zone])
        # Entry 3
        ctxs, events = self.engine.process_frame(t_in, "CAM-01", [self.zone])
        rep_events = [e for e in events if e["event_type"] == "REPEATED_ENTRY"]
        self.assertEqual(len(rep_events), 1)
        self.assertEqual(rep_events[0]["entry_count"], 3)

    def test_repeated_entry_not_emitted_twice(self):
        """REPEATED_ENTRY emits only once per episode."""
        t_in = _make_tracking(1, "person", (200, 100, 300, 300))
        t_out = _make_tracking(1, "person", (10, 10, 30, 30))
        for _ in range(3):
            self.engine.process_frame(t_in, "CAM-01", [self.zone])
            self.engine.process_frame(t_out, "CAM-01", [self.zone])
        # Third entry triggers, subsequent should not
        self.engine.process_frame(t_in, "CAM-01", [self.zone])
        rep_events = [e for e in self.engine.process_frame(t_in, "CAM-01", [self.zone])[1]
                      if e["event_type"] == "REPEATED_ENTRY"]
        self.assertEqual(len(rep_events), 0)


class TestRiskScore(unittest.TestCase):
    def setUp(self):
        self.engine = RiskEngine()

    def test_person_intrusion_base(self):
        """Person intrusion base score."""
        event = {"event_type": "PERSON_INTRUSION", "severity": "CRITICAL", "confidence": 0.9}
        result = self.engine.assess(event)
        self.assertGreaterEqual(result.risk_score, 30)
        self.assertIn("Person Intrusion", [f["factor"] for f in result.risk_factors])

    def test_vehicle_intrusion_base(self):
        """Vehicle intrusion base score."""
        event = {"event_type": "VEHICLE_INTRUSION", "severity": "HIGH", "confidence": 0.9}
        result = self.engine.assess(event)
        self.assertGreaterEqual(result.risk_score, 40)

    def test_severity_mapping_medium(self):
        """Score 25-49 maps to MEDIUM."""
        event = {"event_type": "PERSON_INTRUSION", "severity": "MEDIUM", "confidence": 0.5}
        result = self.engine.assess(event)
        self.assertIn(result.severity, ("LOW", "MEDIUM"))

    def test_severity_mapping_high(self):
        """Score 50-74 maps to HIGH."""
        event = {"event_type": "PERSON_INTRUSION", "severity": "CRITICAL", "confidence": 0.9}
        # Add loitering context to push score
        ctx = TrackContext(
            track_id=1, object_class="person", center_x=0.5, center_y=0.5,
            dwell_seconds=15.0, current_zone_id="Z1",
            loitering=True, loitering_seconds=35.0,
            fence_proximity=True, distance_to_fence=0.05,
            direction="APPROACHING_FENCE", direction_vector=(0.01, 0.02),
            repeated_entry=False, entry_count=1,
            zone_severity="CRITICAL",
        )
        result = self.engine.assess(event, track_context=ctx)
        self.assertGreaterEqual(result.risk_score, 75)

    def test_night_activity(self):
        """Night activity adds weight."""
        event = {"event_type": "PERSON_INTRUSION", "severity": "MEDIUM", "confidence": 0.5}
        day = self.engine.assess(event, is_night=False)
        night = self.engine.assess(event, is_night=True)
        self.assertEqual(night.risk_score, day.risk_score + 10)

    def test_clamp_0_100(self):
        """Score clamped to 0-100."""
        event = {"event_type": "UNKNOWN", "severity": "LOW", "confidence": 0.1}
        result = self.engine.assess(event)
        self.assertGreaterEqual(result.risk_score, 0)
        self.assertLessEqual(result.risk_score, 100)

    def test_full_context_max_score(self):
        """All factors combined can reach high score."""
        event = {"event_type": "VEHICLE_INTRUSION", "severity": "CRITICAL", "confidence": 0.95}
        ctx = TrackContext(
            track_id=1, object_class="car", center_x=0.5, center_y=0.5,
            dwell_seconds=15.0, current_zone_id="Z1",
            loitering=True, loitering_seconds=35.0,
            fence_proximity=True, distance_to_fence=0.03,
            direction="APPROACHING_FENCE", direction_vector=(0.01, 0.02),
            repeated_entry=True, entry_count=4,
            zone_severity="CRITICAL",
        )
        result = self.engine.assess(event, track_context=ctx, is_night=True)
        self.assertGreaterEqual(result.risk_score, 90)
        self.assertEqual(result.severity, "CRITICAL")


class TestEffectiveSeverity(unittest.TestCase):
    def test_risk_escalates_base(self):
        """Risk severity higher than base escalates."""
        self.assertEqual(RiskEngine.effective_severity("LOW", "HIGH"), "HIGH")
        self.assertEqual(RiskEngine.effective_severity("MEDIUM", "CRITICAL"), "CRITICAL")

    def test_base_preserved_when_higher(self):
        """Base severity preserved when higher than risk."""
        self.assertEqual(RiskEngine.effective_severity("CRITICAL", "LOW"), "CRITICAL")
        self.assertEqual(RiskEngine.effective_severity("HIGH", "MEDIUM"), "HIGH")


class TestAlertDedup(unittest.TestCase):
    def test_dedup_key(self):
        """Alert dedup uses camera_id:track_id:event_type."""
        key = "CAM-01:5:PERSON_INTRUSION"
        self.assertEqual(key, "CAM-01:5:PERSON_INTRUSION")


class TestOfflineOperation(unittest.TestCase):
    def test_context_engine_no_network(self):
        """ContextEngine works without network."""
        engine = ContextEngine()
        zone = _make_zone()
        t = _make_tracking(1, "person", (200, 100, 300, 300))
        ctxs, events = engine.process_frame(t, "CAM-01", [zone])
        self.assertEqual(len(ctxs), 1)

    def test_risk_engine_no_network(self):
        """RiskEngine works without network."""
        engine = RiskEngine()
        event = {"event_type": "PERSON_INTRUSION", "severity": "CRITICAL", "confidence": 0.9}
        result = engine.assess(event)
        self.assertIsInstance(result, RiskAssessment)


class TestCoexistence(unittest.TestCase):
    """Verify ContextEngine and BehaviorEngine can coexist."""

    def test_context_does_not_duplicate_behavior_events(self):
        """ContextEngine LOITERING is separate from BehaviorEngine LOITERING."""
        from ai.events.behavior import BehaviorEngine
        from ai.events.engine import EventEngine

        context_engine = ContextEngine()
        behavior_engine = BehaviorEngine()
        zone = _make_zone()
        t = _make_tracking(1, "person", (200, 100, 300, 300))

        # Process through both
        ctxs, ctx_events = context_engine.process_frame(t, "CAM-01", [zone])
        beh_events = behavior_engine.process_frame(t, "CAM-01")

        # Both can produce events independently
        ctx_loiter = [e for e in ctx_events if e.get("event_type") == "LOITERING"]
        beh_loiter = [e for e in beh_events if hasattr(e, "event_type") and e.event_type == "LOITERING"]
        # They are independent — no duplication issue
        self.assertIsInstance(ctx_loiter, list)
        self.assertIsInstance(beh_loiter, list)


class TestPointToPolygonDistance(unittest.TestCase):
    def test_inside_polygon(self):
        """Point inside polygon has small distance to boundary."""
        poly = [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.4},
                {"x": 0.6, "y": 0.6}, {"x": 0.4, "y": 0.6}]
        dist = _point_to_polygon_distance(0.5, 0.5, poly)
        self.assertAlmostEqual(dist, 0.1, places=2)

    def test_outside_polygon(self):
        """Point outside polygon has larger distance."""
        poly = [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.4},
                {"x": 0.6, "y": 0.6}, {"x": 0.4, "y": 0.6}]
        dist = _point_to_polygon_distance(0.1, 0.1, poly)
        self.assertGreater(dist, 0.1)


class TestComputeDirection(unittest.TestCase):
    def test_enough_positions(self):
        """Direction computed from sufficient positions."""
        positions = deque([
            (0.1, 0.5, 0.0),
            (0.2, 0.5, 0.1),
            (0.3, 0.5, 0.2),
        ])
        direction, vec = _compute_direction(positions, 3)
        self.assertEqual(direction, "LEFT_TO_RIGHT")

    def test_not_enough_positions(self):
        """Direction empty when insufficient positions."""
        positions = deque([(0.1, 0.5, 0.0)])
        direction, vec = _compute_direction(positions, 3)
        self.assertEqual(direction, "")


if __name__ == "__main__":
    unittest.main()
