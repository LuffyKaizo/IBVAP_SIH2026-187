"""Evidence storage abstraction.

Provides a pluggable storage backend for evidence files (snapshots, clips).
LocalFileEvidenceStore writes to the local filesystem under ai/data/evidence/.
A future implementation could support S3/object storage without changing the capture logic.
"""

import os
import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("ibvap.evidence")


class EvidenceStore(ABC):
    """Abstract base class for evidence file storage."""

    @abstractmethod
    def save(self, data: bytes, path: str) -> str:
        """Save evidence bytes to storage. Returns the stored file path."""

    @abstractmethod
    def load(self, path: str) -> bytes:
        """Load evidence bytes from storage."""

    @abstractmethod
    def delete(self, path: str) -> bool:
        """Delete evidence file. Returns True if deleted."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if evidence file exists."""

    @abstractmethod
    def size(self, path: str) -> int:
        """Return file size in bytes."""


class LocalFileEvidenceStore(EvidenceStore):
    """Local filesystem evidence storage.

    Files are stored under:
        {base_dir}/{camera_id}/{event_id}/{evidence_id}.jpg

    The base_dir defaults to ai/data/evidence/ which is gitignored.
    """

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path(__file__).resolve().parent.parent / "data" / "evidence")
        self._base_dir = base_dir
        os.makedirs(self._base_dir, exist_ok=True)

    def _full_path(self, rel_path: str) -> str:
        return os.path.join(self._base_dir, rel_path)

    def save(self, data: bytes, path: str) -> str:
        full = self._full_path(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
        logger.debug("[EVIDENCE] Saved %d bytes to %s", len(data), path)
        return path

    def load(self, path: str) -> bytes:
        full = self._full_path(path)
        with open(full, "rb") as f:
            return f.read()

    def delete(self, path: str) -> bool:
        full = self._full_path(path)
        if os.path.exists(full):
            os.remove(full)
            logger.debug("[EVIDENCE] Deleted %s", path)
            return True
        return False

    def exists(self, path: str) -> bool:
        return os.path.exists(self._full_path(path))

    def size(self, path: str) -> int:
        full = self._full_path(path)
        if os.path.exists(full):
            return os.path.getsize(full)
        return 0
