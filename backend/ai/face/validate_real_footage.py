"""Real-footage face detection validation + visual output.

Runs the REAL YuNet detector over sampled frames of a real video,
records honest statistics, and writes an annotated image so results can
be visually verified. No fabricated numbers.

Usage: python -m ai.face.validate_real_footage [video_path]
"""
import sys
import os
import time
import statistics

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ai.face.face_detector import (
    FaceDetector, associate_faces_with_persons,
)
from ai.tracking.tracker import TrackedObject
from ai.config import settings


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'data',
                     'surveillance_test.mp4'))
    out_dir = os.path.normpath(os.path.join(
        os.path.dirname(__file__), '..', '..', 'data', 'face_validation'))
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 74)
    print("REAL-FOOTAGE FACE DETECTION VALIDATION")
    print("=" * 74)
    print("video:", video)

    det = FaceDetector(score_threshold=0.4)
    if not det.initialize():
        print("BLOCKER: face detector unavailable — cannot validate.")
        return 1

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        print("BLOCKER: cannot open video.")
        return 1

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_src = cap.get(cv2.CAP_PROP_FPS) or 0.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print("frames=%d fps=%.1f res=%dx%d" % (total_frames, fps_src, w, h))

    frames_sampled = 0
    frames_with_faces = 0
    detections_total = 0
    confidences = []
    latencies = []
    sample_saved = 0

    # Sample every 10th frame up to ~60 sampled frames.
    idx = -1
    while frames_sampled < 60:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx % 10 != 0:
            continue
        frames_sampled += 1
        t0 = time.time()
        faces = det.detect(frame)
        latencies.append((time.time() - t0) * 1000)
        if faces:
            frames_with_faces += 1
            detections_total += len(faces)
            confidences.extend(f.confidence for f in faces)
            if sample_saved < 3:
                for f in faces:
                    x1, y1, x2, y2 = [int(v) for v in f.bbox]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 120), 2)
                    cv2.putText(frame, "FACE %.0f%%" % (f.confidence * 100),
                                (x1, max(14, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 120), 2)
                out_path = os.path.join(out_dir, "face_sample_%02d.jpg" % (sample_saved + 1))
                cv2.imwrite(out_path, frame)
                print("  saved visual:", out_path)
                sample_saved += 1

    cap.release()

    print()
    print("-" * 74)
    print("frames sampled:            %d" % frames_sampled)
    print("frames containing faces:   %d" % frames_with_faces)
    print("total face detections:     %d" % detections_total)
    if confidences:
        print("avg confidence:            %.3f" % statistics.mean(confidences))
        print("min confidence:            %.3f" % min(confidences))
        print("max confidence:            %.3f" % max(confidences))
    else:
        print("avg/min/max confidence:    n/a (no faces detected)")
    if latencies:
        s = sorted(latencies)
        print("avg inference latency:     %.1f ms" % statistics.mean(latencies))
        print("P50 latency:               %.1f ms" % s[len(s)//2])
        print("P95 latency:               %.1f ms" % s[min(int(len(s)*0.95), len(s)-1)])
        print("inference calls:           %d" % len(latencies))

    if detections_total == 0:
        print()
        print("NO faces detected in this footage. Faces are likely too "
              "small/distant or absent. Per task rules this is reported "
              "honestly and NOT treated as real-world validation.")
        print("Synthetic-fixture results (unit tests) cover the software path.")
        return 0

    # Person-track association statistics need ByteTrack; here we approximate
    # association eligibility only (no YOLO run) — real association happens in
    # the live pipeline. Faces without person tracks are 'unassociated'.
    print()
    print("associated person tracks:  measured in live pipeline (requires YOLO+ByteTrack)")
    print("unassociated faces here:   %d (no person tracks passed)" % detections_total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
