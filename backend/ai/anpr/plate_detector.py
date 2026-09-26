"""License plate region detection — YOLO primary, OpenCV fallback.

Primary: README-based YOLOv8 plate detection model resolved from
settings.PLATE_MODEL_PATH (default: models/license_plate/license_plate_detector.pt
— the checkpoint documented by the project README, single class
'license_plate'). Fallback: Classical OpenCV contour analysis when YOLO is
unavailable or fails.

The previous experimental detector (models/license_plate/best.pt) is
preserved for rollback and is NOT loaded unless PLATE_MODEL_PATH points to it.
"""

import cv2
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ai.config import settings


@dataclass
class PlateCandidate:
    """A candidate license plate region within a vehicle ROI."""
    bbox: tuple  # (x1, y1, x2, y2) relative to the vehicle ROI
    confidence: float
    area: float


def _find_model() -> Optional[Path]:
    """Resolve the active license-plate detection model (project-relative).

    Uses settings.PLATE_MODEL_PATH (default models/license_plate/
    license_plate_detector.pt — README-based checkpoint). Does not fall back
    to the previous experimental model — it must never be loaded implicitly.
    """
    path = Path(settings.PLATE_MODEL_PATH)
    if path.exists():
        return path
    return None


class PlateDetector:
    """Detects license plate regions within vehicle bounding boxes.

    Uses YOLO (primary) + OpenCV contour analysis (fallback).
    """

    def __init__(self):
        self._min_aspect = settings.ANPR_PLATE_ASPECT_MIN
        self._max_aspect = settings.ANPR_PLATE_ASPECT_MAX
        self._yolo_model = None
        self._yolo_available = False
        self._model_path: Optional[Path] = None
        self._init_yolo()

    def _init_yolo(self):
        """Try to load the active YOLO plate detection model."""
        try:
            from ultralytics import YOLO
            model_path = _find_model()
            if model_path is None:
                print(f"[PLATE-DETECTOR] plate model not found at {settings.PLATE_MODEL_PATH}, using OpenCV fallback")
                return
            self._yolo_model = YOLO(str(model_path))
            self._yolo_available = True
            self._model_path = model_path
            print(f"[PLATE-DETECTOR] YOLO model loaded: {model_path}")
        except ImportError:
            print("[PLATE-DETECTOR] ultralytics not installed, using OpenCV fallback")
        except Exception as e:
            print(f"[PLATE-DETECTOR] YOLO init failed: {e}, using OpenCV fallback")

    def detect_plates(self, vehicle_roi: np.ndarray) -> List[PlateCandidate]:
        """Detect license plate candidates within a vehicle ROI.

        Tries YOLO first, falls back to OpenCV contour analysis.
        """
        if vehicle_roi is None or vehicle_roi.size == 0:
            return []

        h, w = vehicle_roi.shape[:2]
        if h < 10 or w < 10:
            return []

        # Primary: YOLO detection
        if self._yolo_available and self._yolo_model is not None:
            candidates = self._detect_yolo(vehicle_roi, w, h)
            if candidates:
                return candidates

        # Fallback: OpenCV contour analysis
        return self._detect_opencv(vehicle_roi, w, h)

    def _detect_yolo(self, vehicle_roi: np.ndarray, w: int, h: int) -> List[PlateCandidate]:
        """YOLO-based plate detection."""
        try:
            results = self._yolo_model(vehicle_roi, verbose=False, conf=0.25)
            candidates = []
            for r in results:
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0])
                    bw = x2 - x1
                    bh = y2 - y1
                    if bw < 5 or bh < 5:
                        continue
                    candidates.append(PlateCandidate(
                        bbox=(int(x1), int(y1), int(x2), int(y2)),
                        confidence=conf,
                        area=bw * bh,
                    ))
            candidates.sort(key=lambda c: c.confidence, reverse=True)
            return candidates[:3]
        except Exception:
            return []

    def _detect_opencv(self, vehicle_roi: np.ndarray, w: int, h: int) -> List[PlateCandidate]:
        """OpenCV contour-based plate detection (fallback)."""
        gray = cv2.cvtColor(vehicle_roi, cv2.COLOR_BGR2GRAY)
        blurred = cv2.bilateralFilter(gray, 11, 17, 17)
        edges = cv2.Canny(blurred, 30, 200)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        dilated = cv2.dilate(closed, kernel, iterations=2)
        contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        roi_area = h * w

        for contour in contours:
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) < 4 or len(approx) > 6:
                continue
            x, y, cw, ch = cv2.boundingRect(approx)
            if ch == 0:
                continue
            aspect = cw / ch
            if aspect < self._min_aspect or aspect > self._max_aspect:
                continue
            plate_area = cw * ch
            area_ratio = plate_area / roi_area
            if area_ratio < 0.01 or area_ratio > 0.30:
                continue
            corner_score = 1.0 - abs(len(approx) - 4) * 0.1
            aspect_score = 1.0 - min(abs(aspect - 3.0) / 3.0, 1.0)
            area_score = 1.0 - min(abs(area_ratio - 0.05) / 0.05, 1.0)
            confidence = (corner_score * 0.4 + aspect_score * 0.3 + area_score * 0.3)
            confidence = max(0.1, min(confidence, 0.95))
            candidates.append(PlateCandidate(
                bbox=(x, y, x + cw, y + ch),
                confidence=confidence,
                area=plate_area,
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates[:3]

    def extract_plate_crop(self, vehicle_roi: np.ndarray, candidate: PlateCandidate,
                           padding: int = 5) -> Optional[np.ndarray]:
        """Extract a plate crop from the vehicle ROI.

        Args:
            vehicle_roi: The full vehicle image
            candidate: A PlateCandidate with bbox coordinates
            padding: Extra pixels around the plate for context

        Returns:
            Cropped plate image, or None if invalid
        """
        if vehicle_roi is None or candidate is None or vehicle_roi.ndim < 2:
            return None

        h, w = vehicle_roi.shape[:2]
        x1, y1, x2, y2 = candidate.bbox

        # Reject zero-area bbox BEFORE padding
        if x2 <= x1 or y2 <= y1:
            return None

        # Add padding
        x1 = max(0, x1 - padding)
        y1 = max(0, y1 - padding)
        x2 = min(w, x2 + padding)
        y2 = min(h, y2 + padding)

        if x2 <= x1 or y2 <= y1:
            return None

        crop = vehicle_roi[y1:y2, x1:x2]

        if crop.size == 0:
            return None

        return crop

    def preprocess_for_ocr(self, plate_crop: np.ndarray) -> np.ndarray:
        """Preprocess a plate crop for OCR.

        Operations:
        1. Convert to grayscale
        2. Upscale small crops so glyphs are readable (min height 80px)
        3. No thresholding / no denoising

        Args:
            plate_crop: Cropped license plate image (BGR)

        Returns:
            Preprocessed grayscale image suitable for OCR
        """
        if plate_crop is None or plate_crop.size == 0:
            return np.zeros((40, 120), dtype=np.uint8)

        # Convert to grayscale
        if len(plate_crop.shape) == 3:
            gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = plate_crop.copy()

        h, w = gray.shape[:2]
        if h > 0:
            if h < 80:
                scale = 80.0 / h
                target_w = max(int(w * scale), 40)
                gray = cv2.resize(gray, (target_w, 80), interpolation=cv2.INTER_CUBIC)
            elif h > 200:
                scale = 200.0 / h
                target_w = max(int(w * scale), 40)
                gray = cv2.resize(gray, (target_w, 200), interpolation=cv2.INTER_CUBIC)

        return gray
