"""YOLO object detector using Ultralytics."""

import time
import numpy as np
from typing import Optional
from dataclasses import dataclass, field

from ai.config import settings


@dataclass
class Detection:
    """Single detection result."""
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (pixel coords)
    track_id: Optional[int] = None


@dataclass
class DetectionResult:
    """Result from a single frame inference."""
    detections: list[Detection] = field(default_factory=list)
    inference_time_ms: float = 0.0
    frame_width: int = 0
    frame_height: int = 0
    model_name: str = ""
    device: str = ""


class YoloDetector:
    """Wraps Ultralytics YOLO for border surveillance detection."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        confidence: Optional[float] = None,
        iou: Optional[float] = None,
        img_size: Optional[int] = None,
        device: Optional[str] = None,
    ):
        self.model_path = model_path or settings.MODEL_PATH
        self.confidence = confidence or settings.CONFIDENCE_THRESHOLD
        self.iou = iou or settings.IOU_THRESHOLD
        self.img_size = img_size or settings.IMAGE_SIZE
        self.device = device or settings.get_device()
        self._model = None
        self._class_names: dict[int, str] = {}

    def load(self) -> bool:
        """Load the YOLO model. Returns True on success."""
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_path)
            self._class_names = self._model.names
            return True
        except Exception as e:
            print(f"[IBVAP-AI] Failed to load YOLO model '{self.model_path}': {e}")
            self._model = None
            return False

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def detect(self, frame: np.ndarray) -> DetectionResult:
        """Run YOLO inference on a single BGR frame.

        Returns DetectionResult with bounding boxes, class names, and confidence.
        """
        if not self.is_loaded:
            return DetectionResult()

        h, w = frame.shape[:2]
        start = time.time()

        # Wide frames (4K CCTV): larger inference size for distant objects.
        imgsz = self.img_size if w <= settings.LARGE_FRAME_WIDTH else settings.IMAGE_SIZE_LARGE

        results = self._model(
            frame,
            conf=self.confidence,
            iou=self.iou,
            imgsz=imgsz,
            device=self.device,
            verbose=False,
        )

        elapsed_ms = (time.time() - start) * 1000

        detections = []
        if results and len(results) > 0:
            r = results[0]
            if r.boxes is not None:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    cls_name = self._class_names.get(cls_id, f"class_{cls_id}")
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    detections.append(Detection(
                        class_id=cls_id,
                        class_name=cls_name,
                        confidence=round(conf, 4),
                        bbox=(round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)),
                    ))

        return DetectionResult(
            detections=detections,
            inference_time_ms=round(elapsed_ms, 2),
            frame_width=w,
            frame_height=h,
            model_name=self.model_path,
            device=self.device,
        )

    def detect_batch(self, frames: list[np.ndarray]) -> list[DetectionResult]:
        """Run inference on multiple frames."""
        return [self.detect(f) for f in frames]
