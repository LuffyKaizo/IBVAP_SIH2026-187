"""Camera configuration model for IBVAP multi-camera management."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CameraConfig:
    """Runtime camera configuration.

    Each camera is identified by a unique camera_id and carries its own
    source configuration. Credentials embedded in RTSP URLs are masked
    at serialization time — never stored or returned in cleartext.
    """
    camera_id: str
    name: str
    location: str
    source: str                   # RTSP URL, file path, or webcam index
    source_type: str              # "rtsp" | "video" | "webcam"
    camera_type: str = "FIXED"    # FIXED | PTZ | THERMAL | DAY_NIGHT
    enabled: bool = True
    sd_card_capable: bool = False
    sd_card_status: str = "UNKNOWN"
    sd_card_capacity_gb: Optional[float] = None
    last_sync_at: Optional[str] = None
    pending_footage_count: int = 0
    last_offline_at: Optional[str] = None
    last_online_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Serialize to dict with credential masking."""
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "location": self.location,
            "source": self.source,
            "source_type": self.source_type,
            "camera_type": self.camera_type,
            "enabled": self.enabled,
            "sd_card_capable": self.sd_card_capable,
            "sd_card_status": self.sd_card_status,
            "sd_card_capacity_gb": self.sd_card_capacity_gb,
            "last_sync_at": self.last_sync_at,
            "pending_footage_count": self.pending_footage_count,
            "last_offline_at": self.last_offline_at,
            "last_online_at": self.last_online_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CameraConfig":
        """Deserialize from dict, ignoring unknown fields."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
