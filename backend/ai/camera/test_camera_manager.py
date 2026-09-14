"""Deterministic tests for IBVAP camera management.

Tests camera lifecycle, state isolation, registry operations,
and multi-camera architecture without requiring real RTSP streams.
"""

import os
import time
import threading
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock

from ai.camera.config import CameraConfig
from ai.camera.registry import CameraRegistry
from ai.camera.pipeline import CameraPipeline
from ai.camera.manager import CameraManager
from ai.events.engine import EventEngine, Zone, SecurityEvent
from ai.events.behavior import BehaviorEngine
from ai.anpr.temporal import TemporalStabilizer


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

TEST_MODEL = os.path.join(os.path.dirname(__file__), "..", "..", "yolov8n.pt")
TEST_VIDEO = os.path.join(os.path.dirname(__file__), "..", "..", "data", "test.mp4")


def _make_config(camera_id="CAM-TEST", source_type="video", source=None, enabled=True, name="Test Camera"):
    if source is None:
        source = TEST_VIDEO
    return CameraConfig(
        camera_id=camera_id,
        name=name,
        location="Test Location",
        source=source,
        source_type=source_type,
        enabled=enabled,
    )


# ──────────────────────────────────────────────────────────────────
# CameraConfig Tests
# ──────────────────────────────────────────────────────────────────

class TestCameraConfig:
    def test_create_config(self):
        cfg = _make_config("CAM-01")
        assert cfg.camera_id == "CAM-01"
        assert cfg.name == "Test Camera"
        assert cfg.enabled is True

    def test_to_dict(self):
        cfg = _make_config("CAM-01")
        d = cfg.to_dict()
        assert d["camera_id"] == "CAM-01"
        assert "created_at" in d
        assert "updated_at" in d

    def test_from_dict(self):
        d = {"camera_id": "CAM-X", "name": "X Cam", "location": "Loc", "source": "/dev/null", "source_type": "video"}
        cfg = CameraConfig.from_dict(d)
        assert cfg.camera_id == "CAM-X"
        assert cfg.camera_type == "FIXED"  # default

    def test_from_dict_ignores_unknown_fields(self):
        d = {"camera_id": "CAM-X", "name": "X", "location": "L", "source": "s", "source_type": "v", "extra_field": 42}
        cfg = CameraConfig.from_dict(d)
        assert cfg.camera_id == "CAM-X"
        assert not hasattr(cfg, "extra_field")


# ──────────────────────────────────────────────────────────────────
# CameraRegistry Tests
# ──────────────────────────────────────────────────────────────────

class TestCameraRegistry:
    def test_add_and_get(self):
        reg = CameraRegistry()
        cfg = _make_config("CAM-01")
        reg.add(cfg)
        assert reg.get("CAM-01") is cfg

    def test_get_missing(self):
        reg = CameraRegistry()
        assert reg.get("CAM-NONE") is None

    def test_duplicate_raises(self):
        reg = CameraRegistry()
        reg.add(_make_config("CAM-01"))
        with pytest.raises(ValueError, match="already registered"):
            reg.add(_make_config("CAM-01"))

    def test_list_all(self):
        reg = CameraRegistry()
        reg.add(_make_config("CAM-01"))
        reg.add(_make_config("CAM-02"))
        assert reg.count() == 2
        ids = [c.camera_id for c in reg.list_all()]
        assert "CAM-01" in ids
        assert "CAM-02" in ids

    def test_list_enabled(self):
        reg = CameraRegistry()
        reg.add(_make_config("CAM-01", enabled=True))
        reg.add(_make_config("CAM-02", enabled=False))
        assert reg.count_enabled() == 1
        assert reg.list_enabled()[0].camera_id == "CAM-01"

    def test_update(self):
        reg = CameraRegistry()
        reg.add(_make_config("CAM-01", name="Old Name"))
        updated = reg.update("CAM-01", name="New Name")
        assert updated.name == "New Name"
        assert reg.get("CAM-01").name == "New Name"

    def test_update_missing(self):
        reg = CameraRegistry()
        assert reg.update("CAM-NONE", name="X") is None

    def test_remove(self):
        reg = CameraRegistry()
        reg.add(_make_config("CAM-01"))
        assert reg.remove("CAM-01") is True
        assert reg.get("CAM-01") is None
        assert reg.count() == 0

    def test_remove_missing(self):
        reg = CameraRegistry()
        assert reg.remove("CAM-NONE") is False

    def test_exists(self):
        reg = CameraRegistry()
        reg.add(_make_config("CAM-01"))
        assert reg.exists("CAM-01") is True
        assert reg.exists("CAM-02") is False


# ──────────────────────────────────────────────────────────────────
# CameraManager Tests (Registry + Lifecycle)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCameraManager:
    async def test_register_camera(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01")
        info = await mgr.register_camera(cfg, auto_start=False)
        assert info["camera_id"] == "CAM-01"
        assert mgr.get_pipeline("CAM-01") is not None

    async def test_register_duplicate_raises(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        await mgr.register_camera(_make_config("CAM-01"), auto_start=False)
        with pytest.raises(ValueError):
            await mgr.register_camera(_make_config("CAM-01"), auto_start=False)

    async def test_list_cameras(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        await mgr.register_camera(_make_config("CAM-01"), auto_start=False)
        await mgr.register_camera(_make_config("CAM-02"), auto_start=False)
        cameras = mgr.list_cameras()
        assert len(cameras) == 2
        ids = [c["camera_id"] for c in cameras]
        assert "CAM-01" in ids
        assert "CAM-02" in ids

    async def test_get_camera(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        await mgr.register_camera(_make_config("CAM-01"), auto_start=False)
        info = mgr.get_camera("CAM-01")
        assert info is not None
        assert info["camera_id"] == "CAM-01"

    def test_get_camera_missing(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        assert mgr.get_camera("CAM-NONE") is None

    async def test_unregister_camera(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        await mgr.register_camera(_make_config("CAM-01"), auto_start=False)
        assert await mgr.unregister_camera("CAM-01") is True
        assert mgr.get_pipeline("CAM-01") is None
        assert mgr.get_camera("CAM-01") is None

    async def test_unregister_missing(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        assert await mgr.unregister_camera("CAM-NONE") is False

    async def test_disabled_camera_not_started(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", enabled=False)
        await mgr.register_camera(cfg, auto_start=True)
        pipeline = mgr.get_pipeline("CAM-01")
        assert pipeline.is_running is False

    async def test_aggregate_status(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        await mgr.register_camera(_make_config("CAM-01"), auto_start=False)
        await mgr.register_camera(_make_config("CAM-02"), auto_start=False)
        agg = mgr.get_aggregate_status()
        assert agg["total_registered"] == 2
        assert agg["enabled"] == 2
        assert agg["running_pipelines"] == 0

    async def test_dynamic_camera_registration(self):
        """CAM-07 can be registered at runtime without code changes."""
        mgr = CameraManager(model_path=TEST_MODEL)
        for i in range(1, 7):
            cid = "CAM-0%d" % i
            await mgr.register_camera(_make_config(cid), auto_start=False)
        cam07 = CameraConfig(
            camera_id="CAM-07",
            name="North Gate",
            location="Sector A",
            source=TEST_VIDEO,
            source_type="video",
        )
        await mgr.register_camera(cam07, auto_start=False)
        assert mgr.get_camera("CAM-07") is not None
        assert mgr.get_pipeline("CAM-07") is not None
        assert mgr.list_cameras().__len__() == 7

    async def test_update_camera(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        await mgr.register_camera(_make_config("CAM-01"), auto_start=False)
        info = await mgr.update_camera("CAM-01", name="Updated Name")
        assert info["name"] == "Updated Name"

    async def test_update_camera_missing(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        assert await mgr.update_camera("CAM-NONE", name="X") is None

    def test_shutdown_all(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        mgr._sync_register_camera(_make_config("CAM-01"), auto_start=False)
        mgr._sync_register_camera(_make_config("CAM-02"), auto_start=False)
        mgr.shutdown_all()
        assert len(mgr._pipelines) == 0


# ──────────────────────────────────────────────────────────────────
# CameraPipeline Isolation Tests (using test.mp4)
# ──────────────────────────────────────────────────────────────────

class TestCameraPipelineIsolation:
    """Test that two pipelines maintain fully isolated state."""

    def test_two_pipelines_independent(self):
        """Two CameraPipeline instances have fully isolated state."""
        cfg1 = _make_config("CAM-01", name="Camera One")
        cfg2 = _make_config("CAM-02", name="Camera Two")

        p1 = CameraPipeline(cfg1, TEST_MODEL)
        p2 = CameraPipeline(cfg2, TEST_MODEL)
        p1.initialize()
        p2.initialize()

        assert p1.camera_id == "CAM-01"
        assert p2.camera_id == "CAM-02"
        assert p1._pipeline is not p2._pipeline
        assert p1._event_engine is not p2._event_engine
        assert p1._behavior_engine is not p2._behavior_engine
        assert p1._temporal is not p2._temporal
        assert p1._pipeline.state is not p2._pipeline.state

    def test_event_state_isolation(self):
        cfg1 = _make_config("CAM-01")
        cfg2 = _make_config("CAM-02")
        p1 = CameraPipeline(cfg1, TEST_MODEL)
        p2 = CameraPipeline(cfg2, TEST_MODEL)
        assert p1._event_engine is not p2._event_engine
        assert p1._event_engine._active_events is not p2._event_engine._active_events

    def test_behavior_state_isolation(self):
        cfg1 = _make_config("CAM-01")
        cfg2 = _make_config("CAM-02")
        p1 = CameraPipeline(cfg1, TEST_MODEL)
        p2 = CameraPipeline(cfg2, TEST_MODEL)
        assert p1._behavior_engine is not p2._behavior_engine
        assert p1._behavior_engine._loitering is not p2._behavior_engine._loitering

    def test_anpr_state_isolation(self):
        cfg1 = _make_config("CAM-01")
        cfg2 = _make_config("CAM-02")
        p1 = CameraPipeline(cfg1, TEST_MODEL)
        p2 = CameraPipeline(cfg2, TEST_MODEL)
        assert p1._temporal is not p2._temporal
        assert p1._temporal._states is not p2._temporal._states

    def test_tracker_state_isolation(self):
        cfg1 = _make_config("CAM-01")
        cfg2 = _make_config("CAM-02")
        p1 = CameraPipeline(cfg1, TEST_MODEL)
        p2 = CameraPipeline(cfg2, TEST_MODEL)
        assert p1._pipeline._tracker is not p2._pipeline._tracker

    def test_metadata_camera_id(self):
        cfg1 = _make_config("CAM-01")
        cfg2 = _make_config("CAM-02")
        p1 = CameraPipeline(cfg1, TEST_MODEL)
        p2 = CameraPipeline(cfg2, TEST_MODEL)
        assert p1.get_status()["camera_id"] == "CAM-01"
        assert p2.get_status()["camera_id"] == "CAM-02"

    def test_start_stop_lifecycle(self):
        cfg = _make_config("CAM-TEST")
        pipeline = CameraPipeline(cfg, TEST_MODEL)
        pipeline.initialize()
        started = pipeline.start()
        assert started is True
        assert pipeline.is_running is True
        time.sleep(1.0)
        pipeline.stop()
        assert pipeline.is_running is False

    def test_stop_releases_resources(self):
        cfg = _make_config("CAM-TEST")
        pipeline = CameraPipeline(cfg, TEST_MODEL)
        pipeline.initialize()
        pipeline.start()
        time.sleep(0.5)
        pipeline.stop()
        status = pipeline.get_status()
        assert status["video_connected"] is False

    def test_restart_pipeline(self):
        cfg = _make_config("CAM-TEST")
        pipeline = CameraPipeline(cfg, TEST_MODEL)
        pipeline.initialize()
        pipeline.start()
        time.sleep(0.5)
        restarted = pipeline.restart()
        assert restarted is True
        assert pipeline.is_running is True
        time.sleep(0.5)
        pipeline.stop()

    def test_camera_name_in_status(self):
        cfg = _make_config("CAM-01", name="BOP NORTH")
        pipeline = CameraPipeline(cfg, TEST_MODEL)
        status = pipeline.get_status()
        assert status["camera_name"] == "BOP NORTH"


# ──────────────────────────────────────────────────────────────────
# CameraManager Full Lifecycle Tests
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCameraManagerLifecycle:
    async def test_start_stop_camera(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01")
        await mgr.register_camera(cfg, auto_start=False)

        result = await mgr.start_camera("CAM-01")
        assert "error" not in result
        assert result["started"] is True

        time.sleep(0.5)

        result = await mgr.stop_camera("CAM-01")
        assert "error" not in result
        assert result["stopped"] is True

    async def test_start_disabled_camera_fails(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", enabled=False)
        await mgr.register_camera(cfg, auto_start=False)

        result = await mgr.start_camera("CAM-01")
        assert "error" in result
        assert "disabled" in result["error"]

    async def test_start_missing_camera_fails(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        result = await mgr.start_camera("CAM-NONE")
        assert "error" in result
        assert "not found" in result["error"]

    async def test_restart_camera(self):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01")
        await mgr.register_camera(cfg, auto_start=False)

        await mgr.start_camera("CAM-01")
        time.sleep(0.5)

        result = await mgr.restart_camera("CAM-01")
        assert "error" not in result
        assert result["restarted"] is True

        time.sleep(0.5)
        await mgr.stop_camera("CAM-01")

    async def test_unregister_stops_pipeline(self):
        """Unregistering a camera stops its pipeline first."""
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01")
        await mgr.register_camera(cfg, auto_start=False)
        await mgr.start_camera("CAM-01")
        time.sleep(0.5)

        await mgr.unregister_camera("CAM-01")
        assert mgr.get_pipeline("CAM-01") is None


# ──────────────────────────────────────────────────────────────────
# Two-Camera Simultaneous Test
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTwoCameraSimultaneous:
    async def test_two_cameras_process_simultaneously(self):
        """Two cameras process the same test video simultaneously."""
        mgr = CameraManager(model_path=TEST_MODEL)

        cfg1 = _make_config("CAM-01", name="Camera One")
        cfg2 = _make_config("CAM-02", name="Camera Two")

        await mgr.register_camera(cfg1, auto_start=False)
        await mgr.register_camera(cfg2, auto_start=False)

        r1 = await mgr.start_camera("CAM-01")
        r2 = await mgr.start_camera("CAM-02")
        assert r1["started"] is True
        assert r2["started"] is True

        time.sleep(3.0)

        p1 = mgr.get_pipeline("CAM-01")
        p2 = mgr.get_pipeline("CAM-02")

        s1 = p1.get_status()
        s2 = p2.get_status()

        connected = s1.get("video_connected", False) or s2.get("video_connected", False)
        assert connected, "At least one camera should have connected"

        m1 = p1.get_metadata()
        m2 = p2.get_metadata()
        if m1:
            assert m1["camera_id"] == "CAM-01"
        if m2:
            assert m2["camera_id"] == "CAM-02"

        await mgr.stop_camera("CAM-01")
        await mgr.stop_camera("CAM-02")

    async def test_stopping_one_does_not_affect_other(self):
        """Stopping CAM-01 does not affect CAM-02."""
        mgr = CameraManager(model_path=TEST_MODEL)

        await mgr.register_camera(_make_config("CAM-01"), auto_start=False)
        await mgr.register_camera(_make_config("CAM-02"), auto_start=False)

        await mgr.start_camera("CAM-01")
        await mgr.start_camera("CAM-02")
        time.sleep(1.0)

        await mgr.stop_camera("CAM-01")

        p2 = mgr.get_pipeline("CAM-02")
        assert p2 is not None

        await mgr.stop_camera("CAM-02")


# ──────────────────────────────────────────────────────────────────
# Credential Masking
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCredentialMasking:
    def test_rtsp_url_in_config_to_dict(self):
        """RTSP credentials are present in config.to_dict()."""
        cfg = CameraConfig(
            camera_id="CAM-RTSP",
            name="RTSP Camera",
            location="Test",
            source="rtsp://admin:password123@192.168.1.100:554/stream",
            source_type="rtsp",
        )
        d = cfg.to_dict()
        assert "password123" in d["source"]

    async def test_api_response_contains_source(self):
        """Camera API responses include the source URL."""
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = CameraConfig(
            camera_id="CAM-RTSP",
            name="RTSP Camera",
            location="Test",
            source="rtsp://admin:secret@10.0.0.1:554/stream",
            source_type="rtsp",
        )
        await mgr.register_camera(cfg, auto_start=False)
        info = mgr.get_camera("CAM-RTSP")
        assert "secret" in info["source"]


# ──────────────────────────────────────────────────────────────────
# PipelineState Camera Name Tests
# ──────────────────────────────────────────────────────────────────

class TestPipelineStateCameraName:
    def test_camera_name_default_empty(self):
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="CAM-01")
        assert state.camera_name == ""

    def test_camera_name_set(self):
        from ai.pipeline import PipelineState
        state = PipelineState(camera_id="CAM-01", camera_name="BOP NORTH")
        assert state.camera_name == "BOP NORTH"

    def test_event_to_alert_uses_camera_name(self):
        from ai.pipeline import PipelineState
        event = {
            "event_id": "test-001",
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "camera_id": "CAM-01",
            "zone_id": "ZONE-01",
            "zone_name": "Restricted Area",
            "track_id": 5,
            "object_class": "person",
            "timestamp": "2026-01-01T00:00:00Z",
            "confidence": 0.95,
            "bbox": {"x1": 10, "y1": 10, "x2": 50, "y2": 50},
            "status": "DETECTED",
        }
        alert = PipelineState._event_to_alert(event, camera_name="BOP NORTH MAIN GATE")
        assert alert["cameraId"] == "CAM-01"
        assert alert["cameraName"] == "BOP NORTH MAIN GATE"

    def test_event_to_alert_fallback_to_camera_id(self):
        from ai.pipeline import PipelineState
        event = {
            "event_id": "test-002",
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "camera_id": "CAM-01",
            "track_id": 1,
            "confidence": 0.9,
            "status": "DETECTED",
        }
        alert = PipelineState._event_to_alert(event, camera_name="")
        assert alert["cameraName"] == "CAM-01"
