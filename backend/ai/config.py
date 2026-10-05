"""Centralized configuration for IBVAP AI Service."""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

try:
    import torch
    torch.set_num_threads(1)
except Exception:
    pass

from dataclasses import dataclass, field
from pathlib import Path

# Repository root (project-relative; never a personal absolute path).
# config.py lives at backend/ai/config.py -> parents[2] == repo root.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
MODELS_DIR: Path = REPO_ROOT / "models"

# Deployment environment: set APP_ENV=production on any real deployment.
# Auto-detects Render (which exports RENDER_* vars) as production even if
# APP_ENV was forgotten, so auth bypasses can never silently stay enabled.
APP_ENV: str = os.getenv("APP_ENV", "")


def is_production() -> bool:
    """True when running in a production deployment."""
    env = (APP_ENV or os.getenv("NODE_ENV", "")).lower()
    if env in ("production", "prod"):
        return True
    # Render exports RENDER_SERVICE_ID / RENDER_INSTANCE_ID etc.
    return any(k == "RENDER" or k.startswith("RENDER_") for k in os.environ)


@dataclass
class Settings:
    """AI service configuration — reads from environment with sensible defaults."""

    # Video source
    VIDEO_SOURCE_TYPE: str = os.getenv("VIDEO_SOURCE_TYPE", "video")  # video | rtsp | webcam
    VIDEO_SOURCE: str = os.getenv("VIDEO_SOURCE", "./data/surveillance_test.mp4")

    # RTSP / CCTV ingestion reliability
    RTSP_OPEN_TIMEOUT_SEC: float = float(os.getenv("RTSP_OPEN_TIMEOUT_SEC", "5"))
    RTSP_READ_TIMEOUT_SEC: float = float(os.getenv("RTSP_READ_TIMEOUT_SEC", "3"))
    RTSP_BUFFER_SIZE: int = int(os.getenv("RTSP_BUFFER_SIZE", "1"))  # low-latency
    RECONNECT_INITIAL_DELAY_SEC: float = float(os.getenv("RECONNECT_INITIAL_DELAY_SEC", "1"))
    RECONNECT_MAX_DELAY_SEC: float = float(os.getenv("RECONNECT_MAX_DELAY_SEC", "30"))
    RECONNECT_MAX_ATTEMPTS: int = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "0"))  # 0 = retry forever
    FRAME_TIMEOUT_SECONDS: float = float(os.getenv("FRAME_TIMEOUT_SECONDS", "5"))  # stale threshold

    # YOLO model
    MODEL_PATH: str = os.getenv("MODEL_PATH", str(MODELS_DIR / "vehicle" / "yolov8n.pt"))  # n=nano, s=small, m=medium, l=large, x=xlarge
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.50"))
    IOU_THRESHOLD: float = float(os.getenv("IOU_THRESHOLD", "0.45"))
    IMAGE_SIZE: int = int(os.getenv("IMAGE_SIZE", "640"))
    # Wide frames (e.g. 4K CCTV) need a larger inference size so distant
    # small objects keep enough pixels to clear MIN_TRACKING_CONFIDENCE.
    IMAGE_SIZE_LARGE: int = int(os.getenv("IMAGE_SIZE_LARGE", "960"))
    LARGE_FRAME_WIDTH: int = int(os.getenv("LARGE_FRAME_WIDTH", "1920"))

    # Inference
    INFERENCE_FPS: int = int(os.getenv("INFERENCE_FPS", "10"))
    DEVICE: str = os.getenv("DEVICE", "auto")  # auto | cpu | cuda

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@ibvap.local")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")

    # Service
    AI_SERVICE_HOST: str = os.getenv("AI_SERVICE_HOST", "0.0.0.0")
    AI_SERVICE_PORT: int = int(os.getenv("AI_SERVICE_PORT", "8000"))

    # Camera startup. true (default) preserves current behavior: enabled
    # cameras auto-start during application startup. false registers cameras
    # but leaves them waiting for an explicit start (memory-limited hosts).
    CAMERA_AUTO_START: bool = os.getenv("CAMERA_AUTO_START", "true").lower() == "true"

    # Targeted demo allow-list: the cameras that should actually start and be
    # shown during a demo deployment, as a comma-separated list of camera IDs.
    # Only takes effect when CAMERA_AUTO_START=false — then the listed cameras
    # are started one at a time at boot while every other registered camera is
    # left stopped and hidden from the camera list. Set to an empty string to
    # disable demo mode (CAMERA_AUTO_START=false then starts nothing at all).
    DEMO_CAMERA_IDS: str = os.getenv("DEMO_CAMERA_IDS", "CAM-05,CAM-07")

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent
    DATA_DIR: Path = BASE_DIR / "data"

    # Class labels (COCO 80 classes — subset relevant to border surveillance)
    RELEVANT_CLASSES: list = field(default_factory=lambda: [
        "person", "bicycle", "car", "motorcycle", "bus", "truck",
        "traffic light", "stop sign", "bird", "cat", "dog",
        "backpack", "umbrella", "handbag", "suitcase",
    ])

    # Tracker (ByteTrack via Ultralytics)
    TRACKER_TYPE: str = os.getenv("TRACKER_TYPE", "bytetrack.yaml")
    TRACK_BUFFER: int = int(os.getenv("TRACK_BUFFER", "30"))  # frames to keep lost tracks
    MATCH_THRESHOLD: float = float(os.getenv("MATCH_THRESHOLD", "0.8"))  # appearance match threshold
    MIN_TRACKING_CONFIDENCE: float = float(os.getenv("MIN_TRACKING_CONFIDENCE", "0.45"))  # min det conf for tracking + YOLO inference

    # Detection quality filters (tuned for stock YOLOv8n on surveillance video)
    MIN_BBOX_AREA_PCT: float = float(os.getenv("MIN_BBOX_AREA_PCT", "0.2"))  # min bbox area as % of frame
    PERSON_MAX_ASPECT_RATIO: float = float(os.getenv("PERSON_MAX_ASPECT_RATIO", "4.0"))  # w/h ratio max for person
    PERSON_MIN_ASPECT_RATIO: float = float(os.getenv("PERSON_MIN_ASPECT_RATIO", "0.2"))  # w/h ratio min for person
    TEMPORAL_CONFIRM_FRAMES: int = int(os.getenv("TEMPORAL_CONFIRM_FRAMES", "2"))  # frames required before showing detection
    # Static detection suppression rejects real stationary objects (standing
    # people, queued vehicles) after ~10 observations. Keep machinery for the
    # tree/pole FP use-case but disabled by default — surveillance targets
    # legitimately stand still.
    STATIC_SUPPRESSION_ENABLED: bool = os.getenv("STATIC_SUPPRESSION_ENABLED", "false").lower() == "true"

    # Behavior engine
    LOITERING_THRESHOLD_SECONDS: int = int(os.getenv("LOITERING_THRESHOLD_SECONDS", "30"))
    LOITERING_MOVEMENT_THRESHOLD: float = float(os.getenv("LOITERING_MOVEMENT_THRESHOLD", "0.03"))
    MOVEMENT_THRESHOLD: float = float(os.getenv("MOVEMENT_THRESHOLD", "0.01"))
    NIGHT_START: int = int(os.getenv("NIGHT_START", "22"))
    NIGHT_END: int = int(os.getenv("NIGHT_END", "5"))
    POSITION_HISTORY_MAX: int = int(os.getenv("POSITION_HISTORY_MAX", "200"))
    ORPHAN_RESOLVE_FRAMES: int = int(os.getenv("ORPHAN_RESOLVE_FRAMES", "30"))  # frames before orphaned events auto-resolve

    # Context Engine thresholds
    CONTEXT_DWELL_THRESHOLD_SEC: float = float(os.getenv("CONTEXT_DWELL_THRESHOLD_SEC", "10.0"))
    CONTEXT_LOITERING_THRESHOLD_SEC: float = float(os.getenv("CONTEXT_LOITERING_THRESHOLD_SEC", "30.0"))
    CONTEXT_LOITERING_RADIUS: float = float(os.getenv("CONTEXT_LOITERING_RADIUS", "0.05"))
    CONTEXT_FENCE_PROXIMITY_DISTANCE: float = float(os.getenv("CONTEXT_FENCE_PROXIMITY_DISTANCE", "0.10"))
    CONTEXT_REPEATED_ENTRY_COUNT: int = int(os.getenv("CONTEXT_REPEATED_ENTRY_COUNT", "3"))
    CONTEXT_REPEATED_ENTRY_WINDOW_SEC: float = float(os.getenv("CONTEXT_REPEATED_ENTRY_WINDOW_SEC", "300.0"))
    CONTEXT_DIRECTION_MIN_FRAMES: int = int(os.getenv("CONTEXT_DIRECTION_MIN_FRAMES", "3"))

    # Risk Engine weights
    RISK_WEIGHT_PERSON_INTRUSION: int = int(os.getenv("RISK_WEIGHT_PERSON_INTRUSION", "30"))
    RISK_WEIGHT_VEHICLE_INTRUSION: int = int(os.getenv("RISK_WEIGHT_VEHICLE_INTRUSION", "40"))
    RISK_WEIGHT_ZONE_SEVERITY_CRITICAL: int = int(os.getenv("RISK_WEIGHT_ZONE_SEVERITY_CRITICAL", "25"))
    RISK_WEIGHT_ZONE_SEVERITY_HIGH: int = int(os.getenv("RISK_WEIGHT_ZONE_SEVERITY_HIGH", "15"))
    RISK_WEIGHT_LOITERING: int = int(os.getenv("RISK_WEIGHT_LOITERING", "20"))
    RISK_WEIGHT_DWELL: int = int(os.getenv("RISK_WEIGHT_DWELL", "15"))
    RISK_WEIGHT_FENCE_PROXIMITY: int = int(os.getenv("RISK_WEIGHT_FENCE_PROXIMITY", "15"))
    RISK_WEIGHT_REPEATED_ENTRY: int = int(os.getenv("RISK_WEIGHT_REPEATED_ENTRY", "20"))
    RISK_WEIGHT_NIGHT_ACTIVITY: int = int(os.getenv("RISK_WEIGHT_NIGHT_ACTIVITY", "10"))
    RISK_WEIGHT_HIGH_CONFIDENCE: int = int(os.getenv("RISK_WEIGHT_HIGH_CONFIDENCE", "5"))

    # Risk Engine severity thresholds
    RISK_THRESHOLD_MEDIUM: int = int(os.getenv("RISK_THRESHOLD_MEDIUM", "25"))
    RISK_THRESHOLD_HIGH: int = int(os.getenv("RISK_THRESHOLD_HIGH", "50"))
    RISK_THRESHOLD_CRITICAL: int = int(os.getenv("RISK_THRESHOLD_CRITICAL", "75"))

    # Alert deduplication
    ALERT_ACTIVE_WINDOW_SEC: int = int(os.getenv("ALERT_ACTIVE_WINDOW_SEC", "300"))


    # ANPR / License Plate Recognition
    ANPR_ENABLED: bool = os.getenv("ANPR_ENABLED", "true").lower() == "true"
    # Active license-plate detector: README-based model
    # (Muhammad-Zeerak-Khan Automatic-License-Plate-Recognition-using-YOLOv8,
    # SHA-256 8EC3B254A6C87610F037A90957462CAFA11A9C03224E33A28C6A1D1AC2AC51B0).
    # Rollback/experiment: point this at models/license_plate/best.pt.
    PLATE_MODEL_PATH: str = os.getenv("PLATE_MODEL_PATH", str(MODELS_DIR / "license_plate" / "license_plate_detector.pt"))
    ANPR_OCR_ENGINE: str = os.getenv("ANPR_OCR_ENGINE", "easyocr")  # easyocr | tesseract | none
    ANPR_OCR_GPU: bool = os.getenv("ANPR_OCR_GPU", "false").lower() == "true"  # EasyOCR GPU mode
    ANPR_OCR_PASSES: int = int(os.getenv("ANPR_OCR_PASSES", "2"))  # OCR inference passes per plate (1-2)
    ANPR_FORMAT_VALIDATION: bool = os.getenv("ANPR_FORMAT_VALIDATION", "true").lower() == "true"
    ANPR_CONTEXTUAL_CORRECTION: bool = os.getenv("ANPR_CONTEXTUAL_CORRECTION", "true").lower() == "true"
    ANPR_CONTEXTUAL_MIN_CONFIDENCE: float = float(os.getenv("ANPR_CONTEXTUAL_MIN_CONFIDENCE", "0.5"))

    # Face DETECTION (no recognition / no identity / no biometrics)
    FACE_DETECTION_ENABLED: bool = os.getenv("FACE_DETECTION_ENABLED", "true").lower() == "true"
    FACE_CONFIDENCE_THRESHOLD: float = float(os.getenv("FACE_CONFIDENCE_THRESHOLD", "0.5"))
    FACE_PERSON_OVERLAP_THRESHOLD: float = float(os.getenv("FACE_PERSON_OVERLAP_THRESHOLD", "0.4"))  # containment ratio
    FACE_DETECTION_INTERVAL: int = int(os.getenv("FACE_DETECTION_INTERVAL", "2"))  # run every N frames
    ANPR_MIN_PLATE_CONFIDENCE: float = float(os.getenv("ANPR_MIN_PLATE_CONFIDENCE", "0.4"))
    ANPR_MIN_OCR_CONFIDENCE: float = float(os.getenv("ANPR_MIN_OCR_CONFIDENCE", "0.5"))
    ANPR_OCR_INTERVAL_FRAMES: int = int(os.getenv("ANPR_OCR_INTERVAL_FRAMES", "10"))  # OCR every N frames per track
    ANPR_TEMPORAL_WINDOW: int = int(os.getenv("ANPR_TEMPORAL_WINDOW", "20"))  # max OCR observations to keep
    ANPR_MAX_HISTORY: int = int(os.getenv("ANPR_MAX_HISTORY", "500"))  # max ANPR records in memory
    ANPR_VEHICLE_CLASSES: list = field(default_factory=lambda: ["car", "truck", "bus", "motorcycle", "bicycle"])
    ANPR_PLATE_ASPECT_MIN: float = float(os.getenv("ANPR_PLATE_ASPECT_MIN", "1.5"))  # min width/height ratio
    ANPR_PLATE_ASPECT_MAX: float = float(os.getenv("ANPR_PLATE_ASPECT_MAX", "6.0"))  # max width/height ratio

    # Evidence Management
    EVIDENCE_ENABLED: bool = os.getenv("EVIDENCE_ENABLED", "true").lower() == "true"
    EVIDENCE_RETENTION_DAYS: int = int(os.getenv("EVIDENCE_RETENTION_DAYS", "90"))
    EVIDENCE_DIR: str = os.getenv("EVIDENCE_DIR", "")
    EVIDENCE_SNAPSHOT_QUALITY: int = int(os.getenv("EVIDENCE_SNAPSHOT_QUALITY", "85"))
    # Fraction of the target bbox added on each side when cropping TARGET_CROP
    # evidence (spec: target-centric crop, clamped 0.0-0.5)
    EVIDENCE_TARGET_CROP_MARGIN: float = float(os.getenv("EVIDENCE_TARGET_CROP_MARGIN", "0.2"))
    # Explicit opt-in for non-persistent storage (e.g. Render Free, no disk).
    # Default false: normal production still requires EVIDENCE_DIR to be an
    # absolute path on persistent storage. Set to "true" ONLY for a demo
    # deployment where the container filesystem is wiped on every redeploy,
    # restart or hibernation — all evidence, SQLite rows and other runtime
    # data are lost then.
    EPHEMERAL_STORAGE: bool = os.getenv("EPHEMERAL_STORAGE", "false").lower() == "true"

    # Store-and-Forward Synchronization
    SYNC_ENABLED: bool = os.getenv("SYNC_ENABLED", "true").lower() == "true"
    SYNC_INTERVAL_SEC: int = int(os.getenv("SYNC_INTERVAL_SEC", "10"))
    SYNC_BATCH_SIZE: int = int(os.getenv("SYNC_BATCH_SIZE", "20"))
    SYNC_REQUEST_TIMEOUT_SEC: int = int(os.getenv("SYNC_REQUEST_TIMEOUT_SEC", "15"))
    SYNC_MAX_RETRIES: int = int(os.getenv("SYNC_MAX_RETRIES", "5"))
    SYNC_BACKOFF_BASE_SEC: float = float(os.getenv("SYNC_BACKOFF_BASE_SEC", "2.0"))
    SYNC_BACKOFF_MAX_SEC: float = float(os.getenv("SYNC_BACKOFF_MAX_SEC", "60.0"))
    SYNC_CLEANUP_DAYS: int = int(os.getenv("SYNC_CLEANUP_DAYS", "30"))
    CENTRAL_API_URL: str = os.getenv("CENTRAL_API_URL", "")
    CENTRAL_API_KEY: str = os.getenv("CENTRAL_API_KEY", "")

    # Network Health Monitoring
    NETWORK_HEALTH_ENABLED: bool = os.getenv("NETWORK_HEALTH_ENABLED", "true").lower() == "true"
    NETWORK_HEALTH_INTERVAL_SEC: int = int(os.getenv("NETWORK_HEALTH_INTERVAL_SEC", "10"))
    NETWORK_HEALTH_TIMEOUT_SEC: int = int(os.getenv("NETWORK_HEALTH_TIMEOUT_SEC", "5"))
    NETWORK_DEGRADED_LATENCY_MS: float = float(os.getenv("NETWORK_DEGRADED_LATENCY_MS", "1000"))
    NETWORK_FAILURE_THRESHOLD: int = int(os.getenv("NETWORK_FAILURE_THRESHOLD", "3"))
    NETWORK_RECOVERY_THRESHOLD: int = int(os.getenv("NETWORK_RECOVERY_THRESHOLD", "2"))
    NETWORK_HEALTH_WINDOW_SIZE: int = int(os.getenv("NETWORK_HEALTH_WINDOW_SIZE", "20"))

    # Edge Node Identity (Section 14 — Secure Edge ↔ Central Communication)
    EDGE_NODE_ID: str = os.getenv("EDGE_NODE_ID", "")
    EDGE_NODE_SECRET: str = os.getenv("EDGE_NODE_SECRET", "")
    EDGE_TOKEN_TTL_SECONDS: int = int(os.getenv("EDGE_TOKEN_TTL_SECONDS", "300"))
    EDGE_TOKEN_SECRET: str = os.getenv("EDGE_TOKEN_SECRET", "")
    EDGE_TOKEN_ISSUER: str = os.getenv("EDGE_TOKEN_ISSUER", "ibvap-edge")
    EDGE_LAST_SEEN_UPDATE_SECONDS: int = int(os.getenv("EDGE_LAST_SEEN_UPDATE_SECONDS", "60"))

    # TLS / Transport Security
    CENTRAL_VERIFY_TLS: bool = os.getenv("CENTRAL_VERIFY_TLS", "true").lower() == "true"
    CENTRAL_CA_BUNDLE: str = os.getenv("CENTRAL_CA_BUNDLE", "")

    # Evidence Upload Limits
    MAX_EVIDENCE_UPLOAD_MB: int = int(os.getenv("MAX_EVIDENCE_UPLOAD_MB", "10"))

    # Edge Auth Rate Limiting
    EDGE_AUTH_RATE_LIMIT_MAX: int = int(os.getenv("EDGE_AUTH_RATE_LIMIT_MAX", "5"))
    EDGE_AUTH_RATE_LIMIT_WINDOW_SEC: int = int(os.getenv("EDGE_AUTH_RATE_LIMIT_WINDOW_SEC", "300"))

    # Blockchain / Trust Layer (Pre-Section 15A Retrofit)
    BLOCKCHAIN_ENABLED: bool = os.getenv("BLOCKCHAIN_ENABLED", "false").lower() == "true"
    BLOCKCHAIN_LEDGER_TYPE: str = os.getenv("BLOCKCHAIN_LEDGER_TYPE", "local")  # local | hyperledger
    BLOCKCHAIN_ANCHOR_POLICY: str = os.getenv("BLOCKCHAIN_ANCHOR_POLICY", "high_severity")  # all | high_severity | manual_only
    BLOCKCHAIN_ANCHOR_MIN_SEVERITY: str = os.getenv("BLOCKCHAIN_ANCHOR_MIN_SEVERITY", "HIGH")
    BLOCKCHAIN_LOCAL_LATENCY_MS: float = float(os.getenv("BLOCKCHAIN_LOCAL_LATENCY_MS", "0"))

    def demo_camera_ids(self) -> list:
        """Parse DEMO_CAMERA_IDS into an ordered, de-duplicated list of IDs."""
        ids = []
        for raw in self.DEMO_CAMERA_IDS.split(","):
            cam_id = raw.strip()
            if cam_id and cam_id not in ids:
                ids.append(cam_id)
        return ids

    def get_device(self) -> str:
        """Resolve device string. Auto-detects CUDA."""
        if self.DEVICE != "auto":
            return self.DEVICE
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"


settings = Settings()
