"""OCR engine for license plate text recognition.

Supports EasyOCR (preferred) and Tesseract as OCR backends.
Falls back gracefully when no OCR engine is available.
"""

import re
import numpy as np
import cv2
from typing import Optional, Tuple

from ai.config import settings


class OCREngine:
    """OCR engine for reading license plate text from cropped images.
    
    Supports:
    - EasyOCR (preferred, CPU/GPU)
    - Tesseract (requires system installation)
    - Fallback: returns None when no engine is available
    
    EasyOCR Reader is lazily initialized on first read_text() call and
    reused for all subsequent calls (no per-frame re-initialization).
    """

    def __init__(self):
        self._engine = None
        self._engine_name = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the OCR engine. Returns True if successful."""
        if self._initialized:
            return self._engine is not None

        self._initialized = True
        engine_choice = settings.ANPR_OCR_ENGINE.lower()

        if engine_choice in ("easyocr", "auto"):
            try:
                import easyocr
                use_gpu = settings.ANPR_OCR_GPU
                self._engine = easyocr.Reader(
                    ["en"],
                    gpu=use_gpu,
                    verbose=False,
                    # Uses default EasyOCR model cache at ~/.EasyOCR/model/
                )
                self._engine_name = "easyocr"
                mode = "GPU" if use_gpu else "CPU"
                print("[IBVAP-ANPR] EasyOCR engine initialized (%s mode)" % mode)
                return True
            except ImportError:
                print("[IBVAP-ANPR] EasyOCR not installed")
            except Exception as e:
                print("[IBVAP-ANPR] EasyOCR init failed: %s" % e)

        if engine_choice in ("tesseract", "auto"):
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                self._engine = pytesseract
                self._engine_name = "tesseract"
                print("[IBVAP-ANPR] Tesseract engine initialized")
                return True
            except Exception:
                print("[IBVAP-ANPR] Tesseract not available")

        print("[IBVAP-ANPR] No OCR engine available")
        return False

    def read_text(self, plate_image: np.ndarray) -> Tuple[Optional[str], float]:
        """Read text from a preprocessed plate image."""
        if not self._initialized:
            self.initialize()
        if self._engine is None:
            return None, 0.0
        if plate_image is None or plate_image.size == 0:
            return None, 0.0
        try:
            if self._engine_name == "easyocr":
                return self._read_easyocr(plate_image)
            elif self._engine_name == "tesseract":
                return self._read_tesseract(plate_image)
            else:
                return self._read_opencv_fallback(plate_image)
        except Exception as e:
            print("[IBVAP-ANPR] OCR error: %s" % e)
        return None, 0.0

    def read_text_multi(self, plate_image: np.ndarray,
                        max_candidates: int = 4) -> list:
        """Read text preserving every candidate reading (multi-candidate OCR).

        Runs EasyOCR on the plate image, plus an optional second pass on an
        upscaled variant when settings.ANPR_OCR_PASSES >= 2, and returns a
        list of candidate dicts sorted by confidence:
            {"raw": str, "normalized": str|None, "confidence": float,
             "variant": str}
        Nothing is fabricated: candidates are actual OCR outputs. The caller
        (temporal stabilizer) uses consistency across frames, not a single
        frame, to decide the final reading.
        """
        if not self._initialized:
            self.initialize()
        if self._engine is None or self._engine_name != "easyocr":
            # Fall back to single reading semantics.
            raw, norm, conf = self.read_text_raw(plate_image)
            return [{"raw": raw, "normalized": norm, "confidence": conf,
                     "variant": "primary"}] if norm else []
        if plate_image is None or plate_image.size == 0:
            return []

        variants = []
        variants.append(("primary", self._to_bgr(plate_image)))
        passes = getattr(settings, "ANPR_OCR_PASSES", 1)
        if passes >= 2:
            img3 = self._to_bgr(plate_image)
            h, w = img3.shape[:2]
            img3 = cv2.resize(img3, (int(w * 2), int(h * 2)),
                              interpolation=cv2.INTER_CUBIC)
            variants.append(("2x-upscale", img3))

        candidates = []
        for variant, img in variants:
            try:
                results = self._engine.readtext(img)
            except Exception as e:
                print("[IBVAP-ANPR] OCR error (%s): %s" % (variant, e))
                continue
            texts, confs = [], []
            for (bbox, text, conf) in results:
                if conf > 0.1 and text.strip():
                    texts.append(text.strip())
                    confs.append(float(conf))
            if not texts:
                continue
            combined = " ".join(texts)
            norm = self.normalize_plate_text(combined)
            avg_conf = sum(confs) / len(confs)
            if norm:
                candidates.append({
                    "raw": combined,
                    "normalized": norm,
                    "confidence": avg_conf,
                    "variant": variant,
                })

        # Deduplicate by normalized text keeping the highest confidence.
        best_by_text = {}
        for c in candidates:
            k = c["normalized"]
            if k not in best_by_text or c["confidence"] > best_by_text[k]["confidence"]:
                best_by_text[k] = c
        ranked = sorted(best_by_text.values(),
                        key=lambda c: c["confidence"], reverse=True)
        return ranked[:max_candidates]

    @staticmethod
    def _to_bgr(plate_image: np.ndarray) -> np.ndarray:
        """Ensure image is BGR (EasyOCR input format)."""
        if len(plate_image.shape) == 2:
            return cv2.cvtColor(plate_image, cv2.COLOR_GRAY2BGR)
        return plate_image

    def read_text_raw(self, plate_image: np.ndarray) -> Tuple[Optional[str], Optional[str], float]:
        """Read text returning raw and normalized results."""
        if not self._initialized:
            self.initialize()
        if self._engine is None:
            return None, None, 0.0
        if plate_image is None or plate_image.size == 0:
            return None, None, 0.0
        try:
            if self._engine_name == "easyocr":
                return self._read_easyocr_raw(plate_image)
            elif self._engine_name == "tesseract":
                normalized, conf = self._read_tesseract(plate_image)
                return normalized, normalized, conf
            else:
                return None, None, 0.0
        except Exception as e:
            print("[IBVAP-ANPR] OCR error: %s" % e)
        return None, None, 0.0

    def _read_easyocr(self, plate_image: np.ndarray) -> Tuple[Optional[str], float]:
        """Read plate text using EasyOCR."""
        raw, normalized, conf = self._read_easyocr_raw(plate_image)
        return normalized, conf

    def _read_easyocr_raw(self, plate_image: np.ndarray) -> Tuple[Optional[str], Optional[str], float]:
        """Read plate text using EasyOCR, returning raw and normalized."""
        if len(plate_image.shape) == 2:
            img = cv2.cvtColor(plate_image, cv2.COLOR_GRAY2BGR)
        else:
            img = plate_image

        results = self._engine.readtext(img)
        if not results:
            return None, None, 0.0

        texts = []
        confidences = []
        for (bbox, text, conf) in results:
            if conf > 0.1 and text.strip():
                texts.append(text.strip())
                confidences.append(conf)

        if not texts:
            return None, None, 0.0

        combined = " ".join(texts)
        normalized = self.normalize_plate_text(combined)
        avg_conf = sum(confidences) / len(confidences)
        return combined, normalized, avg_conf

    def _read_tesseract(self, plate_image: np.ndarray) -> Tuple[Optional[str], float]:
        """Read plate text using Tesseract."""
        import pytesseract
        config = "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        text = pytesseract.image_to_string(plate_image, config=config).strip()
        data = pytesseract.image_to_data(plate_image, config=config, output_type=pytesseract.Output.DICT)
        confs = [int(c) for c in data["conf"] if int(c) > 0]
        avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        normalized = self.normalize_plate_text(text)
        return normalized if normalized else None, avg_conf

    def _read_opencv_fallback(self, plate_image: np.ndarray) -> Tuple[Optional[str], float]:
        """Fallback OCR using OpenCV character region detection."""
        if plate_image is None or plate_image.size == 0:
            return None, 0.0
        gray = plate_image if len(plate_image.shape) == 2 else cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        h, w = gray.shape[:2]
        char_count = 0
        for i in range(1, num_labels):
            x, y, cw, ch, area = stats[i]
            if ch > 3 and cw > 2 and ch < h * 0.9 and area > 5:
                char_count += 1
        if char_count >= 3:
            return None, 0.3
        return None, 0.0

    @staticmethod
    def normalize_plate_text(text: str) -> Optional[str]:
        """Normalize OCR output for license plate format.
        
        Operations:
        - Strip whitespace, uppercase
        - Remove spaces/hyphens/separators
        - Keep only alphanumeric characters
        
        Does NOT replace O->0 or I->1 to avoid corrupting valid plates.
        """
        if not text:
            return None
        normalized = text.strip().upper()
        normalized = re.sub(r"[ \s\-_.]", "", normalized)
        normalized = re.sub(r"[^A-Z0-9]", "", normalized)
        if len(normalized) < 2:
            return None
        return normalized
