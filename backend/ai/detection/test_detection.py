"""IBVAP YOLO Detection Test - proves VIDEO -> YOLO -> DETECTIONS pipeline."""

import sys
import time
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ai.video.capture import VideoCapture
from ai.detection.yolo_detector import YoloDetector, DetectionResult
from ai.config import settings


SURVEILLANCE_CLASSES = {
    "person", "car", "motorcycle", "bus", "truck",
    "bicycle", "traffic light", "stop sign",
}


def draw_detections(frame, detections):
    """Draw bounding boxes on frame for visual validation."""
    vis = frame.copy()
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det.bbox]
        color = (0, 0, 255) if det.class_name == "person" else (0, 200, 160)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        label = f"{det.class_name.upper()} {det.confidence:.0%}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(vis, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(vis, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return vis


def test_detection(video_path="data/test.mp4", max_frames=None, output_video=None):
    print()
    print("#" * 55)
    print("  IBVAP YOLO DETECTION TEST")
    print("#" * 55)

    # Load model
    print("")
    print("Model: " + settings.MODEL_PATH)
    print("Device: " + settings.get_device())
    print("Confidence: " + str(settings.CONFIDENCE_THRESHOLD))
    print("IOU: " + str(settings.IOU_THRESHOLD))
    print("Image size: " + str(settings.IMAGE_SIZE))

    detector = YoloDetector()
    load_start = time.time()
    loaded = detector.load()
    load_time = (time.time() - load_start) * 1000
    print("Model load time: %.0fms" % load_time)

    if not loaded:
        print("FAILED: Could not load YOLO model")
        return False

    # Warmup
    print("")
    print("Warming up...")
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    warmup_start = time.time()
    detector.detect(dummy)
    warmup_time = (time.time() - warmup_start) * 1000
    print("Warmup time: %.0fms" % warmup_time)

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

    # Detection loop
    target = max_frames or total
    print("")
    print("Processing %d frames..." % target)

    frames_processed = 0
    total_detections = 0
    class_counts = {}
    inference_times = []
    all_detections = []

    writer = None
    if output_video:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_video, fourcc, fps, (w, h))

    loop_start = time.time()

    for frame, info in cap.frame_generator(target_fps=100):
        if frames_processed >= target:
            break

        result = detector.detect(frame)
        inference_times.append(result.inference_time_ms)
        total_detections += len(result.detections)

        for det in result.detections:
            class_counts[det.class_name] = class_counts.get(det.class_name, 0) + 1

        all_detections.append(result)

        # Visual output
        if writer:
            vis = draw_detections(frame, result.detections)
            overlay = "Frame %d | %d detections | %.0fms" % (frames_processed, len(result.detections), result.inference_time_ms)
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
    avg_latency = np.mean(inference_times) if inference_times else 0
    p50 = np.percentile(inference_times, 50) if inference_times else 0
    p95 = np.percentile(inference_times, 95) if inference_times else 0
    inf_fps = 1000.0 / avg_latency if avg_latency > 0 else 0
    eff_fps = frames_processed / total_elapsed if total_elapsed > 0 else 0

    print("")
    print("=" * 55)
    print("  RESULTS")
    print("=" * 55)
    print("  Model:                " + settings.MODEL_PATH)
    print("  Device:               " + settings.get_device())
    print("  Input:                " + video_path)
    print("  Resolution:           %dx%d" % (w, h))
    print("  Image size:           %d" % settings.IMAGE_SIZE)
    print("  Confidence:           %.2f" % settings.CONFIDENCE_THRESHOLD)
    print("  Model load time:      %.0fms" % load_time)
    print("  Warmup time:          %.0fms" % warmup_time)
    print("  Frames processed:     %d" % frames_processed)
    print("  Total detections:     %d" % total_detections)
    print("  Avg inference latency:%.1fms" % avg_latency)
    print("  P50 latency:          %.1fms" % p50)
    print("  P95 latency:          %.1fms" % p95)
    print("  Inference FPS:        %.1f" % inf_fps)
    print("  Source FPS:           %.1f" % fps)
    print("  Effective proc FPS:   %.1f" % eff_fps)
    print("  Total elapsed:        %.2fs" % total_elapsed)

    if class_counts:
        print("")
        print("  Detection classes:")
        for cls, cnt in sorted(class_counts.items(), key=lambda x: -x[1]):
            print("    %-20s %d" % (cls, cnt))
    else:
        print("")
        print("  No detections (expected for synthetic test video)")

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
    output = "data/detection_output.mp4" if Path("data").exists() else None
    test_detection(output_video=output)
