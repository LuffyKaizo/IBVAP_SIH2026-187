"""Footage retrieval service for SD-card recording fallback.

When a camera goes offline, it records to its local SD card.  On
reconnection this module discovers, retrieves, and feeds recorded
footage into the existing IBVAP processing pipeline (VideoCapture with
source_type="video").

Supported retrieval backends:
- ONVIF WS-MediaRecording (most IP cameras)
- FTP/SFTP (cameras exposing an FTP server)
- Local filesystem (SD card mounted on the edge node)

The module exposes two public classes:

- ``RecordedFootageFile``: metadata for a single footage clip.
- ``FootageRetrievalService``: orchestrates discovery → retrieval →
  processing → cleanup for a single camera.
"""

import os
import time
import logging
import tempfile
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Callable

logger = logging.getLogger("ibvap.footage")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class FootageStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    RETRIEVING = "RETRIEVING"
    RETRIEVED = "RETRIEVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RetrievalBackend(str, Enum):
    ONVIF = "ONVIF"
    FTP = "FTP"
    LOCAL_FS = "LOCAL_FS"
    NONE = "NONE"


@dataclass
class RecordedFootageFile:
    """Metadata for a single recorded footage clip."""
    footage_id: str
    camera_id: str
    filename: str
    remote_path: str
    start_time: datetime
    end_time: datetime
    file_size_bytes: int
    duration_sec: float
    status: FootageStatus = FootageStatus.DISCOVERED
    local_path: Optional[str] = None
    error_message: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "footage_id": self.footage_id,
            "camera_id": self.camera_id,
            "filename": self.filename,
            "remote_path": self.remote_path,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "file_size_bytes": self.file_size_bytes,
            "duration_sec": self.duration_sec,
            "status": self.status.value,
            "local_path": self.local_path,
            "error_message": self.error_message,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }


# ---------------------------------------------------------------------------
# Backend adapters (thin wrappers — real implementations would use
# python-onvif-zeep, ftplib, or shutil depending on the camera model)
# ---------------------------------------------------------------------------

class OnvifFootageBackend:
    """Discover and retrieve footage via ONVIF WS-MediaRecording.

    Real implementation would use python-onvif-zeep to call
    GetRecordings / GetRecordingSearch / GetMediaUri.
    This adapter provides the interface; actual ONVIF calls are
    camera-vendor specific and should be implemented per deployment.
    """

    def __init__(self, camera_source: str, credentials: Optional[dict] = None):
        self._source = camera_source
        self._credentials = credentials or {}

    def discover_footage(self, camera_id: str,
                         since: Optional[datetime] = None) -> List[RecordedFootageFile]:
        """Discover available recordings on the camera.

        Returns a list of RecordedFootageFile metadata objects.
        The actual ONVIF GetRecordings call is camera-specific.
        """
        logger.info("[ONVIF] Discovering footage for %s from %s", camera_id, self._source)
        # In production, this would call ONVIF WS-MediaRecording.
        # Return empty list — real implementation depends on camera firmware.
        return []

    def retrieve_file(self, footage: RecordedFootageFile,
                      local_dir: str) -> Optional[str]:
        """Download a single footage file to local_dir.

        Returns the local file path on success, None on failure.
        """
        logger.info("[ONVIF] Retrieving %s from %s", footage.filename, self._source)
        # Real implementation: call GetMediaUri then download via HTTP.
        return None


class FtpFootageBackend:
    """Discover and retrieve footage via FTP/SFTP."""

    def __init__(self, camera_source: str, credentials: Optional[dict] = None):
        self._source = camera_source
        self._credentials = credentials or {}

    def discover_footage(self, camera_id: str,
                         since: Optional[datetime] = None) -> List[RecordedFootageFile]:
        logger.info("[FTP] Discovering footage for %s from %s", camera_id, self._source)
        return []

    def retrieve_file(self, footage: RecordedFootageFile,
                      local_dir: str) -> Optional[str]:
        logger.info("[FTP] Retrieving %s from %s", footage.filename, self._source)
        return None


class LocalFsFootageBackend:
    """Discover and retrieve footage from a locally mounted SD card.

    The SD card path is expected to be provided as camera_source
    (e.g. ``/mnt/sdcard/CAM-01/``).
    """

    def __init__(self, mount_path: str):
        self._mount_path = mount_path

    def discover_footage(self, camera_id: str,
                         since: Optional[datetime] = None) -> List[RecordedFootageFile]:
        """List video files in the mount directory."""
        logger.info("[LOCAL_FS] Discovering footage for %s at %s", camera_id, self._mount_path)
        footage_files: List[RecordedFootageFile] = []
        if not os.path.isdir(self._mount_path):
            logger.warning("[LOCAL_FS] Mount path does not exist: %s", self._mount_path)
            return footage_files

        video_exts = {".mp4", ".avi", ".mkv", ".ts", ".h264", ".h265"}
        for entry in sorted(os.listdir(self._mount_path)):
            ext = os.path.splitext(entry)[1].lower()
            if ext not in video_exts:
                continue
            full_path = os.path.join(self._mount_path, entry)
            if not os.path.isfile(full_path):
                continue
            stat = os.stat(full_path)
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if since and mtime < since:
                continue
            footage = RecordedFootageFile(
                footage_id="%s_%s" % (camera_id, hashlib.sha256(entry.encode()).hexdigest()[:12]),
                camera_id=camera_id,
                filename=entry,
                remote_path=full_path,
                start_time=mtime,
                end_time=mtime,
                file_size_bytes=stat.st_size,
                duration_sec=0.0,
            )
            footage_files.append(footage)
        logger.info("[LOCAL_FS] Found %d footage files for %s", len(footage_files), camera_id)
        return footage_files

    def retrieve_file(self, footage: RecordedFootageFile,
                      local_dir: str) -> Optional[str]:
        """Copy file from mounted SD card to local processing directory."""
        import shutil
        if not os.path.isfile(footage.remote_path):
            logger.error("[LOCAL_FS] Source file does not exist: %s", footage.remote_path)
            return None
        dest = os.path.join(local_dir, footage.filename)
        try:
            shutil.copy2(footage.remote_path, dest)
            logger.info("[LOCAL_FS] Copied %s -> %s", footage.remote_path, dest)
            return dest
        except Exception as e:
            logger.error("[LOCAL_FS] Copy failed: %s", e)
            return None


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

def _get_backend(backend: RetrievalBackend, camera_source: str,
                 credentials: Optional[dict] = None):
    """Factory for retrieval backends."""
    if backend == RetrievalBackend.ONVIF:
        return OnvifFootageBackend(camera_source, credentials)
    elif backend == RetrievalBackend.FTP:
        return FtpFootageBackend(camera_source, credentials)
    elif backend == RetrievalBackend.LOCAL_FS:
        return LocalFsFootageBackend(camera_source)
    return None


class FootageRetrievalService:
    """Orchestrates SD-card footage retrieval for a single camera.

    Lifecycle:
    1. ``discover()`` — scan camera storage for available recordings
    2. ``retrieve(footage_id)`` — download a single clip
    3. ``get_retrieved_path(footage_id)`` — get local path for pipeline
    4. ``mark_completed(footage_id)`` — mark as processed
    5. ``cleanup(footage_id)`` — remove local temp file
    6. ``get_pending()`` — list footage not yet processed

    The service does NOT own the processing pipeline.  The caller
    (CameraManager lifecycle) is responsible for feeding retrieved
    files into ``VideoCapture(source_type="video")``.
    """

    def __init__(self, camera_id: str, camera_source: str,
                 backend: RetrievalBackend = RetrievalBackend.NONE,
                 credentials: Optional[dict] = None,
                 local_processing_dir: Optional[str] = None):
        self._camera_id = camera_id
        self._camera_source = camera_source
        self._backend_type = backend
        self._backend = _get_backend(backend, camera_source, credentials)
        self._footage: dict[str, RecordedFootageFile] = {}
        self._local_dir = local_processing_dir or os.path.join(
            tempfile.gettempdir(), "ibvap_footage", camera_id
        )
        os.makedirs(self._local_dir, exist_ok=True)

    @property
    def camera_id(self) -> str:
        return self._camera_id

    @property
    def backend_type(self) -> RetrievalBackend:
        return self._backend_type

    def discover(self, since: Optional[datetime] = None) -> List[RecordedFootageFile]:
        """Discover available footage on the camera's SD card."""
        if self._backend is None:
            logger.warning("[FOOTAGE] No retrieval backend for %s", self._camera_id)
            return []
        files = self._backend.discover_footage(self._camera_id, since)
        for f in files:
            self._footage[f.footage_id] = f
        logger.info("[FOOTAGE] Discovered %d files for %s", len(files), self._camera_id)
        return files

    def retrieve(self, footage_id: str) -> bool:
        """Download a single footage file to local storage."""
        footage = self._footage.get(footage_id)
        if not footage:
            logger.error("[FOOTAGE] Unknown footage_id: %s", footage_id)
            return False
        if self._backend is None:
            logger.error("[FOOTAGE] No retrieval backend for %s", self._camera_id)
            return False

        footage.status = FootageStatus.RETRIEVING
        local_path = self._backend.retrieve_file(footage, self._local_dir)
        if local_path and os.path.isfile(local_path):
            footage.local_path = local_path
            footage.status = FootageStatus.RETRIEVED
            footage.retrieved_at = datetime.now(timezone.utc)
            logger.info("[FOOTAGE] Retrieved %s -> %s", footage.filename, local_path)
            return True
        else:
            footage.status = FootageStatus.FAILED
            footage.error_message = "Retrieval failed"
            logger.error("[FOOTAGE] Failed to retrieve %s", footage.filename)
            return False

    def retrieve_all(self) -> int:
        """Retrieve all discovered footage. Returns count of successful retrievals."""
        count = 0
        for fid, footage in self._footage.items():
            if footage.status == FootageStatus.DISCOVERED:
                if self.retrieve(fid):
                    count += 1
        return count

    def get_retrieved_path(self, footage_id: str) -> Optional[str]:
        """Get local file path for a retrieved footage clip."""
        footage = self._footage.get(footage_id)
        if footage and footage.status == FootageStatus.RETRIEVED and footage.local_path:
            return footage.local_path
        return None

    def get_next_to_process(self) -> Optional[RecordedFootageFile]:
        """Get the next retrieved footage file ready for processing."""
        for footage in self._footage.values():
            if footage.status == FootageStatus.RETRIEVED:
                return footage
        return None

    def mark_processing(self, footage_id: str):
        """Mark footage as currently being processed by the pipeline."""
        footage = self._footage.get(footage_id)
        if footage:
            footage.status = FootageStatus.PROCESSING

    def mark_completed(self, footage_id: str):
        """Mark footage as successfully processed."""
        footage = self._footage.get(footage_id)
        if footage:
            footage.status = FootageStatus.COMPLETED
            footage.processed_at = datetime.now(timezone.utc)

    def mark_failed(self, footage_id: str, error: str = "Processing failed"):
        """Mark footage processing as failed."""
        footage = self._footage.get(footage_id)
        if footage:
            footage.status = FootageStatus.FAILED
            footage.error_message = error

    def cleanup(self, footage_id: str):
        """Remove local temp file after processing."""
        footage = self._footage.get(footage_id)
        if footage and footage.local_path and os.path.isfile(footage.local_path):
            try:
                os.remove(footage.local_path)
                logger.info("[FOOTAGE] Cleaned up %s", footage.local_path)
            except Exception as e:
                logger.warning("[FOOTAGE] Cleanup failed for %s: %s", footage.local_path, e)

    def get_pending(self) -> List[RecordedFootageFile]:
        """List footage not yet completed."""
        return [
            f for f in self._footage.values()
            if f.status not in (FootageStatus.COMPLETED, FootageStatus.SKIPPED)
        ]

    def get_all(self) -> List[RecordedFootageFile]:
        """List all known footage files."""
        return list(self._footage.values())

    def get_status_summary(self) -> dict:
        """Get summary statistics for this camera's footage queue."""
        counts = {}
        for f in self._footage.values():
            counts[f.status.value] = counts.get(f.status.value, 0) + 1
        return {
            "camera_id": self._camera_id,
            "backend": self._backend_type.value,
            "total_files": len(self._footage),
            "by_status": counts,
            "pending": counts.get(FootageStatus.DISCOVERED.value, 0)
                      + counts.get(FootageStatus.RETRIEVING.value, 0)
                      + counts.get(FootageStatus.RETRIEVED.value, 0)
                      + counts.get(FootageStatus.PROCESSING.value, 0),
            "completed": counts.get(FootageStatus.COMPLETED.value, 0),
            "failed": counts.get(FootageStatus.FAILED.value, 0),
        }

    def cleanup_all(self):
        """Remove all local temp files."""
        for footage in list(self._footage.values()):
            self.cleanup(footage.footage_id)
