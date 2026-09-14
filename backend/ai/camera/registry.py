"""In-memory camera registry for IBVAP.

Provides a clean abstraction that can later be replaced by a PostgreSQL
repository without changing the public API.
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone

from ai.camera.config import CameraConfig


class CameraRegistry:
    """In-memory camera registry.

    Stores CameraConfig objects keyed by camera_id. Designed so that the
    internal dict can be swapped for database queries in a future section
    without changing the public interface.
    """

    def __init__(self):
        self._cameras: Dict[str, CameraConfig] = {}

    def add(self, config: CameraConfig) -> CameraConfig:
        """Register a new camera. Raises ValueError on duplicate camera_id."""
        if config.camera_id in self._cameras:
            raise ValueError("Camera already registered: %s" % config.camera_id)
        self._cameras[config.camera_id] = config
        return config

    def get(self, camera_id: str) -> Optional[CameraConfig]:
        """Get a camera by ID. Returns None if not found."""
        return self._cameras.get(camera_id)

    def list_all(self) -> List[CameraConfig]:
        """Return all registered cameras."""
        return list(self._cameras.values())

    def list_enabled(self) -> List[CameraConfig]:
        """Return only enabled cameras."""
        return [c for c in self._cameras.values() if c.enabled]

    def update(self, camera_id: str, **fields) -> Optional[CameraConfig]:
        """Update camera fields. Returns updated config or None if not found."""
        config = self._cameras.get(camera_id)
        if config is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        for key, value in fields.items():
            if hasattr(config, key) and key not in ("camera_id", "created_at"):
                setattr(config, key, value)
        config.updated_at = now
        return config

    def remove(self, camera_id: str) -> bool:
        """Remove a camera. Returns True if removed, False if not found."""
        if camera_id in self._cameras:
            del self._cameras[camera_id]
            return True
        return False

    def exists(self, camera_id: str) -> bool:
        """Check if a camera is registered."""
        return camera_id in self._cameras

    def count(self) -> int:
        """Return total number of registered cameras."""
        return len(self._cameras)

    def count_enabled(self) -> int:
        """Return number of enabled cameras."""
        return sum(1 for c in self._cameras.values() if c.enabled)
