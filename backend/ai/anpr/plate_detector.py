"""License plate region detection using OpenCV contour analysis.

This module detects candidate license plate regions within vehicle ROIs
using edge detection, morphological operations, and contour filtering.

The detector does NOT require a separate ML model — it uses classical
computer vision techniques that work well for standard license plates
in reasonable visibility conditions.
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Optional

from ai.config import settings


@dataclass
class PlateCandidate:
    """A candidate license plate region within a vehicle ROI."""
    bbox: tuple  # (x1, y1, x2, y2) relative to the vehicle ROI
    confidence: float
    area: float


class PlateDetector:
    """Detects license plate regions within vehicle bounding boxes.
    
    Uses a multi-stage approach:
    1. Convert to grayscale
    2. Edge detection (Canny)
    3. Morphological closing to connect plate edges
    4. Contour detection
    5. Rectangular contour filtering by aspect ratio and area
    """

    def __init__(self):
        self._min_aspect = settings.ANPR_PLATE_ASPECT_MIN
        self._max_aspect = settings.ANPR_PLATE_ASPECT_MAX

    def detect_plates(self, vehicle_roi: np.ndarray) -> List[PlateCandidate]:
        """Detect license plate candidates within a vehicle ROI.
        
        Args:
            vehicle_roi: Cropped image of the vehicle (BGR)
            
        Returns:
            List of PlateCandidate objects, sorted by confidence (best first)
        """
        if vehicle_roi is None or vehicle_roi.size == 0:
            return []

        h, w = vehicle_roi.shape[:2]
        if h < 10 or w < 10:
            return []

        # Stage 1: Preprocessing
        gray = cv2.cvtColor(vehicle_roi, cv2.COLOR_BGR2GRAY)
        
        # Apply bilateral filter to reduce noise while keeping edges
        blurred = cv2.bilateralFilter(gray, 11, 17, 17)
        
        # Stage 2: Edge detection
        edges = cv2.Canny(blurred, 30, 200)
        
        # Stage 3: Morphological closing to connect plate edges
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        
        # Stage 4: Dilate to thicken edges
        dilated = cv2.dilate(closed, kernel, iterations=2)
        
        # Stage 5: Find contours
        contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        
        candidates = []
        
        for contour in contours:
            # Approximate contour to polygon
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            
            # License plates are typically quadrilaterals
            if len(approx) < 4 or len(approx) > 6:
                continue
            
            # Get bounding rectangle
            x, y, cw, ch = cv2.boundingRect(approx)
            
            # Filter by aspect ratio (plates are wider than tall)
            if ch == 0:
                continue
            aspect = cw / ch
            
            if aspect < self._min_aspect or aspect > self._max_aspect:
                continue
            
            # Filter by area (relative to ROI)
            roi_area = h * w
            plate_area = cw * ch
            
            # Plate should be between 1% and 30% of vehicle area
            area_ratio = plate_area / roi_area
            if area_ratio < 0.01 or area_ratio > 0.30:
                continue
            
            # Calculate confidence based on shape quality
            # Better approximations (closer to 4 corners) and good aspect = higher confidence
            corner_score = 1.0 - abs(len(approx) - 4) * 0.1
            aspect_score = 1.0 - min(abs(aspect - 3.0) / 3.0, 1.0)  # ideal ratio ~3:1
            area_score = 1.0 - min(abs(area_ratio - 0.05) / 0.05, 1.0)  # ideal ~5%
            
            confidence = (corner_score * 0.4 + aspect_score * 0.3 + area_score * 0.3)
            confidence = max(0.1, min(confidence, 0.95))
            
            candidates.append(PlateCandidate(
                bbox=(x, y, x + cw, y + ch),
                confidence=confidence,
                area=plate_area,
            ))
        
        # Sort by confidence (best first)
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        
        # Return top candidates (usually just 1 plate per vehicle)
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
        
        Evidence-based (bench_preprocess.py, real EasyOCR inference):
        - Binarization (adaptive/Otsu) does NOT improve recognition and can
          destroy anti-aliased glyph shapes EasyOCR expects (adaptive
          thresholding even injected a spurious character on one test image).
        - Grayscale with upscaling matches color input accuracy at lower cost.
        
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
                # Upscale small plate crops (only upscaling, never downscaling)
                scale = 80.0 / h
                target_w = max(int(w * scale), 40)
                gray = cv2.resize(gray, (target_w, 80), interpolation=cv2.INTER_CUBIC)
            elif h > 200:
                # Cap very large crops to bound OCR cost
                scale = 200.0 / h
                target_w = max(int(w * scale), 40)
                gray = cv2.resize(gray, (target_w, 200), interpolation=cv2.INTER_CUBIC)
        
        return gray
