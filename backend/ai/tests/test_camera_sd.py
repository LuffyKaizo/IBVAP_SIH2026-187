"""Tests for CameraManager SD-card synchronization lifecycle.

Tests the integration of FootageRetrievalService with CameraManager,
including footage sync triggering, lifecycle state transitions, and cleanup.
"""

import os
import tempfile
import shutil
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from ai.camera.config import CameraConfig
from ai.camera.manager import CameraManager, SYNC_STATE_IDLE, SYNC_STATE_SYNCING, SYNC_STATE_COMPLETED, SYNC_STATE_FAILED
from ai.camera.footage_retrieval import FootageRetrievalService, RetrievalBackend, FootageStatus, LocalFsFootageBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_MODEL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "yolov8n.pt")
TEST_VIDEO = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "test.mp4")


@pytest.fixture
def tmp_footage_dir():
    d = tempfile.mkdtemp(prefix="ibvap_cam_sd_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_sd_card(tmp_footage_dir):
    sd = os.path.join(tmp_footage_dir, "sd_card")
    os.makedirs(sd)
    for name in ["clip_001.mp4", "clip_002.mp4"]:
        path = os.path.join(sd, name)
        with open(path, "wb") as f:
            f.write(os.urandom(1024))
    return sd


def _make_config(camera_id="CAM-TEST", source_type="video", source=None,
                 enabled=True, sd_card_capable=False):
    if source is None:
        source = TEST_VIDEO
    return CameraConfig(
        camera_id=camera_id,
        name="Test Camera",
        location="Test Location",
        source=source,
        source_type=source_type,
        enabled=enabled,
        sd_card_capable=sd_card_capable,
    )


# ---------------------------------------------------------------------------
# CameraConfig SD-card fields tests
# ---------------------------------------------------------------------------

class TestCameraConfigSDCard:
    def test_default_sd_card_fields(self):
        cfg = _make_config("CAM-01")
        assert cfg.sd_card_capable is False
        assert cfg.sd_card_status == "UNKNOWN"
        assert cfg.sd_card_capacity_gb is None
        assert cfg.last_sync_at is None
        assert cfg.pending_footage_count == 0
        assert cfg.last_offline_at is None
        assert cfg.last_online_at is None

    def test_sd_card_capable_config(self):
        cfg = _make_config("CAM-01", sd_card_capable=True)
        assert cfg.sd_card_capable is True

    def test_to_dict_includes_sd_card_fields(self):
        cfg = _make_config("CAM-01", sd_card_capable=True)
        d = cfg.to_dict()
        assert "sd_card_capable" in d
        assert "sd_card_status" in d
        assert "pending_footage_count" in d
        assert "last_sync_at" in d
        assert "last_offline_at" in d
        assert "last_online_at" in d

    def test_from_dict_with_sd_card_fields(self):
        d = {
            "camera_id": "CAM-01",
            "name": "Test",
            "location": "Loc",
            "source": "rtsp://test",
            "source_type": "rtsp",
            "sd_card_capable": True,
            "sd_card_status": "HEALTHY",
            "pending_footage_count": 5,
        }
        cfg = CameraConfig.from_dict(d)
        assert cfg.sd_card_capable is True
        assert cfg.sd_card_status == "HEALTHY"
        assert cfg.pending_footage_count == 5

    def test_from_dict_ignores_unknown_fields(self):
        d = {
            "camera_id": "CAM-01",
            "name": "Test",
            "location": "Loc",
            "source": "rtsp://test",
            "source_type": "rtsp",
            "sd_card_capable": True,
            "unknown_field": "should be ignored",
        }
        cfg = CameraConfig.from_dict(d)
        assert cfg.sd_card_capable is True
        assert not hasattr(cfg, "unknown_field")


# ---------------------------------------------------------------------------
# CameraManager SD-card initialization tests
# ---------------------------------------------------------------------------

class TestCameraManagerSDInit:
    def test_no_footage_service_for_non_sd_camera(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", sd_card_capable=False)
        mgr._sync_register_camera(cfg)
        assert mgr.get_footage_service("CAM-01") is None
        assert mgr.get_sync_state("CAM-01") == SYNC_STATE_IDLE

    def test_footage_service_created_for_sd_capable_rtsp(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source="rtsp://192.168.1.100/stream",
                          sd_card_capable=True)
        mgr._sync_register_camera(cfg)
        svc = mgr.get_footage_service("CAM-01")
        assert svc is not None
        assert svc.backend_type == RetrievalBackend.ONVIF

    def test_no_footage_service_for_video_source_type(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="video",
                          sd_card_capable=True)
        mgr._sync_register_camera(cfg)
        # Local video files don't need SD-card sync
        assert mgr.get_footage_service("CAM-01") is None

    def test_sync_state_initial(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source="rtsp://192.168.1.100/stream",
                          sd_card_capable=True)
        mgr._sync_register_camera(cfg)
        assert mgr.get_sync_state("CAM-01") == SYNC_STATE_IDLE

    def test_sync_state_nonexistent_camera(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        assert mgr.get_sync_state("NONEXISTENT") == SYNC_STATE_IDLE


# ---------------------------------------------------------------------------
# CameraManager async SD-card lifecycle tests
# ---------------------------------------------------------------------------

class TestCameraManagerSyncLifecycle:
    @pytest.mark.asyncio
    async def test_trigger_sync_no_service(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", sd_card_capable=False)
        await mgr.register_camera(cfg)
        result = await mgr.trigger_footage_sync("CAM-01")
        assert result["synced"] is False
        assert "No footage service" in result["reason"]

    @pytest.mark.asyncio
    async def test_trigger_sync_with_local_fs(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing (real ONVIF needs network)
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        result = await mgr.trigger_footage_sync("CAM-01")
        assert result["synced"] is True
        assert result["files_found"] == 2

    @pytest.mark.asyncio
    async def test_trigger_sync_state_transitions(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        # Before trigger
        assert mgr.get_sync_state("CAM-01") == SYNC_STATE_IDLE
        # After trigger completes (local FS is synchronous)
        result = await mgr.trigger_footage_sync("CAM-01")
        assert result["synced"] is True
        assert mgr.get_sync_state("CAM-01") == SYNC_STATE_COMPLETED

    @pytest.mark.asyncio
    async def test_trigger_sync_with_no_footage(self, tmp_footage_dir):
        # Empty SD card directory
        empty_sd = os.path.join(tmp_footage_dir, "empty_sd")
        os.makedirs(empty_sd)
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=empty_sd,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(empty_sd)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        result = await mgr.trigger_footage_sync("CAM-01")
        assert result["synced"] is True
        assert result["files_found"] == 0

    @pytest.mark.asyncio
    async def test_unregister_cleans_footage_service(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        assert mgr.get_footage_service("CAM-01") is not None
        await mgr.unregister_camera("CAM-01")
        assert mgr.get_footage_service("CAM-01") is None
        assert mgr.get_sync_state("CAM-01") == SYNC_STATE_IDLE

    @pytest.mark.asyncio
    async def test_get_camera_includes_sync_state(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        info = mgr.get_camera("CAM-01")
        assert info is not None
        assert "sync_state" in info
        assert info["sync_state"] == SYNC_STATE_IDLE

    @pytest.mark.asyncio
    async def test_get_camera_includes_footage_summary(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        info = mgr.get_camera("CAM-01")
        assert "footage_summary" in info
        assert info["footage_summary"]["total_files"] == 0  # not yet discovered

    @pytest.mark.asyncio
    async def test_list_cameras_includes_sync_state(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        cameras = mgr.list_cameras()
        assert len(cameras) == 1
        assert "sync_state" in cameras[0]
        assert "footage_summary" in cameras[0]


# ---------------------------------------------------------------------------
# CameraManager process_next_footage tests
# ---------------------------------------------------------------------------

class TestCameraManagerProcessFootage:
    @pytest.mark.asyncio
    async def test_process_next_no_service(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", sd_card_capable=False)
        await mgr.register_camera(cfg)
        result = mgr.process_next_footage("CAM-01")
        assert result is False

    @pytest.mark.asyncio
    async def test_process_next_no_pending(self, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source="rtsp://192.168.1.100/stream",
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        result = mgr.process_next_footage("CAM-01")
        assert result is False

    @pytest.mark.asyncio
    async def test_process_next_with_footage(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        await mgr.register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        # Sync first
        await mgr.trigger_footage_sync("CAM-01")
        # Process next — random bytes won't open as video, but the method
        # handles this gracefully by marking as FAILED
        result = mgr.process_next_footage("CAM-01")
        # One file was attempted (either completed or failed)
        all_files = svc.get_all()
        processed = [f for f in all_files if f.status in (FootageStatus.COMPLETED, FootageStatus.FAILED)]
        assert len(processed) == 1


# ---------------------------------------------------------------------------
# CameraManager shutdown cleanup tests
# ---------------------------------------------------------------------------

class TestCameraManagerShutdown:
    def test_shutdown_clears_footage_services(self, tmp_sd_card, tmp_footage_dir):
        mgr = CameraManager(model_path=TEST_MODEL)
        cfg = _make_config("CAM-01", source_type="rtsp",
                          source=tmp_sd_card,
                          sd_card_capable=True)
        mgr._sync_register_camera(cfg)
        # Override backend to LOCAL_FS for testing
        svc = mgr.get_footage_service("CAM-01")
        svc._backend = LocalFsFootageBackend(tmp_sd_card)
        svc._backend_type = RetrievalBackend.LOCAL_FS
        assert len(mgr._footage_services) == 1
        mgr.shutdown_all()
        assert len(mgr._footage_services) == 0
        assert len(mgr._sync_states) == 0
