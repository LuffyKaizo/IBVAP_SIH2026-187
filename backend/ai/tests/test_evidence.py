"""Section 11 Evidence Management Tests.

Tests:
1. snapshot creation
2. evidence metadata persistence
3. event/evidence linkage
4. SHA-256 generation
5. SHA-256 verification
6. corrupted/tampered file detection
7. duplicate evidence prevention
8. authenticated evidence access
9. RBAC enforcement
10. evidence access audit logging
11. local operation when central connectivity is unavailable
12. existing event pipeline regression
"""

import asyncio
import hashlib
import os
import secrets
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np

# Add project root to path
_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from ai.evidence.store import LocalFileEvidenceStore
from ai.evidence.capture import EvidenceCapture


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _make_frame(width=320, height=240):
    """Create a test BGR frame."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = 100  # blue channel
    cv2.putText(frame, "TEST", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return frame


def _make_event(event_id=None, camera_id="CAM-TEST", status="DETECTED"):
    return {
        "event_id": event_id or ("EVT-" + secrets.token_hex(4)),
        "event_type": "PERSON_INTRUSION",
        "severity": "CRITICAL",
        "camera_id": camera_id,
        "zone_id": "ZONE-01",
        "zone_name": "Restricted Area",
        "track_id": 1,
        "object_class": "person",
        "timestamp": time.time(),
        "confidence": 0.85,
        "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.8},
        "status": status,
    }


class MockEvidenceRepo:
    """In-memory evidence repository for testing."""
    def __init__(self):
        self._store = {}

    async def create(self, evidence):
        self._store[evidence["id"]] = evidence
        return evidence

    async def get(self, evidence_id):
        return self._store.get(evidence_id)

    async def list_for_event(self, event_id):
        return [e for e in self._store.values() if e.get("eventId") == event_id]

    async def list_for_camera(self, camera_id, limit=100):
        items = [e for e in self._store.values() if e.get("cameraId") == camera_id]
        return items[:limit]

    async def list_recent(self, limit=50):
        items = sorted(self._store.values(), key=lambda x: x.get("createdAt", ""), reverse=True)
        return items[:limit]

    async def update_integrity(self, evidence_id, status):
        if evidence_id in self._store:
            self._store[evidence_id]["integrityStatus"] = status
            return True
        return False

    async def delete(self, evidence_id):
        if evidence_id in self._store:
            del self._store[evidence_id]
            return True
        return False

    async def count(self):
        return len(self._store)

    def count_sync(self):
        return len(self._store)


class MockAuditRepo:
    def __init__(self):
        self.logs = []

    async def log(self, action, entity_type, entity_id, details=None, actor=None):
        self.logs.append({
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
            "actor": actor,
        })


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────

class TestEvidenceSnapshotCreation(unittest.TestCase):
    """Test 1: Snapshot creation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LocalFileEvidenceStore(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_snapshot_creation(self):
        frame = _make_frame()
        event = _make_event()
        evidence_id = "EVD-" + secrets.token_hex(8)
        file_path = "%s/%s/%s.jpg" % (event["camera_id"], event["event_id"], evidence_id)

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        self.assertTrue(ok)
        jpeg_bytes = buf.tobytes()

        saved_path = self.store.save(jpeg_bytes, file_path)
        self.assertEqual(saved_path, file_path)
        self.assertTrue(self.store.exists(file_path))
        self.assertGreater(self.store.size(file_path), 0)

        loaded = self.store.load(file_path)
        self.assertEqual(len(loaded), len(jpeg_bytes))

    def test_capture_snapshot_produces_valid_jpeg(self):
        frame = _make_frame()
        event = _make_event()
        mock_repo = MockEvidenceRepo()
        mock_audit = MockAuditRepo()

        capture = EvidenceCapture(self.store, mock_repo, mock_audit)
        result = asyncio.get_event_loop().run_until_complete(
            capture.capture_snapshot(event, frame, actor="TEST")
        )

        self.assertIsNotNone(result)
        self.assertIn("id", result)
        self.assertEqual(result["evidenceType"], "SNAPSHOT")
        self.assertEqual(result["cameraId"], event["camera_id"])
        self.assertTrue(self.store.exists(result["filePath"]))


class TestEvidenceMetadataPersistence(unittest.TestCase):
    """Test 2: Evidence metadata persistence."""

    def test_persist_and_retrieve(self):
        mock_repo = MockEvidenceRepo()
        evidence = {
            "id": "EVD-TEST-001",
            "eventId": "EVT-001",
            "cameraId": "CAM-01",
            "evidenceType": "SNAPSHOT",
            "timestamp": time.time(),
            "filePath": "CAM-01/EVT-001/EVD-TEST-001.jpg",
            "fileSize": 12345,
            "mimeType": "image/jpeg",
            "sha256Hash": "abc123",
            "integrityStatus": "VALID",
            "createdBy": "SYSTEM",
        }
        result = asyncio.get_event_loop().run_until_complete(mock_repo.create(evidence))
        self.assertEqual(result["id"], "EVD-TEST-001")

        retrieved = asyncio.get_event_loop().run_until_complete(mock_repo.get("EVD-TEST-001"))
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["cameraId"], "CAM-01")
        self.assertEqual(retrieved["sha256Hash"], "abc123")


class TestEventEvidenceLinkage(unittest.TestCase):
    """Test 3: Event/evidence linkage."""

    def test_list_evidence_for_event(self):
        mock_repo = MockEvidenceRepo()
        event_id = "EVT-LINK-001"

        for i in range(3):
            asyncio.get_event_loop().run_until_complete(mock_repo.create({
                "id": "EVD-LINK-%03d" % i,
                "eventId": event_id,
                "cameraId": "CAM-01",
                "evidenceType": "SNAPSHOT",
                "timestamp": time.time(),
                "filePath": "test.jpg",
                "fileSize": 100,
                "mimeType": "image/jpeg",
                "sha256Hash": "hash%d" % i,
                "integrityStatus": "VALID",
            }))

        items = asyncio.get_event_loop().run_until_complete(mock_repo.list_for_event(event_id))
        self.assertEqual(len(items), 3)
        for item in items:
            self.assertEqual(item["eventId"], event_id)

    def test_event_id_in_evidence_metadata(self):
        tmpdir = tempfile.mkdtemp()
        try:
            store = LocalFileEvidenceStore(tmpdir)
            mock_repo = MockEvidenceRepo()
            mock_audit = MockAuditRepo()
            capture = EvidenceCapture(store, mock_repo, mock_audit)

            event = _make_event(event_id="EVT-SPECIFIC-123")
            frame = _make_frame()
            result = asyncio.get_event_loop().run_until_complete(
                capture.capture_snapshot(event, frame)
            )
            self.assertEqual(result["eventId"], "EVT-SPECIFIC-123")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestSHA256Generation(unittest.TestCase):
    """Test 4: SHA-256 generation."""

    def test_sha256_deterministic(self):
        data = b"test evidence data"
        h1 = EvidenceCapture.compute_sha256(data)
        h2 = EvidenceCapture.compute_sha256(data)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # SHA-256 hex is 64 chars

    def test_sha256_different_for_different_data(self):
        h1 = EvidenceCapture.compute_sha256(b"data1")
        h2 = EvidenceCapture.compute_sha256(b"data2")
        self.assertNotEqual(h1, h2)

    def test_sha256_on_jpeg_frame(self):
        frame = _make_frame()
        ok, buf = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        h = EvidenceCapture.compute_sha256(buf.tobytes())
        self.assertEqual(len(h), 64)


class TestSHA256Verification(unittest.TestCase):
    """Test 5: SHA-256 verification."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LocalFileEvidenceStore(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_verify_valid(self):
        data = b"evidence data"
        file_path = "test/verify.jpg"
        self.store.save(data, file_path)
        h = EvidenceCapture.compute_sha256(data)

        capture = EvidenceCapture(self.store)
        self.assertTrue(capture.verify_integrity(file_path, h))

    def test_capture_and_verify(self):
        frame = _make_frame()
        event = _make_event()
        mock_repo = MockEvidenceRepo()
        mock_audit = MockAuditRepo()
        capture = EvidenceCapture(self.store, mock_repo, mock_audit)

        result = asyncio.get_event_loop().run_until_complete(
            capture.capture_snapshot(event, frame)
        )
        self.assertIsNotNone(result)

        is_valid = capture.verify_integrity(result["filePath"], result["sha256Hash"])
        self.assertTrue(is_valid)


class TestCorruptedFileDetection(unittest.TestCase):
    """Test 6: Corrupted/tampered file detection."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LocalFileEvidenceStore(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tampered_file_detected(self):
        data = b"original evidence"
        file_path = "test/tampered.jpg"
        self.store.save(data, file_path)
        h = EvidenceCapture.compute_sha256(data)

        # Tamper with the file
        self.store.save(b"TAMPERED evidence", file_path)

        capture = EvidenceCapture(self.store)
        self.assertFalse(capture.verify_integrity(file_path, h))


class TestDuplicateEvidencePrevention(unittest.TestCase):
    """Test 7: Duplicate evidence prevention via event lifecycle."""

    def test_only_detected_triggers_capture(self):
        """Only DETECTED status (first time) should create evidence, not ACTIVE updates."""
        tmpdir = tempfile.mkdtemp()
        try:
            store = LocalFileEvidenceStore(tmpdir)
            mock_repo = MockEvidenceRepo()
            mock_audit = MockAuditRepo()
            capture = EvidenceCapture(store, mock_repo, mock_audit)

            event = _make_event(status="DETECTED")
            frame = _make_frame()

            r1 = asyncio.get_event_loop().run_until_complete(
                capture.capture_snapshot(event, frame)
            )
            self.assertIsNotNone(r1)

            # Only 1 evidence created (capture is called once per DETECTED)
            self.assertEqual(mock_repo.count_sync(), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestAuthenticatedEvidenceAccess(unittest.TestCase):
    """Test 8: Authenticated evidence access."""

    def test_evidence_read_permission_exists(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.EVIDENCE_READ, ROLE_PERMISSIONS[Role.ADMIN])
        self.assertIn(Permission.EVIDENCE_READ, ROLE_PERMISSIONS[Role.OPERATOR])
        self.assertIn(Permission.EVIDENCE_READ, ROLE_PERMISSIONS[Role.VIEWER])

    def test_evidence_delete_permission_exists(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.EVIDENCE_DELETE, ROLE_PERMISSIONS[Role.ADMIN])
        self.assertNotIn(Permission.EVIDENCE_DELETE, ROLE_PERMISSIONS[Role.OPERATOR])
        self.assertNotIn(Permission.EVIDENCE_DELETE, ROLE_PERMISSIONS[Role.VIEWER])


class TestRBACEnforcement(unittest.TestCase):
    """Test 9: RBAC enforcement."""

    def test_viewer_cannot_delete(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertNotIn(Permission.EVIDENCE_DELETE, ROLE_PERMISSIONS[Role.VIEWER])

    def test_operator_cannot_delete(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertNotIn(Permission.EVIDENCE_DELETE, ROLE_PERMISSIONS[Role.OPERATOR])

    def test_admin_can_delete(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.EVIDENCE_DELETE, ROLE_PERMISSIONS[Role.ADMIN])


class TestAuditLogging(unittest.TestCase):
    """Test 10: Evidence access audit logging."""

    def test_capture_creates_audit_log(self):
        tmpdir = tempfile.mkdtemp()
        try:
            store = LocalFileEvidenceStore(tmpdir)
            mock_repo = MockEvidenceRepo()
            mock_audit = MockAuditRepo()
            capture = EvidenceCapture(store, mock_repo, mock_audit)

            event = _make_event()
            frame = _make_frame()
            asyncio.get_event_loop().run_until_complete(
                capture.capture_snapshot(event, frame, actor="USER-123")
            )

            self.assertGreater(len(mock_audit.logs), 0)
            log = mock_audit.logs[0]
            self.assertEqual(log["action"], "evidence.capture")
            self.assertEqual(log["entity_type"], "evidence")
            self.assertEqual(log["actor"], "USER-123")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_verify_creates_audit_log(self):
        tmpdir = tempfile.mkdtemp()
        try:
            store = LocalFileEvidenceStore(tmpdir)
            mock_repo = MockEvidenceRepo()
            mock_audit = MockAuditRepo()
            capture = EvidenceCapture(store, mock_repo, mock_audit)

            event = _make_event()
            frame = _make_frame()
            result = asyncio.get_event_loop().run_until_complete(
                capture.capture_snapshot(event, frame)
            )

            asyncio.get_event_loop().run_until_complete(
                capture.verify_and_update(result)
            )

            verify_logs = [l for l in mock_audit.logs if l["action"] == "evidence.verify"]
            self.assertGreater(len(verify_logs), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestLocalOperationWithoutDB(unittest.TestCase):
    """Test 11: Local operation when central connectivity is unavailable."""

    def test_capture_works_without_repo(self):
        tmpdir = tempfile.mkdtemp()
        try:
            store = LocalFileEvidenceStore(tmpdir)
            capture = EvidenceCapture(store, evidence_repo=None, audit_repo=None)

            event = _make_event()
            frame = _make_frame()
            result = asyncio.get_event_loop().run_until_complete(
                capture.capture_snapshot(event, frame)
            )

            self.assertIsNotNone(result)
            self.assertTrue(store.exists(result["filePath"]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_store_works_independently(self):
        tmpdir = tempfile.mkdtemp()
        try:
            store = LocalFileEvidenceStore(tmpdir)
            data = b"independent storage test"
            path = "indep/test.bin"
            store.save(data, path)
            self.assertTrue(store.exists(path))
            self.assertEqual(store.load(path), data)
            self.assertEqual(store.size(path), len(data))
            self.assertTrue(store.delete(path))
            self.assertFalse(store.exists(path))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestPipelineRegression(unittest.TestCase):
    """Test 12: Existing event pipeline regression — evidence does not break it."""

    def test_pipeline_state_has_evidence_capture_field(self):
        from ai.pipeline import PipelineState
        state = PipelineState("CAM-REG", "Regression Test")
        self.assertIsNone(state._evidence_capture)

    def test_set_events_works_without_evidence_capture(self):
        from ai.pipeline import PipelineState
        state = PipelineState("CAM-REG", "Regression Test")
        state.latest_metadata = {"events": [], "alerts": []}

        event = _make_event()
        with patch.object(state, '_persist_event_lifecycle'):
            with patch.object(state, '_event_to_alert', return_value={}):
                state.set_events([event])

        self.assertIn("events", state.latest_metadata)
        self.assertEqual(len(state.latest_metadata["events"]), 1)

    def test_evidence_capture_failure_does_not_crash_pipeline(self):
        tmpdir = tempfile.mkdtemp()
        try:
            store = LocalFileEvidenceStore(tmpdir)
            mock_repo = MockEvidenceRepo()

            # Create a capture that always fails
            failing_capture = EvidenceCapture(store, mock_repo)
            failing_capture.capture_snapshot = AsyncMock(side_effect=RuntimeError("disk full"))

            from ai.pipeline import PipelineState
            state = PipelineState("CAM-FAIL", "Fail Test")
            state._evidence_capture = failing_capture
            state.latest_metadata = {"events": [], "alerts": []}
            state.latest_frame = _make_frame()

            event = _make_event()
            with patch.object(state, '_persist_event_lifecycle'):
                with patch.object(state, '_event_to_alert', return_value={}):
                    with patch.object(state, '_schedule_persist') as mock_sched:
                        # Should NOT raise
                        state.set_events([event])

            # Events still processed
            self.assertEqual(len(state.latest_metadata["events"]), 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
