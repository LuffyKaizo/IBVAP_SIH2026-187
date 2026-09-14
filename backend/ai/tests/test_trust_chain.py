"""Phase 5 Trust Chain Integration Tests.

End-to-end validation of the evidence → SHA-256 → PostgreSQL → blockchain →
verification → tamper detection → restoration pipeline.

Uses mock repositories for deterministic testing without requiring a live database.
Tests the ACTUAL EvidenceCapture, BlockchainService, and LocalLedger implementations
with real JPEG encoding, real SHA-256 computation, and real file I/O.
"""
import asyncio
import hashlib
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import cv2
import numpy as np

from ai.evidence.capture import EvidenceCapture
from ai.evidence.store import LocalFileEvidenceStore
from ai.blockchain.service import BlockchainService
from ai.blockchain.local_ledger import LocalLedger
from ai.blockchain.models import VERIFIED, EVIDENCE_TAMPERED, BLOCKCHAIN_HASH_MISMATCH


def _run(coro):
    """Run async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Mock Repositories ────────────────────────────────────────────────────

class MockEvidenceRepo:
    def __init__(self):
        self._evidence = {}

    async def get(self, evidence_id):
        return self._evidence.get(evidence_id)

    async def create(self, evidence):
        eid = evidence.get("id", "EVD-test")
        self._evidence[eid] = evidence
        return evidence

    async def update_integrity(self, evidence_id, status):
        if evidence_id in self._evidence:
            self._evidence[evidence_id]["integrityStatus"] = status
            return True
        return False

    async def delete(self, evidence_id):
        if evidence_id in self._evidence:
            del self._evidence[evidence_id]
            return True
        return False

    async def list_for_event(self, event_id):
        return [e for e in self._evidence.values() if e.get("eventId") == event_id]

    async def list_for_camera(self, camera_id, limit=100):
        return [e for e in self._evidence.values() if e.get("cameraId") == camera_id][:limit]

    async def list_recent(self, limit=50):
        return list(self._evidence.values())[:limit]

    async def count(self):
        return len(self._evidence)


class MockAnchorRepo:
    def __init__(self):
        self._anchors = {}

    async def create(self, anchor_id, evidence_id, sha256_hash, record_hash, tx_hash,
                     block_number=0, previous_hash="", status="PENDING", confirmation_time_ms=0.0):
        self._anchors[anchor_id] = {
            "anchorId": anchor_id,
            "evidenceId": evidence_id,
            "sha256Hash": sha256_hash,
            "recordHash": record_hash,
            "txHash": tx_hash,
            "blockNumber": block_number,
            "previousHash": previous_hash,
            "status": status,
            "confirmationTimeMs": confirmation_time_ms,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "confirmedAt": datetime.now(timezone.utc).isoformat() if status == "CONFIRMED" else None,
        }
        return self._anchors[anchor_id]

    async def get_by_id(self, anchor_id):
        return self._anchors.get(anchor_id)

    async def get_by_evidence(self, evidence_id):
        for a in self._anchors.values():
            if a["evidenceId"] == evidence_id and a["status"] in ("PENDING", "CONFIRMED"):
                return a
        return None

    async def update_status(self, anchor_id, status, block_number=None, confirmation_time_ms=None):
        if anchor_id not in self._anchors:
            return False
        a = self._anchors[anchor_id]
        a["status"] = status
        if status == "CONFIRMED":
            a["confirmedAt"] = datetime.now(timezone.utc).isoformat()
        if block_number is not None:
            a["blockNumber"] = block_number
        if confirmation_time_ms is not None:
            a["confirmationTimeMs"] = confirmation_time_ms
        return True

    async def list_pending(self, limit=20):
        items = [a for a in self._anchors.values() if a["status"] == "PENDING"]
        return sorted(items, key=lambda x: x["createdAt"])[:limit]

    async def count_by_status(self):
        counts = {}
        for a in self._anchors.values():
            s = a["status"]
            counts[s] = counts.get(s, 0) + 1
        return counts

    async def list_recent(self, limit=10):
        items = sorted(self._anchors.values(), key=lambda x: x["createdAt"], reverse=True)
        return items[:limit]


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


# ── Trust Chain Integration Tests ────────────────────────────────────────

class TestTrustChainEndToEnd(unittest.TestCase):
    """Full trust chain: event → evidence → SHA-256 → DB → blockchain → verify → tamper → detect → restore."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ibvap_trust_test_")
        self.store = LocalFileEvidenceStore(base_dir=self.test_dir)
        self.evidence_repo = MockEvidenceRepo()
        self.anchor_repo = MockAnchorRepo()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.anchor_repo)
        self.blockchain_service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.store,
            audit_repo=self.audit_repo,
            anchor_repo=self.anchor_repo,
        )
        self.capture = EvidenceCapture(
            store=self.store,
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
            snapshot_quality=85,
            blockchain_service=self.blockchain_service,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_frame(self, width=640, height=480, color=(128, 64, 32)):
        """Create a real BGR numpy frame (simulates camera output)."""
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = color
        # Add some structure so JPEG encoding produces non-trivial bytes
        cv2.rectangle(frame, (100, 100), (300, 300), (0, 255, 0), 2)
        cv2.putText(frame, "TRUST TEST", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        return frame

    def _make_event(self, event_id="EVT-TRUST-001"):
        """Create a realistic event dict."""
        return {
            "event_id": event_id,
            "camera_id": "CAM-TRUST-01",
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "track_id": 42,
            "object_class": "person",
            "confidence": 0.95,
            "bbox": {"x1": 100, "y1": 100, "x2": 300, "y2": 300},
            "zone_name": "PERIMETER_FENCE_SECTOR_05",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @patch("ai.blockchain.service.settings")
    def test_01_capture_creates_real_jpeg(self, mock_settings):
        """Step 1: Evidence capture creates a real JPEG file on disk."""
        mock_settings.BLOCKCHAIN_ENABLED = False

        frame = self._make_frame()
        event = self._make_event()

        result = _run(self.capture.capture_snapshot(event, frame, actor="TEST"))

        self.assertIsNotNone(result, "Evidence capture should succeed")
        evidence_id = result["id"]
        file_path = result["filePath"]

        # File exists on disk
        full_path = os.path.join(self.test_dir, file_path)
        self.assertTrue(os.path.exists(full_path), f"Evidence file should exist: {full_path}")
        self.assertGreater(os.path.getsize(full_path), 0, "Evidence file should be non-empty")

        # File is valid JPEG
        with open(full_path, "rb") as f:
            header = f.read(2)
        self.assertEqual(header[:2], b'\xff\xd8', "File should start with JPEG SOI marker")

        return result

    @patch("ai.blockchain.service.settings")
    def test_02_sha256_matches_file_bytes(self, mock_settings):
        """Step 2: SHA-256 stored in DB matches actual file bytes."""
        mock_settings.BLOCKCHAIN_ENABLED = False

        frame = self._make_frame()
        event = self._make_event("EVT-SHA256-001")

        result = _run(self.capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result)

        # Read file and compute SHA-256
        full_path = os.path.join(self.test_dir, result["filePath"])
        with open(full_path, "rb") as f:
            file_bytes = f.read()
        actual_sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Compare with stored hash
        stored_hash = result["sha256Hash"]
        self.assertEqual(actual_sha256, stored_hash,
                         "SHA-256 from file bytes must match stored hash")

        # Also verify via EvidenceCapture.verify_integrity()
        self.assertTrue(
            self.capture.verify_integrity(result["filePath"], stored_hash),
            "verify_integrity should return True for untampered file"
        )

    @patch("ai.blockchain.service.settings")
    def test_03_db_record_matches_file(self, mock_settings):
        """Step 3: PostgreSQL evidence record matches actual file metadata."""
        mock_settings.BLOCKCHAIN_ENABLED = False

        frame = self._make_frame()
        event = self._make_event("EVT-DB-001")

        result = _run(self.capture.capture_snapshot(event, frame, actor="TEST"))
        evidence_id = result["id"]

        # Fetch from "DB"
        db_record = _run(self.evidence_repo.get(evidence_id))
        self.assertIsNotNone(db_record, "DB record should exist")

        # Verify all fields
        self.assertEqual(db_record["id"], evidence_id)
        self.assertEqual(db_record["eventId"], "EVT-DB-001")
        self.assertEqual(db_record["cameraId"], "CAM-TRUST-01")
        self.assertEqual(db_record["evidenceType"], "SNAPSHOT")
        self.assertEqual(db_record["mimeType"], "image/jpeg")
        self.assertEqual(db_record["integrityStatus"], "VALID")

        # File size matches
        full_path = os.path.join(self.test_dir, db_record["filePath"])
        actual_size = os.path.getsize(full_path)
        self.assertEqual(db_record["fileSize"], actual_size,
                         "DB file_size must match actual file size")

        # SHA-256 matches
        with open(full_path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(db_record["sha256Hash"], actual_hash,
                         "DB sha256_hash must match actual file hash")

    @patch("ai.blockchain.service.settings")
    def test_04_blockchain_anchor_uses_real_fingerprint(self, mock_settings):
        """Step 4: Blockchain anchor stores the actual evidence SHA-256 fingerprint."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"

        frame = self._make_frame()
        event = self._make_event("EVT-ANCHOR-001")

        # Capture with blockchain enabled
        result = _run(self.capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result)
        evidence_id = result["id"]
        evidence_sha256 = result["sha256Hash"]

        # Verify anchor was created
        anchor = _run(self.anchor_repo.get_by_evidence(evidence_id))
        self.assertIsNotNone(anchor, "Blockchain anchor should be created")

        # Anchor stores the SAME SHA-256 as the evidence
        self.assertEqual(anchor["sha256Hash"], evidence_sha256,
                         "Anchor sha256_hash must match evidence sha256")

        # Anchor has required fields
        self.assertTrue(anchor["anchorId"].startswith("ANC-"))
        self.assertEqual(anchor["evidenceId"], evidence_id)
        self.assertEqual(anchor["status"], "CONFIRMED")
        self.assertGreater(anchor["blockNumber"], 0)
        self.assertEqual(len(anchor["recordHash"]), 64, "record_hash should be 64-char hex")
        self.assertEqual(len(anchor["txHash"]), 64, "tx_hash should be 64-char hex")

    @patch("ai.blockchain.service.settings")
    def test_05_verify_returns_verified(self, mock_settings):
        """Step 5: Evidence verification returns VERIFIED for untampered file."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"

        frame = self._make_frame()
        event = self._make_event("EVT-VERIFY-001")

        result = _run(self.capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result)

        # Run three-layer verification
        bc_result = _run(self.blockchain_service.verify_evidence(result))

        self.assertTrue(bc_result.verified, f"Verification should pass, got status={bc_result.status}")
        self.assertEqual(bc_result.status, VERIFIED)
        self.assertEqual(bc_result.local_hash, result["sha256Hash"])

    @patch("ai.blockchain.service.settings")
    def test_06_tamper_detection(self, mock_settings):
        """Step 6: Modifying the evidence file changes SHA-256 and verification detects tampering."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"

        frame = self._make_frame()
        event = self._make_event("EVT-TAMPER-001")

        result = _run(self.capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result)
        original_hash = result["sha256Hash"]
        file_path = result["filePath"]
        full_path = os.path.join(self.test_dir, file_path)

        # Backup original bytes
        with open(full_path, "rb") as f:
            original_bytes = f.read()

        # Tamper: modify file bytes (append extra data)
        with open(full_path, "ab") as f:
            f.write(b"TAMPERED_DATA_12345")

        # Verify SHA-256 changed
        with open(full_path, "rb") as f:
            tampered_bytes = f.read()
        tampered_hash = hashlib.sha256(tampered_bytes).hexdigest()
        self.assertNotEqual(original_hash, tampered_hash,
                            "Tampered file hash must differ from original")

        # Verify integrity check fails
        self.assertFalse(
            self.capture.verify_integrity(file_path, original_hash),
            "verify_integrity should return False for tampered file"
        )

        # Blockchain verification should detect tampering
        bc_result = _run(self.blockchain_service.verify_evidence(result))
        self.assertFalse(bc_result.verified, "Verification should fail for tampered file")
        self.assertEqual(bc_result.status, EVIDENCE_TAMPERED,
                         "Status should be EVIDENCE_TAMPERED")

        # Blockchain anchor should remain unchanged
        anchor = _run(self.anchor_repo.get_by_evidence(result["id"]))
        self.assertEqual(anchor["sha256Hash"], original_hash,
                         "Blockchain anchor must NOT change during tamper")
        self.assertEqual(anchor["status"], "CONFIRMED",
                         "Blockchain anchor status must remain CONFIRMED")

        return result, original_bytes, original_hash

    @patch("ai.blockchain.service.settings")
    def test_07_restore_and_reverify(self, mock_settings):
        """Step 7: Restoring original bytes makes verification return VERIFIED again."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"

        frame = self._make_frame()
        event = self._make_event("EVT-RESTORE-001")

        result = _run(self.capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result)
        original_hash = result["sha256Hash"]
        file_path = result["filePath"]
        full_path = os.path.join(self.test_dir, file_path)

        # Backup original bytes
        with open(full_path, "rb") as f:
            original_bytes = f.read()

        # Tamper
        with open(full_path, "ab") as f:
            f.write(b"TAMPERED")

        # Verify detection
        bc_tampered = _run(self.blockchain_service.verify_evidence(result))
        self.assertEqual(bc_tampered.status, EVIDENCE_TAMPERED)

        # Restore original bytes
        with open(full_path, "wb") as f:
            f.write(original_bytes)

        # Verify restored
        with open(full_path, "rb") as f:
            restored_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(restored_hash, original_hash,
                         "Restored file hash must match original")

        bc_restored = _run(self.blockchain_service.verify_evidence(result))
        self.assertTrue(bc_restored.verified, "Verification should pass after restore")
        self.assertEqual(bc_restored.status, VERIFIED)


class TestAutoAnchoring(unittest.TestCase):
    """Verify that automatic anchoring works when BlockchainService is properly wired."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ibvap_auto_anchor_")
        self.store = LocalFileEvidenceStore(base_dir=self.test_dir)
        self.evidence_repo = MockEvidenceRepo()
        self.anchor_repo = MockAnchorRepo()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.anchor_repo)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("ai.blockchain.service.settings")
    def test_auto_anchor_fires_from_capture(self, mock_settings):
        """Auto-anchoring fires when EvidenceCapture has a real BlockchainService."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"

        bc_service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.store,
            audit_repo=self.audit_repo,
            anchor_repo=self.anchor_repo,
        )

        capture = EvidenceCapture(
            store=self.store,
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
            snapshot_quality=85,
            blockchain_service=bc_service,
        )

        # Verify service is NOT None
        self.assertIsNotNone(capture._blockchain_service,
                             "EvidenceCapture must receive real BlockchainService")
        self.assertTrue(capture._blockchain_service.enabled,
                        "BlockchainService must be enabled")

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(frame, "AUTO", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        event = {
            "event_id": "EVT-AUTO-001",
            "camera_id": "CAM-AUTO-01",
            "event_type": "VEHICLE_INTRUSION",
            "severity": "HIGH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        result = _run(capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result)
        evidence_id = result["id"]

        # Auto-anchor should have been created
        anchor = _run(self.anchor_repo.get_by_evidence(evidence_id))
        self.assertIsNotNone(anchor,
                             "Auto-anchor must be created by capture_snapshot pipeline")
        self.assertEqual(anchor["sha256Hash"], result["sha256Hash"],
                         "Anchor must store evidence SHA-256")

    @patch("ai.blockchain.service.settings")
    def test_no_auto_anchor_when_service_none(self, mock_settings):
        """No auto-anchoring when BlockchainService is None (original bug scenario)."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"

        # Create EvidenceCapture with blockchain_service=None (simulates old bug)
        capture = EvidenceCapture(
            store=self.store,
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
            snapshot_quality=85,
            blockchain_service=None,
        )

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        event = {
            "event_id": "EVT-NOANCHOR-001",
            "camera_id": "CAM-NO-01",
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        result = _run(capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result)

        # No anchor should exist
        anchor = _run(self.anchor_repo.get_by_evidence(result["id"]))
        self.assertIsNone(anchor,
                          "No anchor should exist when BlockchainService is None")


class TestBlockchainFailureIsolation(unittest.TestCase):
    """Verify that blockchain failure does NOT stop evidence capture or AI processing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ibvap_fail_iso_")
        self.store = LocalFileEvidenceStore(base_dir=self.test_dir)
        self.evidence_repo = MockEvidenceRepo()
        self.anchor_repo = MockAnchorRepo()
        self.audit_repo = MockAuditRepo()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("ai.blockchain.service.settings")
    def test_evidence_captured_when_blockchain_fails(self, mock_settings):
        """Evidence capture succeeds even when blockchain anchoring fails."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"

        # Create a broken ledger that raises on append
        class BrokenLedger:
            async def append(self, evidence_id, sha256_hash):
                raise RuntimeError("Blockchain ledger is broken!")
            async def verify(self, evidence_id, sha256_hash):
                raise RuntimeError("Blockchain ledger is broken!")
            async def get_proof(self, anchor_id):
                return None
            async def get_proof_by_evidence(self, evidence_id):
                return None
            async def stats(self):
                return None
            async def health_check(self):
                return False

        bc_service = BlockchainService(
            ledger=BrokenLedger(),
            evidence_repo=self.evidence_repo,
            evidence_store=self.store,
            audit_repo=self.audit_repo,
            anchor_repo=self.anchor_repo,
        )

        capture = EvidenceCapture(
            store=self.store,
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
            snapshot_quality=85,
            blockchain_service=bc_service,
        )

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        event = {
            "event_id": "EVT-FAIL-001",
            "camera_id": "CAM-FAIL-01",
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Capture should NOT raise despite blockchain failure
        result = _run(capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNotNone(result, "Evidence capture must succeed despite blockchain failure")

        # Evidence file exists
        full_path = os.path.join(self.test_dir, result["filePath"])
        self.assertTrue(os.path.exists(full_path), "Evidence file must exist")

        # Evidence record in DB
        db_record = _run(self.evidence_repo.get(result["id"]))
        self.assertIsNotNone(db_record, "Evidence DB record must exist")

        # SHA-256 is valid
        with open(full_path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(result["sha256Hash"], actual_hash)

        # No anchor was created (blockchain failed)
        anchor = _run(self.anchor_repo.get_by_evidence(result["id"]))
        self.assertIsNone(anchor, "No anchor should exist when blockchain fails")

    @patch("ai.blockchain.service.settings")
    def test_event_persists_when_evidence_capture_fails(self, mock_settings):
        """Event creation continues even if evidence storage fails."""
        mock_settings.BLOCKCHAIN_ENABLED = False

        # Create a broken store
        class BrokenStore:
            def save(self, data, path):
                raise IOError("Disk full!")
            def load(self, path):
                return b""
            def exists(self, path):
                return False
            def delete(self, path):
                return False
            def size(self, path):
                return 0

        capture = EvidenceCapture(
            store=BrokenStore(),
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
            snapshot_quality=85,
            blockchain_service=None,
        )

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        event = {
            "event_id": "EVT-EVFAIL-001",
            "camera_id": "CAM-EVFAIL-01",
            "event_type": "VEHICLE_INTRUSION",
            "severity": "HIGH",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Capture should return None but NOT raise
        result = _run(capture.capture_snapshot(event, frame, actor="TEST"))
        self.assertIsNone(result, "Capture returns None on store failure")
        # The important thing: no exception was raised — the pipeline continues


class TestReconciliationValidation(unittest.TestCase):
    """Verify reconciliation detects mismatches between PG and ledger."""

    def setUp(self):
        self.anchor_repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.anchor_repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
            anchor_repo=self.anchor_repo,
        )

    @patch("ai.blockchain.service.settings")
    def test_reconcile_matching_data(self, mock_settings):
        """Reconciliation succeeds when PG and ledger agree."""
        mock_settings.BLOCKCHAIN_ENABLED = True

        anchor = _run(self.ledger.append("EVD-REC-001", "a" * 64))
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))

        self.assertTrue(result.matched, f"Should match, mismatches={result.mismatches}")
        self.assertEqual(len(result.mismatches), 0)

    @patch("ai.blockchain.service.settings")
    def test_reconcile_detects_hash_mismatch(self, mock_settings):
        """Reconciliation detects when PG hash differs from ledger."""
        mock_settings.BLOCKCHAIN_ENABLED = True

        anchor = _run(self.ledger.append("EVD-REC-002", "a" * 64))

        # Intercept ledger.get_proof to return modified data (simulates external DB tampering)
        original_get_proof = self.ledger.get_proof

        async def tampered_get_proof(anchor_id):
            result = await original_get_proof(anchor_id)
            if result:
                result.sha256_hash = "b" * 64  # Different from PG
            return result

        self.ledger.get_proof = tampered_get_proof

        result = _run(self.service.reconcile_anchor(anchor.anchor_id))

        self.assertFalse(result.matched)
        self.assertIn("sha256_hash", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_reconcile_detects_record_hash_mismatch(self, mock_settings):
        """Reconciliation detects when PG record_hash differs from ledger."""
        mock_settings.BLOCKCHAIN_ENABLED = True

        anchor = _run(self.ledger.append("EVD-REC-003", "c" * 64))

        # Intercept ledger.get_proof to return modified data
        original_get_proof = self.ledger.get_proof

        async def tampered_get_proof(anchor_id):
            result = await original_get_proof(anchor_id)
            if result:
                result.record_hash = "d" * 64  # Different from PG
            return result

        self.ledger.get_proof = tampered_get_proof

        result = _run(self.service.reconcile_anchor(anchor.anchor_id))

        self.assertFalse(result.matched)
        self.assertIn("record_hash", result.mismatches)


class TestAuditLogging(unittest.TestCase):
    """Verify audit events are recorded for evidence and blockchain operations."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ibvap_audit_")
        self.store = LocalFileEvidenceStore(base_dir=self.test_dir)
        self.evidence_repo = MockEvidenceRepo()
        self.anchor_repo = MockAnchorRepo()
        self.audit_repo = MockAuditRepo()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("ai.blockchain.service.settings")
    def test_capture_generates_audit_log(self, mock_settings):
        """Evidence capture generates an audit log entry."""
        mock_settings.BLOCKCHAIN_ENABLED = False

        capture = EvidenceCapture(
            store=self.store,
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
            snapshot_quality=85,
            blockchain_service=None,
        )

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        event = {
            "event_id": "EVT-AUDIT-001",
            "camera_id": "CAM-AUDIT-01",
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        _run(capture.capture_snapshot(event, frame, actor="TEST_USER"))

        # Check audit logs
        capture_logs = [l for l in self.audit_repo.logs if l["action"] == "evidence.capture"]
        self.assertEqual(len(capture_logs), 1, "Should have one evidence.capture audit log")
        self.assertEqual(capture_logs[0]["actor"], "TEST_USER")
        self.assertEqual(capture_logs[0]["entity_type"], "evidence")

    @patch("ai.blockchain.service.settings")
    def test_blockchain_anchor_generates_audit_log(self, mock_settings):
        """Blockchain anchoring generates an audit log entry."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"

        service = BlockchainService(
            ledger=LocalLedger(anchor_repo=self.anchor_repo),
            evidence_repo=self.evidence_repo,
            evidence_store=self.store,
            audit_repo=self.audit_repo,
            anchor_repo=self.anchor_repo,
        )

        # Seed evidence in repo
        _run(self.evidence_repo.create({
            "id": "EVD-AUDIT-BC-001",
            "sha256Hash": "e" * 64,
            "filePath": "test/file.jpg",
            "metadata": {"severity": "CRITICAL"},
        }))

        _run(service.maybe_anchor({"id": "EVD-AUDIT-BC-001", "metadata": {"severity": "CRITICAL"}}))

        anchor_logs = [l for l in self.audit_repo.logs if l["action"] == "blockchain.anchor"]
        self.assertEqual(len(anchor_logs), 1, "Should have one blockchain.anchor audit log")
        self.assertEqual(anchor_logs[0]["actor"], "BLOCKCHAIN_SERVICE")


class TestSecretLeakagePrevention(unittest.TestCase):
    """Verify that no secrets appear in audit logs or output."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ibvap_secret_")
        self.store = LocalFileEvidenceStore(base_dir=self.test_dir)
        self.audit_repo = MockAuditRepo()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("ai.blockchain.service.settings")
    def test_no_secrets_in_audit_logs(self, mock_settings):
        """Audit logs must not contain passwords, tokens, or secrets."""
        mock_settings.BLOCKCHAIN_ENABLED = False

        evidence_repo = MockEvidenceRepo()
        anchor_repo = MockAnchorRepo()

        capture = EvidenceCapture(
            store=self.store,
            evidence_repo=evidence_repo,
            audit_repo=self.audit_repo,
            snapshot_quality=85,
            blockchain_service=None,
        )

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        event = {
            "event_id": "EVT-AUDIT-LOG-001",
            "camera_id": "CAM-AUDIT-01",
            "event_type": "PERSON_INTRUSION",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        _run(capture.capture_snapshot(event, frame, actor="SYSTEM"))

        # Check all audit log details for leaked secrets
        sensitive_patterns = [
            "password", "secret", "token", "DATABASE_URL",
            "strawhacks", "admin123", "ibvap-dev-secret",
        ]
        for log_entry in self.audit_repo.logs:
            details_str = str(log_entry.get("details", {}))
            for pattern in sensitive_patterns:
                self.assertNotIn(
                    pattern.lower(), details_str.lower(),
                    f"Audit log must not contain '{pattern}': {details_str}"
                )


if __name__ == "__main__":
    unittest.main()
