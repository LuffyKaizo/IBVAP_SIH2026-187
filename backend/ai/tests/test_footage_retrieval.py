"""Tests for SD-card footage retrieval service.

Tests the footage discovery, retrieval, processing lifecycle, and cleanup
for all three backends: ONVIF, FTP, and local filesystem.
"""

import os
import time
import tempfile
import shutil
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from ai.camera.footage_retrieval import (
    FootageRetrievalService,
    RecordedFootageFile,
    FootageStatus,
    RetrievalBackend,
    OnvifFootageBackend,
    FtpFootageBackend,
    LocalFsFootageBackend,
    _get_backend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_footage_dir():
    """Create a temp directory for footage testing."""
    d = tempfile.mkdtemp(prefix="ibvap_footage_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_sd_card(tmp_footage_dir):
    """Create a simulated SD card directory with test video files."""
    sd = os.path.join(tmp_footage_dir, "sd_card")
    os.makedirs(sd)
    # Create dummy video files
    for name in ["clip_001.mp4", "clip_002.mp4", "clip_003.ts", "readme.txt"]:
        path = os.path.join(sd, name)
        with open(path, "wb") as f:
            f.write(os.urandom(1024))
    return sd


# ---------------------------------------------------------------------------
# RecordedFootageFile tests
# ---------------------------------------------------------------------------

class TestRecordedFootageFile:
    def test_create_footage_file(self):
        now = datetime.now(timezone.utc)
        f = RecordedFootageFile(
            footage_id="F-001",
            camera_id="CAM-01",
            filename="clip.mp4",
            remote_path="/sd/clip.mp4",
            start_time=now,
            end_time=now,
            file_size_bytes=1024,
            duration_sec=10.0,
        )
        assert f.footage_id == "F-001"
        assert f.camera_id == "CAM-01"
        assert f.status == FootageStatus.DISCOVERED

    def test_to_dict(self):
        now = datetime.now(timezone.utc)
        f = RecordedFootageFile(
            footage_id="F-002",
            camera_id="CAM-02",
            filename="rec.ts",
            remote_path="/sd/rec.ts",
            start_time=now,
            end_time=now + timedelta(seconds=30),
            file_size_bytes=2048,
            duration_sec=30.0,
        )
        d = f.to_dict()
        assert d["footage_id"] == "F-002"
        assert d["camera_id"] == "CAM-02"
        assert d["status"] == "DISCOVERED"
        assert "start_time" in d
        assert "end_time" in d

    def test_status_transitions(self):
        now = datetime.now(timezone.utc)
        f = RecordedFootageFile(
            footage_id="F-003",
            camera_id="CAM-01",
            filename="test.mp4",
            remote_path="/sd/test.mp4",
            start_time=now,
            end_time=now,
            file_size_bytes=512,
            duration_sec=5.0,
        )
        assert f.status == FootageStatus.DISCOVERED
        f.status = FootageStatus.RETRIEVING
        assert f.status == FootageStatus.RETRIEVING
        f.status = FootageStatus.RETRIEVED
        assert f.status == FootageStatus.RETRIEVED
        f.status = FootageStatus.PROCESSING
        assert f.status == FootageStatus.PROCESSING
        f.status = FootageStatus.COMPLETED
        assert f.status == FootageStatus.COMPLETED


# ---------------------------------------------------------------------------
# Backend factory tests
# ---------------------------------------------------------------------------

class TestBackendFactory:
    def test_get_onvif_backend(self):
        backend = _get_backend(RetrievalBackend.ONVIF, "rtsp://192.168.1.100/stream")
        assert isinstance(backend, OnvifFootageBackend)

    def test_get_ftp_backend(self):
        backend = _get_backend(RetrievalBackend.FTP, "ftp://192.168.1.100/recordings")
        assert isinstance(backend, FtpFootageBackend)

    def test_get_local_fs_backend(self):
        backend = _get_backend(RetrievalBackend.LOCAL_FS, "/mnt/sdcard")
        assert isinstance(backend, LocalFsFootageBackend)

    def test_get_none_backend(self):
        backend = _get_backend(RetrievalBackend.NONE, "rtsp://192.168.1.100/stream")
        assert backend is None


# ---------------------------------------------------------------------------
# ONVIF Backend tests
# ---------------------------------------------------------------------------

class TestOnvifBackend:
    def test_discover_returns_empty_list(self):
        backend = OnvifFootageBackend("rtsp://192.168.1.100/stream")
        files = backend.discover_footage("CAM-01")
        assert files == []

    def test_retrieve_returns_none(self):
        backend = OnvifFootageBackend("rtsp://192.168.1.100/stream")
        now = datetime.now(timezone.utc)
        footage = RecordedFootageFile(
            footage_id="F-001", camera_id="CAM-01", filename="clip.mp4",
            remote_path="/sd/clip.mp4", start_time=now, end_time=now,
            file_size_bytes=1024, duration_sec=10.0,
        )
        result = backend.retrieve_file(footage, "/tmp/test")
        assert result is None


# ---------------------------------------------------------------------------
# FTP Backend tests
# ---------------------------------------------------------------------------

class TestFtpBackend:
    def test_discover_returns_empty_list(self):
        backend = FtpFootageBackend("ftp://192.168.1.100/recordings")
        files = backend.discover_footage("CAM-01")
        assert files == []

    def test_retrieve_returns_none(self):
        backend = FtpFootageBackend("ftp://192.168.1.100/recordings")
        now = datetime.now(timezone.utc)
        footage = RecordedFootageFile(
            footage_id="F-001", camera_id="CAM-01", filename="clip.mp4",
            remote_path="/sd/clip.mp4", start_time=now, end_time=now,
            file_size_bytes=1024, duration_sec=10.0,
        )
        result = backend.retrieve_file(footage, "/tmp/test")
        assert result is None


# ---------------------------------------------------------------------------
# LocalFs Backend tests
# ---------------------------------------------------------------------------

class TestLocalFsBackend:
    def test_discover_finds_video_files(self, tmp_sd_card):
        backend = LocalFsFootageBackend(tmp_sd_card)
        files = backend.discover_footage("CAM-01")
        # Should find .mp4 and .ts files (not .txt)
        assert len(files) == 3
        filenames = {f.filename for f in files}
        assert "clip_001.mp4" in filenames
        assert "clip_002.mp4" in filenames
        assert "clip_003.ts" in filenames
        assert "readme.txt" not in filenames

    def test_discover_nonexistent_dir(self):
        backend = LocalFsFootageBackend("/nonexistent/path")
        files = backend.discover_footage("CAM-01")
        assert files == []

    def test_discover_with_since_filter(self, tmp_sd_card):
        backend = LocalFsFootageBackend(tmp_sd_card)
        since = datetime.now(timezone.utc) + timedelta(hours=1)  # future
        files = backend.discover_footage("CAM-01", since=since)
        assert len(files) == 0

    def test_retrieve_copies_file(self, tmp_sd_card, tmp_footage_dir):
        backend = LocalFsFootageBackend(tmp_sd_card)
        files = backend.discover_footage("CAM-01")
        assert len(files) > 0

        dest_dir = os.path.join(tmp_footage_dir, "retrieved")
        os.makedirs(dest_dir)
        result = backend.retrieve_file(files[0], dest_dir)
        assert result is not None
        assert os.path.isfile(result)
        assert os.path.getsize(result) == 1024  # matches our dummy file size

    def test_retrieve_nonexistent_file(self, tmp_sd_card, tmp_footage_dir):
        backend = LocalFsFootageBackend(tmp_sd_card)
        now = datetime.now(timezone.utc)
        footage = RecordedFootageFile(
            footage_id="F-X", camera_id="CAM-01", filename="nope.mp4",
            remote_path="/nonexistent/nope.mp4", start_time=now, end_time=now,
            file_size_bytes=0, duration_sec=0.0,
        )
        dest_dir = os.path.join(tmp_footage_dir, "retrieved")
        os.makedirs(dest_dir)
        result = backend.retrieve_file(footage, dest_dir)
        assert result is None


# ---------------------------------------------------------------------------
# FootageRetrievalService tests
# ---------------------------------------------------------------------------

class TestFootageRetrievalService:
    def test_init_creates_local_dir(self, tmp_footage_dir):
        svc_dir = os.path.join(tmp_footage_dir, "svc")
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source="rtsp://192.168.1.100/stream",
            backend=RetrievalBackend.NONE,
            local_processing_dir=svc_dir,
        )
        assert os.path.isdir(svc_dir)
        assert svc.camera_id == "CAM-01"
        assert svc.backend_type == RetrievalBackend.NONE

    def test_discover_no_backend_returns_empty(self, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source="rtsp://192.168.1.100/stream",
            backend=RetrievalBackend.NONE,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        files = svc.discover()
        assert files == []

    def test_discover_local_fs(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        files = svc.discover()
        assert len(files) == 3
        assert len(svc.get_all()) == 3

    def test_retrieve_unknown_footage_id(self, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source="rtsp://192.168.1.100/stream",
            backend=RetrievalBackend.NONE,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        result = svc.retrieve("NONEXISTENT")
        assert result is False

    def test_retrieve_all_local_fs(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        count = svc.retrieve_all()
        assert count == 3
        # All should now be RETRIEVED
        for f in svc.get_all():
            assert f.status == FootageStatus.RETRIEVED
            assert f.local_path is not None

    def test_get_next_to_process(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.retrieve_all()
        next_f = svc.get_next_to_process()
        assert next_f is not None
        assert next_f.status == FootageStatus.RETRIEVED

    def test_get_next_to_process_none_pending(self, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source="rtsp://192.168.1.100/stream",
            backend=RetrievalBackend.NONE,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        next_f = svc.get_next_to_process()
        assert next_f is None

    def test_mark_processing(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.retrieve_all()
        f = svc.get_next_to_process()
        svc.mark_processing(f.footage_id)
        assert f.status == FootageStatus.PROCESSING

    def test_mark_completed(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.retrieve_all()
        f = svc.get_next_to_process()
        svc.mark_processing(f.footage_id)
        svc.mark_completed(f.footage_id)
        assert f.status == FootageStatus.COMPLETED
        assert f.processed_at is not None

    def test_mark_failed(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.retrieve_all()
        f = svc.get_next_to_process()
        svc.mark_failed(f.footage_id, "Test error")
        assert f.status == FootageStatus.FAILED
        assert f.error_message == "Test error"

    def test_cleanup_removes_local_file(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.retrieve_all()
        f = svc.get_next_to_process()
        local_path = f.local_path
        assert local_path is not None
        assert os.path.isfile(local_path)
        svc.cleanup(f.footage_id)
        assert not os.path.isfile(local_path)

    def test_cleanup_all(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.retrieve_all()
        local_paths = [f.local_path for f in svc.get_all() if f.local_path]
        assert len(local_paths) == 3
        svc.cleanup_all()
        for p in local_paths:
            assert not os.path.isfile(p)

    def test_get_pending(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        pending = svc.get_pending()
        assert len(pending) == 3
        # Complete one
        svc.retrieve_all()
        f = svc.get_next_to_process()
        svc.mark_completed(f.footage_id)
        pending = svc.get_pending()
        assert len(pending) == 2

    def test_get_status_summary(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        summary = svc.get_status_summary()
        assert summary["camera_id"] == "CAM-01"
        assert summary["backend"] == "LOCAL_FS"
        assert summary["total_files"] == 3
        assert summary["by_status"]["DISCOVERED"] == 3

    def test_status_summary_after_processing(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.retrieve_all()
        f = svc.get_next_to_process()
        svc.mark_processing(f.footage_id)
        svc.mark_completed(f.footage_id)
        summary = svc.get_status_summary()
        assert summary["completed"] == 1
        assert summary["by_status"].get("RETRIEVED", 0) == 2

    def test_discover_idempotent(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        svc.discover()
        svc.discover()  # second call should not duplicate
        assert len(svc.get_all()) == 3

    def test_footage_to_dict(self, tmp_sd_card, tmp_footage_dir):
        svc = FootageRetrievalService(
            camera_id="CAM-01",
            camera_source=tmp_sd_card,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(tmp_footage_dir, "svc"),
        )
        files = svc.discover()
        d = files[0].to_dict()
        assert "footage_id" in d
        assert "status" in d
        assert d["status"] == "DISCOVERED"


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------

class TestEnums:
    def test_footage_status_values(self):
        assert FootageStatus.DISCOVERED.value == "DISCOVERED"
        assert FootageStatus.RETRIEVING.value == "RETRIEVING"
        assert FootageStatus.RETRIEVED.value == "RETRIEVED"
        assert FootageStatus.PROCESSING.value == "PROCESSING"
        assert FootageStatus.COMPLETED.value == "COMPLETED"
        assert FootageStatus.FAILED.value == "FAILED"
        assert FootageStatus.SKIPPED.value == "SKIPPED"

    def test_retrieval_backend_values(self):
        assert RetrievalBackend.ONVIF.value == "ONVIF"
        assert RetrievalBackend.FTP.value == "FTP"
        assert RetrievalBackend.LOCAL_FS.value == "LOCAL_FS"
        assert RetrievalBackend.NONE.value == "NONE"
