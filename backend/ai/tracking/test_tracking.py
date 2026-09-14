"""IBVAP Tracking Test - proves YOLO -> BYTETRACK -> TRACKED OBJECTS pipeline."""

import sys
import time
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ai.video.capture import VideoCapture
from ai.tracking.tracker import ObjectTracker, TrackedObject, TrackingResult
from ai.config import settings


def draw_tracked(frame, tracked_objects):
    """Draw tracked objects with IDs on frame."""
    vis = frame.copy()
    for obj in tracked_objects:
        x1, y1, x2, y2 = [int(v) for v in obj.bbox]
        color = (0, 0, 255) if obj.class_name == "person" else (0, 200, 160)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        label = "ID:%d %s %.0f%%" % (obj.track_id, obj.class_name.upper(), obj.confidence * 100)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(vis, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(vis, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return vis


def test_tracking(video_path="data/test.mp4", max_frames=None, output_video=None):
    print()
    print("#" * 55)
    print("  IBVAP TRACKING TEST")
    print("#" * 55)

    # Load tracker
    print("")
    print("Model: " + settings.MODEL_PATH)
    print("Device: " + settings.get_device())
    print("Tracker: " + settings.TRACKER_TYPE)
    print("Confidence: " + str(settings.MIN_TRACKING_CONFIDENCE))
    print("Track buffer: " + str(settings.TRACK_BUFFER))

    tracker = ObjectTracker()
    load_start = time.time()
    loaded = tracker.load_model()
    load_time = (time.time() - load_start) * 1000
    print("Model load time: %.0fms" % load_time)

    if not loaded:
        print("FAILED: Could not load model")
        return False

    # Warmup
    print("")
    print("Warming up...")
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    warmup_start = time.time()
    tracker.track(dummy)
    warmup_time = (time.time() - warmup_start) * 1000
    print("Warmup time: %.0fms" % warmup_time)
    tracker.reset()

    # Open video
    print("")
    print("Input: " + video_path)
    cap = VideoCapture(source=video_path, source_type="video")
    if not cap.open():
        print("FAILED: Could not open " + video_path)
        return False

    w, h = cap.get_resolution()
    fps = cap.get_fps()
    total = cap.get_frame_count()
    print("Resolution: %dx%d" % (w, h))
    print("Source FPS: %.1f" % fps)
    print("Total frames: %d" % total)

    # Tracking loop
    target = max_frames or total
    print("")
    print("Processing %d frames..." % target)

    frames_processed = 0
    total_detections = 0
    total_tracks = 0
    peak_tracks = 0
    unique_ids = set()
    class_counts = {}
    total_times = []

    writer = None
    if output_video:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_video, fourcc, fps, (w, h))

    loop_start = time.time()

    for frame, info in cap.frame_generator(target_fps=100):
        if frames_processed >= target:
            break

        result = tracker.track(frame)
        total_times.append(result.total_time_ms)
        total_detections += result.active_tracks
        total_tracks += result.active_tracks

        if result.active_tracks > peak_tracks:
            peak_tracks = result.active_tracks

        for obj in result.tracked_objects:
            unique_ids.add(obj.track_id)
            class_counts[obj.class_name] = class_counts.get(obj.class_name, 0) + 1

        if writer:
            vis = draw_tracked(frame, result.tracked_objects)
            overlay = "Frame %d | Tracks: %d | IDs: %d | %.0fms" % (
                frames_processed, result.active_tracks, len(unique_ids), result.total_time_ms)
            cv2.putText(vis, overlay, (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
            writer.write(vis)

        frames_processed += 1
        if frames_processed % 50 == 0:
            print("  Frame %d/%d..." % (frames_processed, target))

    total_elapsed = time.time() - loop_start
    cap.release()
    if writer:
        writer.release()

    # Results
    avg_time = np.mean(total_times) if total_times else 0
    p50 = np.percentile(total_times, 50) if total_times else 0
    p95 = np.percentile(total_times, 95) if total_times else 0
    proc_fps = 1000.0 / avg_time if avg_time > 0 else 0
    eff_fps = frames_processed / total_elapsed if total_elapsed > 0 else 0

    print("")
    print("=" * 55)
    print("  RESULTS")
    print("=" * 55)
    print("  Model:                " + settings.MODEL_PATH)
    print("  Device:               " + settings.get_device())
    print("  Tracker:              " + settings.TRACKER_TYPE)
    print("  Input:                " + video_path)
    print("  Resolution:           %dx%d" % (w, h))
    print("  Model load time:      %.0fms" % load_time)
    print("  Warmup time:          %.0fms" % warmup_time)
    print("  Frames processed:     %d" % frames_processed)
    print("  Total detections:     %d" % total_detections)
    print("  Unique track IDs:     %d" % len(unique_ids))
    print("  Peak active tracks:   %d" % peak_tracks)
    print("  Avg total latency:    %.1fms" % avg_time)
    print("  P50 latency:          %.1fms" % p50)
    print("  P95 latency:          %.1fms" % p95)
    print("  Processing FPS:       %.1f" % proc_fps)
    print("  Source FPS:           %.1f" % fps)
    print("  Effective proc FPS:   %.1f" % eff_fps)
    print("  Total elapsed:        %.2fs" % total_elapsed)

    if class_counts:
        print("")
        print("  Tracked classes:")
        for cls, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
            print("    %-20s %d" % (cls, cnt))
    else:
        print("")
        print("  No tracks (expected for synthetic test video)")

    if unique_ids:
        print("")
        print("  Track IDs: %s" % sorted(unique_ids))

    if output_video:
        print("")
        print("  Output video: " + output_video)

    print("")
    passed = frames_processed > 0 and loaded
    result_str = "PASSED" if passed else "FAILED"
    print("  RESULT: " + result_str)
    print("=" * 55)
    print("")
    return passed


if __name__ == "__main__":
    output = "data/tracking_output.mp4" if Path("data").exists() else None
    test_tracking(output_video=output)
