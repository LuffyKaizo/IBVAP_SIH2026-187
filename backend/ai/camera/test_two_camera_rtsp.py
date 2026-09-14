"""Two-camera RTSP integration test.

Starts MediaMTX, publishes two test video streams via PyAV,
and verifies that two CameraPipeline instances run simultaneously
with isolated state.

Requires:
- mediamtx.exe in .freebuff/rtsp_test/
- PyAV installed
- test.mp4 available
"""

import os
import sys
import time
import subprocess
import signal
import pytest

sys.path.insert(0, ".")

from ai.camera.config import CameraConfig
from ai.camera.pipeline import CameraPipeline

TEST_MODEL = os.path.join(os.path.dirname(__file__), "..", "..", "yolov8n.pt")
TEST_VIDEO = os.path.join(os.path.dirname(__file__), "..", "..", "data", "test.mp4")
MEDIAMTX = os.path.join(os.path.dirname(__file__), "..", "..", ".freebuff", "rtsp_test", "mediamtx.exe")
PUBLISHER = os.path.join(os.path.dirname(__file__), "..", "..", ".freebuff", "rtsp_test", "publish_stream.py")


def _check_prerequisites():
    """Check that all required files exist."""
    for path, name in [(MEDIAMTX, "MediaMTX"), (PUBLISHER, "Publisher script"), (TEST_VIDEO, "Test video")]:
        if not os.path.exists(path):
            pytest.skip("%s not found at %s" % (name, path))


@pytest.mark.skipif(
    not os.path.exists(MEDIAMTX),
    reason="MediaMTX not available"
)
class TestTwoCameraRTSP:
    """Integration test: two cameras processing RTSP streams simultaneously."""

    def test_two_cameras_simultaneous_rtsp(self):
        """Start two RTSP streams, connect two pipelines, verify isolation."""
        _check_prerequisites()

        mediamtx_proc = None
        publisher_procs = []
        pipelines = []

        try:
            # Start MediaMTX
            mediamtx_proc = subprocess.Popen(
                [MEDIAMTX],
                cwd=os.path.dirname(MEDIAMTX),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(2)

            # Start two publisher streams
            for port in [8554, 8555]:
                pub = subprocess.Popen(
                    [sys.executable, PUBLISHER, "--port", str(port)],
                    cwd=os.path.dirname(PUBLISHER),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                publisher_procs.append(pub)
            time.sleep(3)

            # Create two camera configs pointing to the RTSP streams
            cfg1 = CameraConfig(
                camera_id="CAM-01",
                name="Camera One",
                location="Test Location 1",
                source="rtsp://127.0.0.1:8554/stream",
                source_type="rtsp",
            )
            cfg2 = CameraConfig(
                camera_id="CAM-02",
                name="Camera Two",
                location="Test Location 2",
                source="rtsp://127.0.0.1:8555/stream",
                source_type="rtsp",
            )

            # Create two isolated pipelines
            p1 = CameraPipeline(cfg1, TEST_MODEL)
            p2 = CameraPipeline(cfg2, TEST_MODEL)
            p1.initialize()
            p2.initialize()
            pipelines = [p1, p2]

            # Start both
            assert p1.start() is True
            assert p2.start() is True

            # Wait for processing
            time.sleep(5.0)

            # Check both are running
            assert p1.is_running is True
            assert p2.is_running is True

            # Check status
            s1 = p1.get_status()
            s2 = p2.get_status()

            print("\n[CAM-01] Status: connected=%s, fps=%.1f, frames=%d" % (
                s1.get("video_connected"), s1.get("processing_fps", 0), s1.get("frames_processed", 0)))
            print("[CAM-02] Status: connected=%s, fps=%.1f, frames=%d" % (
                s2.get("video_connected"), s2.get("processing_fps", 0), s2.get("frames_processed", 0)))

            # Verify camera IDs are correct
            assert s1["camera_id"] == "CAM-01"
            assert s2["camera_id"] == "CAM-02"

            # Verify metadata camera IDs
            m1 = p1.get_metadata()
            m2 = p2.get_metadata()
            if m1:
                assert m1["camera_id"] == "CAM-01"
            if m2:
                assert m2["camera_id"] == "CAM-02"

            # Verify isolation: separate state objects
            assert p1._pipeline.state is not p2._pipeline.state
            assert p1._event_engine is not p2._event_engine
            assert p1._behavior_engine is not p2._behavior_engine
            assert p1._temporal is not p2._temporal

            print("\nTWO-CAMERA RTSP TEST PASSED")

        finally:
            # Clean shutdown
            for p in pipelines:
                try:
                    p.stop()
                except Exception:
                    pass
            for pub in publisher_procs:
                try:
                    pub.terminate()
                    pub.wait(timeout=5)
                except Exception:
                    pub.kill()
            if mediamtx_proc:
                try:
                    mediamtx_proc.terminate()
                    mediamtx_proc.wait(timeout=5)
                except Exception:
                    mediamtx_proc.kill()
