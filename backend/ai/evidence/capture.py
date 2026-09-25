"""Evidence capture service — event-driven snapshot capture with SHA-256 integrity.

Captures a JPEG snapshot when a new event is DETECTED, computes SHA-256,
stores the file, and persists metadata to the database.

Fault-isolated: capture failures never crash the AI pipeline.
"""

import hashlib
import io
import logging
import secrets
import time
from typing import Optional

import cv2
import numpy as np

from ai.evidence.store import EvidenceStore

logger = logging.getLogger("ibvap.evidence")


class EvidenceCapture:
    """Captures and stores evidence snapshots linked to security events.

    Usage:
        capture = EvidenceCapture(store, evidence_repo, audit_repo)
        await capture.capture_snapshot(event_dict, frame, actor="SYSTEM")
    """

    def __init__(
        self,
        store: EvidenceStore,
        evidence_repo=None,
        audit_repo=None,
        snapshot_quality: int = 85,
        blockchain_service=None,
    ):
        self._store = store
        self._evidence_repo = evidence_repo
        self._audit_repo = audit_repo
        self._snapshot_quality = snapshot_quality
        self._blockchain_service = blockchain_service

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def verify_integrity(self, file_path: str, expected_hash: str) -> bool:
        """Verify file integrity by recomputing SHA-256."""
        try:
            data = self._store.load(file_path)
            actual_hash = self.compute_sha256(data)
            return actual_hash == expected_hash
        except Exception as e:
            logger.warning("[EVIDENCE] Integrity check failed: %s", e)
            return False

    async def capture_snapshot(
        self,
        event_dict: dict,
        frame: np.ndarray,
        actor: str = "SYSTEM",
        jpeg_quality: int = None,
        evidence_type: str = "SNAPSHOT",
        metadata_extra: Optional[dict] = None,
    ) -> Optional[dict]:
        """Capture a JPEG image for an event and persist metadata.

        Args:
            event_dict: Event dict with event_id, camera_id, event_type, etc.
            frame: Raw BGR numpy frame (or a pre-cropped target image).
            actor: Identity of who triggered this (user_id or "SYSTEM").
            jpeg_quality: Override JPEG quality (default: self._snapshot_quality).
            evidence_type: "SNAPSHOT" (full scene) or "TARGET_CROP"
                (target-centric crop with annotations baked in).
            metadata_extra: Optional extra keys merged into evidence metadata.

        Returns:
            Evidence metadata dict on success, None on failure.
        """
        try:
            if frame is None or not isinstance(frame, np.ndarray):
                logger.warning("[EVIDENCE] No frame to capture")
                return None

            event_id = event_dict.get("event_id", "unknown")
            camera_id = event_dict.get("camera_id", "unknown")

            # Generate evidence ID
            evidence_id = "EVD-" + secrets.token_hex(8)

            # Encode frame as JPEG
            quality = jpeg_quality or self._snapshot_quality
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ok:
                logger.warning("[EVIDENCE] JPEG encode failed for %s", event_id)
                return None

            jpeg_bytes = buf.tobytes()

            # Compute SHA-256 hash
            sha256_hash = self.compute_sha256(jpeg_bytes)

            # Build storage path: {camera_id}/{event_id}/{evidence_id}.jpg
            file_path = "%s/%s/%s.jpg" % (camera_id, event_id, evidence_id)

            # Save to local store
            self._store.save(jpeg_bytes, file_path)
            file_size = len(jpeg_bytes)

            # Build evidence metadata
            metadata = {
                "event_type": event_dict.get("event_type"),
                "severity": event_dict.get("severity"),
                "track_id": event_dict.get("track_id"),
                "object_class": event_dict.get("object_class"),
                "confidence": event_dict.get("confidence"),
                "bbox": event_dict.get("bbox"),
                "zone_name": event_dict.get("zone_name"),
            }
            if metadata_extra:
                metadata.update({k: v for k, v in metadata_extra.items() if v is not None})
            evidence = {
                "id": evidence_id,
                "eventId": event_id,
                "alertId": event_dict.get("alert_id"),
                "cameraId": camera_id,
                "evidenceType": evidence_type,
                "timestamp": event_dict.get("timestamp", time.time()),
                "filePath": file_path,
                "fileSize": file_size,
                "mimeType": "image/jpeg",
                "sha256Hash": sha256_hash,
                "integrityStatus": "VALID",
                "metadata": metadata,
                "createdBy": actor,
            }

            # Persist to database
            if self._evidence_repo:
                result = await self._evidence_repo.create(evidence)
                if result:
                    evidence = result

            # Audit log
            if self._audit_repo:
                await self._audit_repo.log(
                    action="evidence.capture",
                    entity_type="evidence",
                    entity_id=evidence_id,
                    details={"event_id": event_id, "camera_id": camera_id, "type": evidence_type},
                    actor=actor,
                )

            logger.info(
                "[EVIDENCE] Captured %s (%s) for %s (%d bytes, sha256=%s...)",
                evidence_id, evidence_type, event_id, file_size, sha256_hash[:12],
            )

            # Blockchain anchoring (fire-and-forget, non-blocking)
            if self._blockchain_service and self._blockchain_service.enabled:
                try:
                    await self._blockchain_service.maybe_anchor(evidence)
                except Exception as bc_err:
                    logger.warning("[EVIDENCE] Blockchain anchor request failed: %s", bc_err)

            return evidence

        except Exception as e:
            # Fault-isolated: never crash the pipeline
            logger.warning("[EVIDENCE] Capture failed: %s", e)
            return None

    async def delete_evidence(self, evidence_dict: dict) -> bool:
        """Delete evidence file and database record."""
        try:
            file_path = evidence_dict.get("filePath", "")
            evidence_id = evidence_dict.get("id", "")

            # Delete file from store
            if file_path:
                self._store.delete(file_path)

            # Delete from database
            if self._evidence_repo and evidence_id:
                await self._evidence_repo.delete(evidence_id)

            # Audit log
            if self._audit_repo and evidence_id:
                await self._audit_repo.log(
                    action="evidence.delete",
                    entity_type="evidence",
                    entity_id=evidence_id,
                    details={"file_path": file_path},
                )

            return True
        except Exception as e:
            logger.warning("[EVIDENCE] Delete failed: %s", e)
            return False

    async def verify_and_update(self, evidence_dict: dict) -> bool:
        """Verify integrity of stored evidence and update status in DB.

        Performs: file hash -> DB hash -> blockchain hash verification.
        """
        try:
            file_path = evidence_dict.get("filePath", "")
            expected_hash = evidence_dict.get("sha256Hash", "")
            evidence_id = evidence_dict.get("id", "")

            if not file_path or not expected_hash:
                return False

            is_valid = self.verify_integrity(file_path, expected_hash)
            new_status = "VALID" if is_valid else "INTEGRITY_FAILURE"

            # Blockchain verification (if available)
            blockchain_status = None
            if self._blockchain_service and self._blockchain_service.enabled:
                try:
                    bc_result = await self._blockchain_service.verify_evidence(evidence_dict)
                    blockchain_status = bc_result.status
                    if is_valid and not bc_result.verified:
                        # File matches DB but blockchain says different — possible tampering
                        new_status = "BLOCKCHAIN_MISMATCH"
                except Exception:
                    blockchain_status = "BLOCKCHAIN_UNAVAILABLE"

            if self._evidence_repo and evidence_id:
                await self._evidence_repo.update_integrity(evidence_id, new_status)

            if self._audit_repo and evidence_id:
                await self._audit_repo.log(
                    action="evidence.verify",
                    entity_type="evidence",
                    entity_id=evidence_id,
                    details={"status": new_status, "blockchain_status": blockchain_status},
                )

            return is_valid
        except Exception as e:
            logger.warning("[EVIDENCE] Verify failed: %s", e)
            return False
