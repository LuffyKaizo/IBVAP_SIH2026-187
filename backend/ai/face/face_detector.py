"""Real face detection using OpenCV YuNet (FaceDetectorYN).

Detector: YuNet face detection model (ONNX, ~230 KB).
Source: OpenCV Zoo — https://github.com/opencv/opencv_zoo
        models/face_detection_yunet/face_detection_yunet_2023mar.onnx
License: Apache-2.0 (OpenCV Zoo). Local CPU inference only.

DETECTION ONLY. This module never computes embeddings, never matches
identities, and never persists biometric data.

Design notes:
- Works on full frames or person crops. Coordinates returned in PIXELS
  of the image given to detect(); callers convert to normalized coords
  for transport.
- YuNet (OpenCV 5 build) requires setInputSize() to match the exact
  input image size, so the detector re-sets input size per image shape.
  This is cheap (no model reload).
- Lazily initialized and reused across frames.
"""

import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from ai.config import settings

# Model shipped with the repo (Apache-2.0, OpenCV Zoo).
MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")


@dataclass
class FaceDetection:
    """One detected face in PIXEL coordinates of the input image."""
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (pixels)
    landmarks: Optional[list] = None  # 5x (x, y) if available

    def to_dict(self, frame_w: int, frame_h: int) -> dict:
        """JSON-serializable dict with normalized bbox (0..1)."""
        x1, y1, x2, y2 = self.bbox
        return {
            "confidence": round(float(self.confidence), 4),
            "bbox": {
                "x1": round(min(max(x1 / frame_w, 0.0), 1.0), 4),
                "y1": round(min(max(y1 / frame_h, 0.0), 1.0), 4),
                "x2": round(min(max(x2 / frame_w, 0.0), 1.0), 4),
                "y2": round(min(max(y2 / frame_h, 0.0), 1.0), 4),
            },
        }


class FaceDetector:
    """YuNet-based face detector (local, CPU, lazily initialized)."""

    def __init__(self, model_path: Optional[str] = None,
                 score_threshold: Optional[float] = None):
        self._detector = None
        self._available = False
        self._init_tried = False
        self._model_path = model_path or os.path.join(
            MODEL_DIR, MODEL_FILENAME)
        self._score_threshold = (score_threshold if score_threshold is not None
                                 else settings.FACE_CONFIDENCE_THRESHOLD)
        self.last_inference_ms = 0.0

    def initialize(self) -> bool:
        """Load the YuNet ONNX model once. Returns True when available."""
        if self._init_tried:
            return self._available
        self._init_tried = True
        if not settings.FACE_DETECTION_ENABLED:
            return False
        if not os.path.exists(self._model_path):
            print("[IBVAP-FACE] YuNet model not found at %s" % self._model_path)
            return False
        try:
            # Input size is re-set per image inside detect(); start generic.
            self._detector = cv2.FaceDetectorYN.create(
                self._model_path, "", (320, 320),
                score_threshold=self._score_threshold)
            self._available = True
            print("[IBVAP-FACE] YuNet face detector initialized "
                  "(model=%s)" % os.path.basename(self._model_path))
        except Exception as e:
            print("[IBVAP-FACE] YuNet init failed: %s" % e)
            self._available = False
        return self._available

    @property
    def is_available(self) -> bool:
        return self._available

    def detect(self, image: np.ndarray) -> List[FaceDetection]:
        """Detect faces in a BGR image. Returns pixel-coord detections.

        Never raises on bad input; returns [] on unusable images.
        """
        if not self._initialized_or_init():
            return []
        if image is None or not hasattr(image, "shape") or image.ndim < 2:
            return []
        h, w = image.shape[:2]
        if h < 8 or w < 8:
            return []
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        try:
            # OpenCV 5 FaceDetectorYN requires exact input size match.
            current = self._detector.getInputSize()
            if tuple(current) != (w, h):
                self._detector.setInputSize((w, h))
            t0 = time.time()
            _, faces = self._detector.detect(image)
            self.last_inference_ms = (time.time() - t0) * 1000.0
        except Exception as e:
            print("[IBVAP-FACE] detect error: %s" % e)
            return []

        results: List[FaceDetection] = []
        if faces is None:
            return results
        for f in faces:
            # YuNet row: x, y, w, h, 5 landmarks (x,y)*5, score
            x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
            score = float(f[-1])
            if score < self._score_threshold:
                continue
            # Clip to image bounds.
            x1, y1 = max(0.0, x), max(0.0, y)
            x2, y2 = min(float(w), x + fw), min(float(h), y + fh)
            if x2 <= x1 or y2 <= y1:
                continue
            landmarks = [(float(f[4 + i * 2]), float(f[5 + i * 2]))
                         for i in range(5)]
            results.append(FaceDetection(
                confidence=score, bbox=(x1, y1, x2, y2), landmarks=landmarks))
        return results

    def _initialized_or_init(self) -> bool:
        if not self._init_tried:
            return self.initialize()
        return self._available


# ---------------------------------------------------------------------------
# Face <-> person track association (explainable, conservative)
# ---------------------------------------------------------------------------

def _iou(a: Tuple[float, float, float, float],
         b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def associate_faces_with_persons(faces: List[FaceDetection],
                                 person_tracks: list,
                                 frame_w: int, frame_h: int,
                                 min_overlap: Optional[float] = None) -> List[dict]:
    """Associate each face with at most one person track.

    Method (explainable):
      1. Compute IoU(face bbox, person bbox) in pixel space.
      2. A face matches a person if the face CENTER lies inside the person
         bbox AND IoU-based containment overlap >= min_overlap, where
         overlap = intersection_area / face_area (containment ratio).
      3. Best (highest overlap) person wins; ties broken by larger person
         bbox area (closer person).
      4. Never forces an association; unassociated faces get personTrackId=None.
      5. Only 'person' class tracks are eligible — never vehicles.

    Returns transport-ready dicts with normalized bbox and metadata.
    """
    thr = min_overlap if min_overlap is not None else \
        settings.FACE_PERSON_OVERLAP_THRESHOLD

    people = [t for t in person_tracks if t.class_name == "person"]
    out: List[dict] = []
    for idx, face in enumerate(faces):
        fx1, fy1, fx2, fy2 = face.bbox
        face_area = max(1e-6, (fx2 - fx1) * (fy2 - fy1))
        cx = (fx1 + fx2) / 2.0
        cy = (fy1 + fy2) / 2.0

        best_tid = None
        best_overlap = 0.0
        best_area = 0.0
        for p in people:
            px1, py1, px2, py2 = p.bbox
            inside = px1 <= cx <= px2 and py1 <= cy <= py2
            ix1, iy1 = max(fx1, px1), max(fy1, py1)
            ix2, iy2 = min(fx2, px2), min(fy2, py2)
            iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
            contain = (iw * ih) / face_area
            if not inside or contain < thr:
                continue
            p_area = (px2 - px1) * (py2 - py1)
            if contain > best_overlap or (contain == best_overlap and p_area > best_area):
                best_tid = p.track_id
                best_overlap = contain
                best_area = p_area

        d = face.to_dict(frame_w, frame_h)
        d.update({
            "id": "FACE-%03d" % (idx + 1),
            "personTrackId": best_tid,
            "timestamp": None,  # set by caller (pipeline) for consistency
            "source": "AI",
        })
        out.append(d)
    return out
