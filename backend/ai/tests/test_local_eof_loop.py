"""Local-file EOF must look like a seamless loop, never a disconnect.

Regression coverage for two production bugs at every local-video loop
boundary:

1. read_frame() used to set _connected=False / ST_DISCONNECTED on local
   EOF, so /status polls (frontend health badge polling every 3s) flipped
   to DISCONNECTED mid-loop even though the source was fine — the camera
   looked dead for the whole reopen window.

2. The pipeline's EOF handler used to release() and reopen the decoder
   every loop, churning native ffmpeg memory across the 6-camera fleet
   (RSS grew by hundreds of MB per EOF until the process died silently).

The contract now: local EOF keeps the session CONNECTED, and rewind()
seeks the SAME open decoder back to frame 0. Genuine handle death must
still report DISCONNECTED, and network/webcam sources must not rewind.
"""

import numpy as np
import cv2
import pytest

from ai.video.capture import VideoCapture, ST_CONNECTED, ST_DISCONNECTED


@pytest.fixture
def tiny_mp4(tmp_path):
    """An 8-frame clip whose pixel values encode the frame index."""
    path = str(tmp_path / "loop_src.mp4")
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48))
    assert out.isOpened(), "cv2.VideoWriter failed to open %s" % path
    for i in range(8):
        frame = np.full((48, 64, 3), 0, dtype=np.uint8)
        frame[:] = (i * 20, 100, 200)
        out.write(frame)
    out.release()
    return path


def _open(source: str, source_type: str = "video") -> VideoCapture:
    cap = VideoCapture(source=source, source_type=source_type)
    assert cap.open(), "failed to open %s" % source
    return cap


def _drain(cap: VideoCapture) -> int:
    count = 0
    while cap.read_frame() is not None:
        count += 1
    return count


def test_local_eof_keeps_session_connected(tiny_mp4):
    """EOF must NOT flip the capture to DISCONNECTED (badge never flips)."""
    cap = _open(tiny_mp4)
    try:
        count = _drain(cap)
        assert count == 8, "expected the full clip to decode"
        assert cap.at_eof is True
        status = cap.get_status()
        assert status.status == ST_CONNECTED, (
            "local EOF must not report DISCONNECTED to /status polls"
        )
        assert status.connected is True
    finally:
        cap.release()


def test_rewind_returns_to_first_frame_and_stays_connected(tiny_mp4):
    """rewind() seeks the same handle to frame 0 across repeated loops."""
    cap = _open(tiny_mp4)
    try:
        first = cap.read_frame()
        assert first is not None

        # Reach EOF on the same handle.
        while cap.read_frame() is not None:
            pass
        assert cap.at_eof is True

        # Rewind: status stays CONNECTED across the whole boundary — this
        # is exactly what /status polling observes.
        assert cap.rewind() is True
        assert cap.at_eof is False
        assert cap.get_status().status == ST_CONNECTED

        again = cap.read_frame()
        assert again is not None
        assert np.array_equal(again, first), "rewind must return the true first frame"

        # Second full cycle on the SAME handle — no reopen, no reconnect.
        read = 1
        while cap.read_frame() is not None:
            read += 1
        assert read == 8
        assert cap.at_eof is True

        assert cap.rewind() is True
        status = cap.get_status()
        assert status.status == ST_CONNECTED
        assert status.connected is True
        assert status.reconnect_count == 0, "rewind must not count as a reconnect"
    finally:
        cap.release()


def test_rewind_rejected_for_network_sources():
    """Network sources keep the documented reconnect path — no rewind."""
    cap = VideoCapture(source="rtsp://cam.example/stream", source_type="rtsp")
    assert cap.rewind() is False
    assert cap.get_status().status == ST_DISCONNECTED


def test_rewind_rejected_when_handle_not_open(tiny_mp4):
    """rewind() on a closed/unopened handle must fail, not raise."""
    cap = VideoCapture(source=tiny_mp4, source_type="video")
    assert cap.rewind() is False


def test_genuine_handle_death_still_reports_disconnected(tiny_mp4):
    """A dead handle is still a real disconnect — don't mask it."""
    cap = _open(tiny_mp4)
    try:
        assert cap.read_frame() is not None
        cap._cap.release()  # kill only the underlying handle
        assert cap.read_frame() is None
        assert cap.get_status().status == ST_DISCONNECTED
    finally:
        cap._cap = None
        cap.release()
