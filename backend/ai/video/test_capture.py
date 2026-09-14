"""IBVAP Video Capture Test - proves VIDEO -> FRAME pipeline works."""

import sys
import time
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ai.video.capture import VideoCapture
from ai.config import settings


def test_mp4_capture():
    print()
    print("=" * 50)
    print("TEST 1: MP4 FILE CAPTURE")
    print("=" * 50)

    source = str(Path("data/test.mp4").resolve())
    source_type = "video"
    target_fps = 10

    print(f"Source: {source}")
    print(f"Type: {source_type}")
    print(f"Target FPS: {target_fps}")

    if not Path(source).exists():
        print(f"ERROR: Test video not found at {source}")
        return False

    file_size = Path(source).stat().st_size / 1024
    print(f"File size: {file_size:.1f} KB")

    cap = VideoCapture(source=source, source_type=source_type)
    opened = cap.open()
    print(f"Opened: {opened}")

    if not opened:
        print("FAILED: Could not open video source")
        return False

    w, h = cap.get_resolution()
    fps = cap.get_fps()
    total = cap.get_frame_count()
    print(f"Resolution: {w}x{h}")
    print(f"Source FPS: {fps}")
    print(f"Total frames: {total}")

    print(f"Reading frames at {target_fps} FPS target...")
    frames_read = 0
    start = time.time()

    for frame, info in cap.frame_generator(target_fps=target_fps):
        frames_read += 1
        assert isinstance(frame, np.ndarray)
        assert frame.ndim == 3
        if frames_read <= 3:
            print(f"  Frame {info.frame_number}: {info.width}x{info.height} @ {info.timestamp_sec}s ({info.read_latency_ms}ms)")
        elif frames_read == 4:
            print("  ...")

    elapsed = time.time() - start
    effective_fps = frames_read / elapsed if elapsed > 0 else 0

    status = cap.get_status()
    cap.release()

    print(f"Frames read: {frames_read}")
    print(f"Elapsed: {elapsed:.2f} sec")
    print(f"Effective read FPS: {effective_fps:.1f}")
    print(f"Capture stopped: YES")
    print(f"Resources released: {not cap.is_connected}")
    print(f"Status connected: {status.connected}")

    passed = opened and frames_read > 0 and not cap.is_connected
    print(f"RESULT: {passed}")
    return passed


def test_missing_file():
    print()
    print("=" * 50)
    print("TEST 2: MISSING FILE HANDLING")
    print("=" * 50)
    cap = VideoCapture(source="./nonexistent.mp4", source_type="video")
    opened = cap.open()
    print(f"Opened: {opened}")
    frame = cap.read_frame()
    print(f"Read frame: {frame}")
    cap.release()
    passed = not opened and frame is None
    print(f"RESULT: {passed}")
    return passed


def test_webcam_failure():
    print()
    print("=" * 50)
    print("TEST 3: WEBCAM FAILURE HANDLING")
    print("=" * 50)
    cap = VideoCapture(source="99", source_type="webcam")
    opened = cap.open()
    print(f"Opened webcam 99: {opened}")
    cap.release()
    passed = not opened
    print(f"RESULT: {passed}")
    return passed


def test_rtsp_failure():
    print()
    print("=" * 50)
    print("TEST 4: RTSP FAILURE HANDLING")
    print("=" * 50)
    # RTSP now uses bounded-exponential-backoff reconnect (retry-forever by
    # default so a power-cycled camera recovers). This test opts into a
    # small attempt budget; the assertion (open fails, no hang) is unchanged.
    from ai.config import settings as _s
    old_attempts = _s.RECONNECT_MAX_ATTEMPTS
    _s.RECONNECT_MAX_ATTEMPTS = 3
    cap = VideoCapture(source="rtsp://192.168.1.999:554/fake", source_type="rtsp")
    start = time.time()
    opened = cap.open()
    elapsed = time.time() - start
    _s.RECONNECT_MAX_ATTEMPTS = old_attempts
    print(f"Opened fake RTSP: {opened}")
    print(f"Attempt time: {elapsed:.2f}s")
    cap.release()
    passed = not opened
    print(f"RESULT: {passed}")
    return passed


def test_end_of_video():
    print()
    print("=" * 50)
    print("TEST 5: END-OF-VIDEO HANDLING")
    print("=" * 50)
    source = str(Path("data/test.mp4").resolve())
    if not Path(source).exists():
        print("Skipped")
        return True
    cap = VideoCapture(source=source, source_type="video")
    cap.open()
    count = 0
    for frame, info in cap.frame_generator(target_fps=100):
        count += 1
    status = cap.get_status()
    cap.release()
    print(f"Frames consumed: {count}")
    print(f"Connected after EOF: {status.connected}")
    passed = count > 0 and not cap.is_connected
    print(f"RESULT: {passed}")
    return passed


def test_resource_cleanup():
    print()
    print("=" * 50)
    print("TEST 6: RESOURCE CLEANUP")
    print("=" * 50)
    source = str(Path("data/test.mp4").resolve())
    if not Path(source).exists():
        print("Skipped")
        return True
    for i in range(3):
        cap = VideoCapture(source=source, source_type="video")
        cap.open()
        for frame, info in cap.frame_generator(target_fps=100):
            pass
        cap.release()
    print("3 open/release cycles completed")
    passed = not cap.is_connected
    print(f"RESULT: {passed}")
    return passed


if __name__ == "__main__":
    print()
    print("#" * 50)
    print("  IBVAP VIDEO CAPTURE TEST")
    print("#" * 50)

    results = {}
    results["MP4 Capture"] = test_mp4_capture()
    results["Missing File"] = test_missing_file()
    results["Webcam Failure"] = test_webcam_failure()
    results["RTSP Failure"] = test_rtsp_failure()
    results["End of Video"] = test_end_of_video()
    results["Resource Cleanup"] = test_resource_cleanup()

    print()
    print("=" * 50)
    print("  SUMMARY")
    print("=" * 50)
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("  ALL TESTS PASSED")
    else:
        print("  SOME TESTS FAILED")
    print("=" * 50)

    sys.exit(0 if all_passed else 1)
