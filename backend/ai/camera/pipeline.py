"""Per-camera processing pipeline for IBVAP multi-camera management.

Each CameraPipeline owns completely isolated state:
- VideoCapture instance
- ObjectTracker (with its own YOLO model instance)
- EventEngine
- BehaviorEngine
- TemporalStabilizer (ANPR)
- FaceDetector
- PipelineState (latest frame, metadata, health)

No state is shared between CameraPipeline instances.
"""

import threading
from typing import Optional

from ai.camera.config import CameraConfig
from ai.pipeline import ProcessingPipeline
from ai.events.engine import EventEngine, Zone
from ai.events.behavior import BehaviorEngine
from ai.context.engine import ContextEngine
from ai.risk.engine import RiskEngine
from ai.anpr.plate_detector import PlateDetector
from ai.anpr.ocr_engine import OCREngine
from ai.anpr.temporal import TemporalStabilizer
from ai.face.face_detector import FaceDetector


class CameraPipeline:
    """Manages the complete processing pipeline for a single camera.

    Each instance is fully isolated — no state leakage between cameras.
    Supports optional persistence repositories for events/alerts/ANPR.
    """

    def __init__(self, config: CameraConfig, model_path: str,
                 event_repo=None, alert_repo=None, anpr_repo=None,
                 evidence_capture=None, sync_manager=None):
        self.config = config
        self.camera_id = config.camera_id
        self._model_path = model_path
        self._running = False

        # Create isolated processing pipeline for this camera
        self._pipeline = ProcessingPipeline(
            camera_id=config.camera_id,
            camera_name=config.name,
        )
        self._pipeline.configure(
            video_source=config.source,
            video_source_type=config.source_type,
            model_path=model_path,
        )

        # Wire persistence repositories into PipelineState
        self._pipeline.state._event_repo = event_repo
        self._pipeline.state._alert_repo = alert_repo
        self._pipeline.state._anpr_repo = anpr_repo
        self._pipeline.state._evidence_capture = evidence_capture
        self._pipeline.state._sync_manager = sync_manager

        # Create per-camera engines (fully isolated)
        self._event_engine = EventEngine()
        self._behavior_engine = BehaviorEngine()
        self._context_engine = ContextEngine()
        self._risk_engine = RiskEngine()
        self._plate_detector = PlateDetector()
        self._ocr_engine = OCREngine()
        self._temporal = TemporalStabilizer()
        self._face_detector = FaceDetector()

        # Wire engines into pipeline
        self._pipeline.set_event_engine(self._event_engine)
        self._pipeline.set_behavior_engine(self._behavior_engine)
        self._pipeline.set_context_engine(self._context_engine)
        self._pipeline.set_risk_engine(self._risk_engine)
        self._pipeline.set_anpr(self._plate_detector, self._ocr_engine, self._temporal)
        self._pipeline.set_face_detector(self._face_detector)

    def initialize(self) -> bool:
        """Initialize OCR engine and face detector. Call once after construction."""
        try:
            self._ocr_engine.initialize()
        except Exception as e:
            print("[CAMERA-PIPELINE] OCR init failed for %s: %s" % (self.camera_id, e))

        try:
            self._face_detector.initialize()
        except Exception as e:
            print("[CAMERA-PIPELINE] Face detector init failed for %s: %s" % (self.camera_id, e))

        return True

    def set_zones(self, zones: list):
        """Set zones for intrusion detection on this camera."""
        self._pipeline.set_zones(zones)

    def start(self) -> bool:
        """Start the processing pipeline for this camera."""
        if self._running:
            return True
        self._running = self._pipeline.start()
        return self._running

    def stop(self):
        """Stop the processing pipeline and release resources."""
        if not self._running:
            return
        self._pipeline.stop()
        self._running = False

    def restart(self) -> bool:
        """Stop then start the pipeline cleanly."""
        self.stop()
        return self.start()

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        """Get pipeline status including camera health."""
        status = self._pipeline.state.get_status()
        status["camera_id"] = self.camera_id
        status["camera_name"] = self.config.name
        status["running"] = self._running
        return status

    def get_metadata(self) -> Optional[dict]:
        """Get latest processing metadata (detections, events, ANPR, faces)."""
        return self._pipeline.state.get_latest_metadata()

    def get_frame(self):
        """Get latest annotated frame for MJPEG streaming."""
        return self._pipeline.state.get_latest_frame()
