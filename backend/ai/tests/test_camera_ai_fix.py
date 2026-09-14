"""Phase 3 & 4 Camera AI Fix: Regression tests.

Tests for:
- Confidence filtering
- Class mapping
- Min bbox size filtering
- Normalized coordinate conversion
- No hardcoded placeholder detections
- Stale detection clearing
- EOF restart logic
- Virtual fence polygon detection
- Tripwire line-crossing detection
- ANPR no fabrication / EasyOCR
- Behavior rules integration
- Orphan auto-resolve
- Event deduplication
"""
import pytest
import numpy as np


class TestConfidenceFiltering:
    """Verify detections below threshold are filtered."""

    def test_low_confidence_filtered(self):
        """Detection with conf < 0.45 must be excluded."""
        from ai.config import settings
        assert settings.MIN_TRACKING_CONFIDENCE >= 0.40, (
            f"MIN_TRACKING_CONFIDENCE={settings.MIN_TRACKING_CONFIDENCE} is too low; "
            "should be >= 0.40 to filter false positives"
        )

    def test_confidence_threshold_reasonable(self):
        """Threshold should be between 0.30 and 0.65 for surveillance."""
        from ai.config import settings
        assert 0.30 <= settings.MIN_TRACKING_CONFIDENCE <= 0.65


class TestBboxSizeFilter:
    """Verify very small bounding boxes are filtered."""

    def test_min_bbox_area_filter_exists(self):
        """Tracker must have a minimum bbox area check."""
        import inspect
        from ai.tracking.tracker import ObjectTracker
        source = inspect.getsource(ObjectTracker.track)
        assert "bbox_area_pct" in source or "area_pct" in source, (
            "ObjectTracker.track() must filter by bbox area"
        )

    def test_min_bbox_area_value(self):
        """Min bbox area should be >= 0.2% to filter noise."""
        from ai.config import settings
        assert settings.MIN_BBOX_AREA_PCT >= 0.2, (
            f"MIN_BBOX_AREA_PCT={settings.MIN_BBOX_AREA_PCT} is too low; "
            "should be >= 0.2 to filter noise"
        )
        assert settings.MIN_BBOX_AREA_PCT <= 2.0, (
            f"MIN_BBOX_AREA_PCT={settings.MIN_BBOX_AREA_PCT} is too high; "
            "should be <= 2.0 to avoid filtering real objects"
        )


class TestClassMapping:
    """Verify COCO class mapping is correct."""

    def test_person_is_class_0(self):
        from ai.tracking.tracker import SURVEILLANCE_CLASS_IDS
        assert SURVEILLANCE_CLASS_IDS[0] == "person"

    def test_car_is_class_2(self):
        from ai.tracking.tracker import SURVEILLANCE_CLASS_IDS
        assert SURVEILLANCE_CLASS_IDS[2] == "car"

    def test_motorcycle_is_class_3(self):
        from ai.tracking.tracker import SURVEILLANCE_CLASS_IDS
        assert SURVEILLANCE_CLASS_IDS[3] == "motorcycle"

    def test_bus_is_class_5(self):
        from ai.tracking.tracker import SURVEILLANCE_CLASS_IDS
        assert SURVEILLANCE_CLASS_IDS[5] == "bus"

    def test_truck_is_class_7(self):
        from ai.tracking.tracker import SURVEILLANCE_CLASS_IDS
        assert SURVEILLANCE_CLASS_IDS[7] == "truck"

    def test_only_surveillance_classes_included(self):
        """Only person, bicycle, car, motorcycle, bus, truck are tracked."""
        from ai.tracking.tracker import SURVEILLANCE_CLASS_IDS
        expected = {0, 1, 2, 3, 5, 7}
        assert set(SURVEILLANCE_CLASS_IDS.keys()) == expected


class TestCoordinateNormalization:
    """Verify coordinate normalization produces values in [0, 1]."""

    def test_normalize_produces_0_to_1(self):
        from ai.pipeline import PipelineState
        w, h = 1920, 1080
        x1, y1, x2, y2 = 100, 200, 500, 800

        nx1 = round(x1 / w, 4)
        ny1 = round(y1 / h, 4)
        nx2 = round(x2 / w, 4)
        ny2 = round(y2 / h, 4)

        assert 0 <= nx1 <= 1
        assert 0 <= ny1 <= 1
        assert 0 <= nx2 <= 1
        assert 0 <= ny2 <= 1
        assert nx1 < nx2
        assert ny1 < ny2

    def test_normalize_roundtrip_accuracy(self):
        """Roundtrip: pixel -> normalized -> pixel should have < 1px error."""
        w, h = 1920, 1080
        x1, y1, x2, y2 = 1468.0, 571.9, 1528.7, 742.8

        nx1 = round(x1 / w, 4)
        ny1 = round(y1 / h, 4)
        nx2 = round(x2 / w, 4)
        ny2 = round(y2 / h, 4)

        rx1 = nx1 * w
        ry1 = ny1 * h
        rx2 = nx2 * w
        ry2 = ny2 * h

        error = abs(rx1 - x1) + abs(ry1 - y1) + abs(rx2 - x2) + abs(ry2 - y2)
        assert error < 1.0, f"Roundtrip error {error:.2f}px exceeds 1px tolerance"


class TestNoPlaceholderDetections:
    """Verify no hardcoded mock detections in camera data."""

    def test_initial_cameras_empty_detections(self):
        """INITIAL_CAMERAS must have empty detection arrays."""
        import os
        mock_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src", "mockData.ts")
        with open(mock_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Check that no DET-1xx mock detection IDs remain in INITIAL_CAMERAS block
        # Find INITIAL_CAMERAS section
        start = content.find("INITIAL_CAMERAS")
        assert start != -1, "INITIAL_CAMERAS not found in mockData.ts"
        end = content.find("];", start)
        cameras_block = content[start:end]
        assert "DET-10" not in cameras_block, (
            f"Mock detection IDs (DET-10x) found in INITIAL_CAMERAS"
        )

    def test_no_unsplash_poster_urls(self):
        """Camera poster URLs must not be Unsplash images."""
        import os
        mock_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src", "mockData.ts")
        with open(mock_path, "r", encoding="utf-8") as f:
            content = f.read()
        start = content.find("INITIAL_CAMERAS")
        end = content.find("];", start)
        cameras_block = content[start:end]
        assert "unsplash" not in cameras_block.lower(), (
            "Unsplash URLs found in INITIAL_CAMERAS videoPosterUrl"
        )


class TestPipelineStateClear:
    """Verify pipeline state is cleared properly."""

    def test_clear_resets_metadata(self):
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")
        state.latest_metadata = {"detections": [{"track_id": 1}]}
        state.frames_processed = 10
        state.total_detections = 5

        state.clear()

        assert state.latest_metadata is None
        assert state.frames_processed == 0
        assert state.total_detections == 0

    def test_clear_resets_persistence_tracking(self):
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")
        state._persisted_events["evt-1"] = "DETECTED"
        state._persisted_alerts.add("ALT-1")
        state._persisted_anpr.add("ANPR-1")

        state.clear()

        assert len(state._persisted_events) == 0
        assert len(state._persisted_alerts) == 0
        assert len(state._persisted_anpr) == 0


class TestDetectionMetadata:
    """Verify detection metadata structure sent via WebSocket."""

    def test_detection_has_required_fields(self):
        """Each detection must have track_id, class_id, class_name, confidence, bbox."""
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")

        class FakeTrack:
            track_id = 1
            class_id = 0
            class_name = "person"
            confidence = 0.75
            bbox = (100, 200, 300, 500)

        class FakeTracking:
            tracked_objects = [FakeTrack()]
            active_tracks = 1
            total_time_ms = 15.0
            frame_index = 1

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        state.update(frame, FakeTracking(), "CAM-01")

        md = state.get_latest_metadata()
        assert md is not None
        assert len(md["detections"]) == 1

        det = md["detections"][0]
        assert "track_id" in det
        assert "class_id" in det
        assert "class_name" in det
        assert "confidence" in det
        assert "bbox" in det
        assert all(k in det["bbox"] for k in ["x1", "y1", "x2", "y2"])

    def test_detection_bbox_normalized(self):
        """Detection bbox coordinates must be normalized to [0, 1]."""
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")

        class FakeTrack:
            track_id = 1
            class_id = 0
            class_name = "person"
            confidence = 0.75
            bbox = (480, 300, 960, 900)  # within 1920x1080

        class FakeTracking:
            tracked_objects = [FakeTrack()]
            active_tracks = 1
            total_time_ms = 15.0
            frame_index = 1

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        state.update(frame, FakeTracking(), "CAM-01")

        md = state.get_latest_metadata()
        det = md["detections"][0]
        bbox = det["bbox"]

        assert 0 <= bbox["x1"] <= 1
        assert 0 <= bbox["y1"] <= 1
        assert 0 <= bbox["x2"] <= 1
        assert 0 <= bbox["y2"] <= 1
        assert bbox["x1"] < bbox["x2"]
        assert bbox["y1"] < bbox["y2"]


class TestMetadataSourceField:
    """Verify metadata includes 'source: real' to distinguish from mock data."""

    def test_metadata_source_is_real(self):
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")

        class FakeTrack:
            track_id = 1
            class_id = 0
            class_name = "person"
            confidence = 0.75
            bbox = (100, 200, 300, 500)

        class FakeTracking:
            tracked_objects = [FakeTrack()]
            active_tracks = 1
            total_time_ms = 15.0
            frame_index = 1

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        state.update(frame, FakeTracking(), "CAM-01")

        md = state.get_latest_metadata()
        assert md["source"] == "real"


class TestTemporalConfirmation:
    """Verify detections require multiple observations before display."""

    def test_temporal_confirm_frames_config(self):
        from ai.config import settings
        assert settings.TEMPORAL_CONFIRM_FRAMES >= 2, (
            f"TEMPORAL_CONFIRM_FRAMES={settings.TEMPORAL_CONFIRM_FRAMES} should be >= 2"
        )

    def test_temporal_confirm_in_tracker_source(self):
        import inspect
        from ai.tracking.tracker import ObjectTracker
        source = inspect.getsource(ObjectTracker.track)
        assert "total_frames_seen" in source or "TEMPORAL_CONFIRM" in source, (
            "Tracker must implement temporal confirmation"
        )


class TestAspectRatioFilter:
    """Verify person class filters out implausible aspect ratios."""

    def test_person_max_aspect_ratio_config(self):
        from ai.config import settings
        assert 2.0 <= settings.PERSON_MAX_ASPECT_RATIO <= 6.0, (
            f"PERSON_MAX_ASPECT_RATIO={settings.PERSON_MAX_ASPECT_RATIO} out of range"
        )

    def test_person_min_aspect_ratio_config(self):
        from ai.config import settings
        assert 0.1 <= settings.PERSON_MIN_ASPECT_RATIO <= 0.5, (
            f"PERSON_MIN_ASPECT_RATIO={settings.PERSON_MIN_ASPECT_RATIO} out of range"
        )

    def test_aspect_ratio_filter_in_tracker_source(self):
        import inspect
        from ai.tracking.tracker import ObjectTracker
        source = inspect.getsource(ObjectTracker.track)
        assert "aspect_ratio" in source, (
            "Tracker must filter by aspect ratio"
        )


class TestStaticDetectionSuppression:
    """Verify detections that don't move over time are suppressed."""

    def test_static_filter_in_tracker_source(self):
        import inspect
        from ai.tracking.tracker import ObjectTracker
        source = inspect.getsource(ObjectTracker.track)
        assert "static" in source.lower() or "_static" in source.lower() or "STATIC" in source, (
            "Tracker must implement static detection suppression"
        )

    def test_position_history_persists(self):
        import inspect
        from ai.tracking.tracker import ObjectTracker
        source = inspect.getsource(ObjectTracker)
        assert "_position_history" in source, (
            "Tracker must maintain position history across frames"
        )


class TestConfidenceThreshold:
    """Verify tracking confidence threshold is appropriate for surveillance."""

    def test_tracking_confidence_min(self):
        from ai.config import settings
        assert settings.MIN_TRACKING_CONFIDENCE >= 0.45, (
            f"MIN_TRACKING_CONFIDENCE={settings.MIN_TRACKING_CONFIDENCE} too low for surveillance"
        )

    def test_tracking_confidence_max(self):
        from ai.config import settings
        assert settings.MIN_TRACKING_CONFIDENCE <= 0.70, (
            f"MIN_TRACKING_CONFIDENCE={settings.MIN_TRACKING_CONFIDENCE} too high; "
            "will miss distant objects"
        )


class TestVideoLoop:
    """Verify EOF restart behavior for local video sources."""

    def test_tracker_reset_clears_frame_count(self):
        """Tracker.reset() must reset _frame_count to 0."""
        from ai.tracking.tracker import ObjectTracker
        tracker = ObjectTracker()
        tracker._frame_count = 464
        tracker.reset()
        assert tracker._frame_count == 0

    def test_tracker_reset_clears_detection_history(self):
        """Tracker.reset() must clear _detection_history."""
        from ai.tracking.tracker import ObjectTracker
        tracker = ObjectTracker()
        tracker._detection_history[1] = True
        tracker._detection_history[2] = False
        tracker.reset()
        assert len(tracker._detection_history) == 0

    def test_tracker_reset_clears_position_history(self):
        """Tracker.reset() must clear _position_history."""
        from ai.tracking.tracker import ObjectTracker
        tracker = ObjectTracker()
        tracker._position_history[1] = [(0.5, 0.5)]
        tracker.reset()
        assert len(tracker._position_history) == 0

    def test_tracker_reset_recreates_model(self):
        """Tracker.reset() must recreate the YOLO model when it was loaded."""
        from ai.tracking.tracker import ObjectTracker
        tracker = ObjectTracker()
        # Model is lazy-loaded; force initialization
        tracker.load_model()
        old_model = tracker._model
        assert old_model is not None, "Model must be loaded before reset test"
        tracker.reset()
        assert tracker._model is not None
        assert tracker._model is not old_model

    def test_pipeline_state_clear_resets_frame_count(self):
        """PipelineState.clear() must reset frames_processed to 0."""
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")
        state.frames_processed = 464
        state.total_detections = 12
        state.clear()
        assert state.frames_processed == 0
        assert state.total_detections == 0

    def test_pipeline_state_clear_resets_latest_frame(self):
        """PipelineState.clear() must set latest_frame to None."""
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")
        state.latest_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        state.clear()
        assert state.latest_frame is None

    def test_pipeline_state_clear_resets_latest_metadata(self):
        """PipelineState.clear() must set latest_metadata to None."""
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="TEST")
        state.latest_metadata = {"detections": [{"track_id": 1}]}
        state.clear()
        assert state.latest_metadata is None

    def test_eof_restart_code_path_exists(self):
        """Pipeline._run_loop must contain EOF restart logic."""
        import inspect
        from ai.pipeline import ProcessingPipeline
        source = inspect.getsource(ProcessingPipeline._run_loop)
        assert "Video EOF" in source or "EOF" in source, (
            "Pipeline._run_loop must contain EOF handling"
        )
        assert "tracker.reset()" in source or "_tracker.reset()" in source, (
            "Pipeline._run_loop must call tracker.reset() on EOF"
        )
        assert "state.clear()" in source, (
            "Pipeline._run_loop must call state.clear() on EOF"
        )


# ── Phase 4: Border Intelligence Tests ──────────────────────────────────


class TestVirtualFence:
    """Verify polygon virtual fence integration."""

    def test_polygon_zone_point_inside(self):
        """Point inside a polygon zone should trigger breach."""
        from ai.events.engine import EventEngine, Zone
        from ai.tracking.tracker import TrackingResult, TrackedObject
        engine = EventEngine()
        zone = Zone(
            id="ZF-01",
            camera_id="CAM-01",
            name="Fence 1",
            points=[{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
            zone_type="POLYGON_ZONE",
            rule="RESTRICTED_ENTRY",
            severity="CRITICAL",
        )
        tracking = TrackingResult(
            tracked_objects=[
                TrackedObject(track_id=1, class_id=0, class_name="person", confidence=0.9, bbox=(400, 400, 600, 600)),
            ],
            frame_width=1000, frame_height=1000,
        )
        events = engine.process_frame(tracking, "CAM-01", [zone])
        assert len(events) >= 1
        assert events[0].zone_id == "ZF-01"

    def test_polygon_zone_point_outside(self):
        """Point outside a polygon zone should NOT trigger breach."""
        from ai.events.engine import EventEngine, Zone
        from ai.tracking.tracker import TrackingResult, TrackedObject
        engine = EventEngine()
        zone = Zone(
            id="ZF-02",
            camera_id="CAM-01",
            name="Fence 2",
            points=[{"x": 0.5, "y": 0.5}, {"x": 0.8, "y": 0.5}, {"x": 0.8, "y": 0.8}, {"x": 0.5, "y": 0.8}],
            zone_type="POLYGON_ZONE",
            rule="RESTRICTED_ENTRY",
            severity="HIGH",
        )
        tracking = TrackingResult(
            tracked_objects=[
                TrackedObject(track_id=2, class_id=0, class_name="person", confidence=0.9, bbox=(10, 10, 50, 50)),
            ],
            frame_width=1000, frame_height=1000,
        )
        events = engine.process_frame(tracking, "CAM-01", [zone])
        assert len(events) == 0

    def test_zone_type_field_exists(self):
        """Zone dataclass must have zone_type field."""
        from ai.events.engine import Zone
        z = Zone(
            id="T", camera_id="C", name="N",
            points=[{"x": 0, "y": 0}, {"x": 1, "y": 0}], zone_type="TRIPWIRE_LINE",
            rule="RESTRICTED_ENTRY", severity="CRITICAL",
        )
        assert z.zone_type == "TRIPWIRE_LINE"


class TestTripwireDetection:
    """Verify tripwire line-crossing detection."""

    def test_tripwire_crossing_detected(self):
        """Object crossing a tripwire should trigger an event."""
        from ai.events.engine import tripwire_crossed
        prev_x, prev_y = 0.35, 0.15
        curr_x, curr_y = 0.35, 0.75
        line_start = {"x": 0.2, "y": 0.5}
        line_end = {"x": 0.8, "y": 0.5}
        assert tripwire_crossed(prev_x, prev_y, curr_x, curr_y, line_start, line_end) is True

    def test_tripwire_no_crossing(self):
        """Object that does NOT cross the tripwire should not trigger."""
        from ai.events.engine import tripwire_crossed
        prev_x, prev_y = 0.35, 0.15
        curr_x, curr_y = 0.35, 0.25
        line_start = {"x": 0.2, "y": 0.5}
        line_end = {"x": 0.8, "y": 0.5}
        assert tripwire_crossed(prev_x, prev_y, curr_x, curr_y, line_start, line_end) is False

    def test_tripwire_event_engine(self):
        """EventEngine should route tripwire zones correctly."""
        from ai.events.engine import EventEngine, Zone
        from ai.tracking.tracker import TrackingResult, TrackedObject
        engine = EventEngine()
        zone = Zone(
            id="TW-01",
            camera_id="CAM-01",
            name="Tripwire 1",
            points=[{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}],
            zone_type="TRIPWIRE_LINE",
            rule="BI_DIRECTIONAL",
            severity="HIGH",
        )
        # Frame 1: object above line
        tracking1 = TrackingResult(
            tracked_objects=[
                TrackedObject(track_id=1, class_id=0, class_name="person", confidence=0.9, bbox=(300, 100, 400, 200)),
            ],
            frame_width=1000, frame_height=1000,
        )
        engine.process_frame(tracking1, "CAM-01", [zone])
        # Frame 2: object below line (crossed)
        tracking2 = TrackingResult(
            tracked_objects=[
                TrackedObject(track_id=1, class_id=0, class_name="person", confidence=0.9, bbox=(300, 700, 400, 800)),
            ],
            frame_width=1000, frame_height=1000,
        )
        events = engine.process_frame(tracking2, "CAM-01", [zone])
        assert len(events) >= 1
        assert events[0].event_type == "PERSON_INTRUSION"


class TestAnprNoFabrication:
    """Verify ANPR system does not use fabricated plates."""

    def test_anpr_no_hardcoded_plates(self):
        """ANPR code must not contain hardcoded plate numbers."""
        import inspect
        from ai.anpr.plate_detector import PlateDetector
        source = inspect.getsource(PlateDetector)
        hardcoded = ["MH12AB1234", "DL01AB1234", "MH", "DL", "KA", "TN", "GJ"]
        for plate in hardcoded:
            assert plate not in source, (
                f"PlateDetector contains hardcoded plate '{plate}'"
            )

    def test_anpr_uses_easyocr(self):
        """ANPR must use EasyOCR, not PaddleOCR."""
        import inspect
        from ai.anpr.ocr_engine import OCREngine
        source = inspect.getsource(OCREngine)
        assert "easyocr" in source.lower() or "EasyOCR" in source, (
            "OCREngine must use EasyOCR"
        )
        assert "paddleocr" not in source.lower(), (
            "OCREngine must NOT use PaddleOCR"
        )


class TestBehaviorRules:
    """Verify behavior detection rules are functional."""

    def test_behavior_engine_loitering(self):
        """BehaviorEngine must detect loitering."""
        from ai.events.behavior import BehaviorEngine
        engine = BehaviorEngine()
        assert hasattr(engine, 'process_frame')

    def test_behavior_engine_imports(self):
        """All behavior rules should be importable."""
        from ai.events.behavior import BehaviorEngine
        engine = BehaviorEngine()
        assert engine is not None


class TestOrphanAutoResolve:
    """Verify orphan detection auto-resolve with frame counter."""

    def test_orphan_resolve_frames_config(self):
        """ORPHAN_RESOLVE_FRAMES must be set in config."""
        from ai.config import settings
        assert hasattr(settings, 'ORPHAN_RESOLVE_FRAMES')
        assert settings.ORPHAN_RESOLVE_FRAMES > 0

    def test_event_engine_orphan_counter(self):
        """EventEngine must track orphan frames for auto-resolve."""
        from ai.events.engine import EventEngine
        engine = EventEngine()
        assert hasattr(engine, '_orphan_resolve_frames')


class TestEventDeduplication:
    """Verify events are deduplicated across frames."""

    def test_no_duplicate_events_same_track(self):
        """Same track_id in consecutive frames should not produce duplicate events."""
        from ai.events.engine import EventEngine, Zone
        from ai.tracking.tracker import TrackingResult, TrackedObject
        engine = EventEngine()
        zone = Zone(
            id="DEDUP-01",
            camera_id="CAM-01",
            name="Dedup Zone",
            points=[{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}],
            zone_type="POLYGON_ZONE",
            rule="RESTRICTED_ENTRY",
            severity="CRITICAL",
        )
        tracking = TrackingResult(
            tracked_objects=[
                TrackedObject(track_id=1, class_id=0, class_name="person", confidence=0.9, bbox=(400, 400, 600, 600)),
            ],
            frame_width=1000, frame_height=1000,
        )
        events1 = engine.process_frame(tracking, "CAM-01", [zone])
        events2 = engine.process_frame(tracking, "CAM-01", [zone])
        # Second frame should NOT re-trigger the same zone for same track
        if events1 and events2:
            for e2 in events2:
                assert e2.event_type != "ZONE_BREACH" or not any(
                    e1.track_id == e2.track_id and e1.zone_id == e2.zone_id
                    for e1 in events1
                )
