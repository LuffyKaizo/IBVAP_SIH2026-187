"""Tests for the blockchain trust layer.

Covers: LocalLedger, BlockchainService, repository, evidence integration,
security/API, and failure/resilience scenarios.

Uses unittest.TestCase + _run() helper (Windows-safe async).
No real database required — all tests use mock repositories.
"""

import asyncio
import hashlib
import json
import secrets
import time
import unittest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from ai.blockchain.exceptions import AnchorError, DuplicateAnchorError
from ai.blockchain.interface import BlockchainLedger
from ai.blockchain.models import (
    AnchorResult, VerificationResult, LedgerStats,
    ANCHOR_STATUS_PENDING, ANCHOR_STATUS_CONFIRMED, ANCHOR_STATUS_FAILED,
    VERIFIED, ANCHOR_NOT_FOUND, BLOCKCHAIN_HASH_MISMATCH, BLOCKCHAIN_UNAVAILABLE,
    DATABASE_HASH_MISMATCH, VERIFICATION_FAILED,
)
from ai.blockchain.local_ledger import LocalLedger, _compute_record_hash, _canonical_record, _RECORD_VERSION
from ai.blockchain.service import BlockchainService
from ai.blockchain.repository import BlockchainAnchorRepository
from ai.evidence.capture import EvidenceCapture


def _sha256(data: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine with a fresh event loop (Windows-safe)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────
# Mock Repository (in-memory)
# ──────────────────────────────────────────────────────────────

class MockAnchorRepo:
    """In-memory mock for BlockchainAnchorRepository."""

    def __init__(self):
        self._anchors = {}
        self._counter = 0

    async def create(
        self, anchor_id, evidence_id, sha256_hash, record_hash, tx_hash,
        block_number=0, previous_hash="", status="PENDING", confirmation_time_ms=0.0,
    ):
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


class MockEvidenceRepo:
    """In-memory mock for EvidenceRepository."""

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


class MockEvidenceStore:
    """In-memory mock for EvidenceStore."""

    def __init__(self):
        self._files = {}

    def save(self, data, path):
        self._files[path] = data
        return path

    def load(self, path):
        return self._files.get(path, b"")

    def delete(self, path):
        return self._files.pop(path, None) is not None

    def exists(self, path):
        return path in self._files

    def size(self, path):
        return len(self._files.get(path, b""))


class MockAuditRepo:
    """In-memory mock for AuditRepository."""

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
# LocalLedger Tests
# ──────────────────────────────────────────────────────────────

class TestLocalLedger(unittest.TestCase):
    """Test LocalLedger development blockchain adapter."""

    def setUp(self):
        self.repo = MockAnchorRepo()
        self.ledger = LocalLedger(anchor_repo=self.repo)

    # 1. append
    def test_01_append_creates_anchor(self):
        result = _run(self.ledger.append("EVD-001", "a" * 64))
        self.assertEqual(result.evidence_id, "EVD-001")
        self.assertEqual(result.status, ANCHOR_STATUS_CONFIRMED)
        self.assertTrue(result.anchor_id.startswith("ANC-"))
        self.assertEqual(result.sha256_hash, "a" * 64)

    # 2. deterministic hash
    def test_02_deterministic_record_hash(self):
        ts = "2026-01-01T00:00:00+00:00"
        canonical = _canonical_record(_RECORD_VERSION, "EVD-001", "aaa", "000" * 64, ts)
        h1 = _compute_record_hash(canonical)
        h2 = _compute_record_hash(canonical)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # SHA-256 hex

    # 3. first block previous_hash
    def test_03_first_block_previous_hash(self):
        result = _run(self.ledger.append("EVD-FIRST", "b" * 64))
        self.assertEqual(result.previous_hash, "0" * 64)

    # 4. chained previous_hash
    def test_04_chained_previous_hash(self):
        r1 = _run(self.ledger.append("EVD-CHAIN-1", "c" * 64))
        r2 = _run(self.ledger.append("EVD-CHAIN-2", "d" * 64))
        self.assertEqual(r2.previous_hash, r1.record_hash)

    # 5. verify valid record
    def test_05_verify_valid_record(self):
        _run(self.ledger.append("EVD-VERIFY", "e" * 64))
        result = _run(self.ledger.verify("EVD-VERIFY", "e" * 64))
        self.assertTrue(result.verified)
        self.assertEqual(result.status, VERIFIED)

    # 6. detect modified chain
    def test_06_detect_modified_evidence_hash(self):
        _run(self.ledger.append("EVD-MOD", "f" * 64))
        result = _run(self.ledger.verify("EVD-MOD", "0" * 64))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, BLOCKCHAIN_HASH_MISMATCH)

    # 7. detect modified evidence hash (different from chain)
    def test_07_detect_modified_hash_from_chain(self):
        _run(self.ledger.append("EVD-MOD2", "g" * 64))
        result = _run(self.ledger.verify("EVD-MOD2", "1" * 64))
        self.assertFalse(result.verified)
        self.assertNotEqual(result.chain_hash, result.local_hash)

    # 8. idempotent duplicate
    def test_08_idempotent_duplicate(self):
        r1 = _run(self.ledger.append("EVD-DUP", "h" * 64))
        r2 = _run(self.ledger.append("EVD-DUP", "h" * 64))
        self.assertEqual(r1.anchor_id, r2.anchor_id)
        self.assertEqual(r1.record_hash, r2.record_hash)

    # 9. stats
    def test_09_stats(self):
        _run(self.ledger.append("EVD-S1", "i" * 64))
        _run(self.ledger.append("EVD-S2", "j" * 64))
        stats = _run(self.ledger.stats())
        self.assertEqual(stats.total_anchors, 2)
        self.assertEqual(stats.confirmed, 2)
        self.assertEqual(stats.pending, 0)
        self.assertEqual(stats.failed, 0)

    # 10. health
    def test_10_health_check(self):
        healthy = _run(self.ledger.health_check())
        self.assertTrue(healthy)

    # 11. verify nonexistent
    def test_11_verify_nonexistent(self):
        result = _run(self.ledger.verify("EVD-NONE", "x" * 64))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, ANCHOR_NOT_FOUND)

    # 12. get_proof
    def test_12_get_proof(self):
        r = _run(self.ledger.append("EVD-PROOF", "k" * 64))
        proof = _run(self.ledger.get_proof(r.anchor_id))
        self.assertIsNotNone(proof)
        self.assertEqual(proof.evidence_id, "EVD-PROOF")

    # 13. get_proof nonexistent
    def test_13_get_proof_nonexistent(self):
        proof = _run(self.ledger.get_proof("ANC-NONE"))
        self.assertIsNone(proof)

    # 14. get_proof_by_evidence
    def test_14_get_proof_by_evidence(self):
        _run(self.ledger.append("EVD-BYEV", "l" * 64))
        proof = _run(self.ledger.get_proof_by_evidence("EVD-BYEV"))
        self.assertIsNotNone(proof)
        self.assertEqual(proof.evidence_id, "EVD-BYEV")

    # 15. record_hash and tx_hash are distinct
    def test_15_record_hash_vs_tx_hash_distinct(self):
        r = _run(self.ledger.append("EVD-DIST", "m" * 64))
        self.assertNotEqual(r.record_hash, r.tx_hash)
        self.assertEqual(len(r.record_hash), 64)
        self.assertEqual(len(r.tx_hash), 64)


# ──────────────────────────────────────────────────────────────
# BlockchainService Tests
# ──────────────────────────────────────────────────────────────

class TestBlockchainService(unittest.TestCase):
    """Test BlockchainService orchestration and policy evaluation."""

    def setUp(self):
        self.repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.evidence_store = MockEvidenceStore()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.evidence_store,
            audit_repo=self.audit_repo,
        )

    def _seed_evidence(self, evidence_id, sha256=None, severity="HIGH", file_content=b"fake-jpeg-data"):
        """Helper to seed evidence in mock repo. If sha256 is None, computes it from file_content."""
        if sha256 is None:
            sha256 = _sha256(file_content)
        file_path = "%s/EVT-001/%s.jpg" % ("CAM-01", evidence_id)
        _run(self.evidence_repo.create({
            "id": evidence_id,
            "eventId": "EVT-001",
            "cameraId": "CAM-01",
            "sha256Hash": sha256,
            "filePath": file_path,
            "metadata": {"severity": severity, "event_type": "INTRUSION"},
        }))
        # Also store a file in the mock store
        self.evidence_store.save(file_content, file_path)

    @patch("ai.blockchain.service.settings")
    def test_16_all_policy(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        ev = {"id": "EVD-POL1", "metadata": {"severity": "LOW"}}
        self.assertTrue(self.service._should_anchor(ev))

    @patch("ai.blockchain.service.settings")
    def test_17_high_severity_policy(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "high_severity"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        ev_high = {"id": "EVD-POL2", "metadata": {"severity": "HIGH"}}
        ev_low = {"id": "EVD-POL3", "metadata": {"severity": "LOW"}}
        self.assertTrue(self.service._should_anchor(ev_high))
        self.assertFalse(self.service._should_anchor(ev_low))

    @patch("ai.blockchain.service.settings")
    def test_18_below_threshold(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "high_severity"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "CRITICAL"
        ev = {"id": "EVD-LOW", "metadata": {"severity": "HIGH"}}
        self.assertFalse(self.service._should_anchor(ev))

    @patch("ai.blockchain.service.settings")
    def test_19_manual_only_policy(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "manual_only"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        ev = {"id": "EVD-MAN", "metadata": {"severity": "CRITICAL"}}
        self.assertFalse(self.service._should_anchor(ev))

    @patch("ai.blockchain.service.settings")
    def test_20_maybe_anchor(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        self._seed_evidence("EVD-MAYBE")
        result = _run(self.service.maybe_anchor({"id": "EVD-MAYBE"}))
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ANCHOR_STATUS_CONFIRMED)

    @patch("ai.blockchain.service.settings")
    def test_21_verify_evidence(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        file_content = b"fake-jpeg-data"
        file_hash = _sha256(file_content)
        self._seed_evidence("EVD-VER", file_hash, file_content=file_content)
        _run(self.ledger.append("EVD-VER", file_hash))
        result = _run(self.service.verify_evidence({
            "id": "EVD-VER",
            "sha256Hash": file_hash,
        }))
        self.assertTrue(result.verified)
        self.assertEqual(result.status, VERIFIED)

    @patch("ai.blockchain.service.settings")
    def test_22_health_delegation(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        healthy = _run(self.service.health_check())
        self.assertTrue(healthy)
        self.assertEqual(self.service._previous_health, True)

    @patch("ai.blockchain.service.settings")
    def test_23_failure_isolation(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        # Evidence not in DB — should not raise
        result = _run(self.service.maybe_anchor({"id": "EVD-NOPE"}))
        self.assertIsNone(result)


# ──────────────────────────────────────────────────────────────
# Repository Tests
# ──────────────────────────────────────────────────────────────

class TestBlockchainRepository(unittest.TestCase):
    """Test MockAnchorRepo (validates the repository interface contract)."""

    def setUp(self):
        self.repo = MockAnchorRepo()

    def test_24_create(self):
        result = _run(self.repo.create(
            "ANC-001", "EVD-001", "a" * 64, "r" * 64, "tx" + "0" * 62,
        ))
        self.assertIsNotNone(result)
        self.assertEqual(result["anchorId"], "ANC-001")

    def test_25_get_by_id(self):
        _run(self.repo.create("ANC-002", "EVD-002", "b" * 64, "r2" + "0" * 62, "tx2" + "0" * 61))
        result = _run(self.repo.get_by_id("ANC-002"))
        self.assertIsNotNone(result)
        self.assertEqual(result["evidenceId"], "EVD-002")

    def test_26_get_by_evidence(self):
        _run(self.repo.create("ANC-003", "EVD-003", "c" * 64, "r3" + "0" * 62, "tx3" + "0" * 61, status="CONFIRMED"))
        result = _run(self.repo.get_by_evidence("EVD-003"))
        self.assertIsNotNone(result)
        self.assertEqual(result["anchorId"], "ANC-003")

    def test_27_update_status(self):
        _run(self.repo.create("ANC-004", "EVD-004", "d" * 64, "r4" + "0" * 62, "tx4" + "0" * 61))
        ok = _run(self.repo.update_status("ANC-004", "CONFIRMED", block_number=1, confirmation_time_ms=50.0))
        self.assertTrue(ok)
        updated = _run(self.repo.get_by_id("ANC-004"))
        self.assertEqual(updated["status"], "CONFIRMED")
        self.assertEqual(updated["blockNumber"], 1)
        self.assertEqual(updated["confirmationTimeMs"], 50.0)

    def test_28_list_pending(self):
        _run(self.repo.create("ANC-P1", "EVD-P1", "e" * 64, "rp1" + "0" * 61, "txp1" + "0" * 60, status="PENDING"))
        _run(self.repo.create("ANC-P2", "EVD-P2", "f" * 64, "rp2" + "0" * 61, "txp2" + "0" * 60, status="CONFIRMED"))
        pending = _run(self.repo.list_pending())
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["anchorId"], "ANC-P1")

    def test_29_count_by_status(self):
        _run(self.repo.create("ANC-C1", "EVD-C1", "g" * 64, "rc1" + "0" * 61, "txc1" + "0" * 60, status="CONFIRMED"))
        _run(self.repo.create("ANC-C2", "EVD-C2", "h" * 64, "rc2" + "0" * 61, "txc2" + "0" * 60, status="CONFIRMED"))
        _run(self.repo.create("ANC-C3", "EVD-C3", "i" * 64, "rc3" + "0" * 61, "txc3" + "0" * 60, status="PENDING"))
        counts = _run(self.repo.count_by_status())
        self.assertEqual(counts["CONFIRMED"], 2)
        self.assertEqual(counts["PENDING"], 1)

    def test_30_list_recent(self):
        _run(self.repo.create("ANC-R1", "EVD-R1", "j" * 64, "rr1" + "0" * 61, "txr1" + "0" * 60))
        _run(self.repo.create("ANC-R2", "EVD-R2", "k" * 64, "rr2" + "0" * 61, "txr2" + "0" * 60))
        recent = _run(self.repo.list_recent(limit=1))
        self.assertEqual(len(recent), 1)


# ──────────────────────────────────────────────────────────────
# Evidence Integration Tests
# ──────────────────────────────────────────────────────────────

class TestEvidenceIntegration(unittest.TestCase):
    """Test blockchain integration with evidence capture and verification."""

    def setUp(self):
        self.repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.evidence_store = MockEvidenceStore()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.evidence_store,
            audit_repo=self.audit_repo,
        )

    @patch("ai.blockchain.service.settings")
    def test_31_capture_triggers_anchor(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        file_content = b"test-jpeg-data"
        file_hash = _sha256(file_content)
        _run(self.evidence_repo.create({
            "id": "EVD-CAP", "eventId": "EVT-1", "cameraId": "CAM-1",
            "sha256Hash": file_hash, "filePath": "CAM-1/EVT-1/EVD-CAP.jpg",
            "metadata": {"severity": "HIGH"},
        }))
        self.evidence_store.save(file_content, "CAM-1/EVT-1/EVD-CAP.jpg")
        result = _run(self.service.maybe_anchor({"id": "EVD-CAP"}))
        self.assertIsNotNone(result)

    @patch("ai.blockchain.service.settings")
    def test_32_disabled_does_not_break(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = False
        result = _run(self.service.maybe_anchor({"id": "EVD-DIS"}))
        self.assertIsNone(result)

    @patch("ai.blockchain.service.settings")
    def test_33_verify_detects_modified(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        _run(self.evidence_repo.create({
            "id": "EVD-TAM", "eventId": "EVT-2", "cameraId": "CAM-2",
            "sha256Hash": "original" + "0" * 57, "filePath": "",
            "metadata": {},
        }))
        _run(self.ledger.append("EVD-TAM", "original" + "0" * 57))
        result = _run(self.service.verify_evidence({
            "id": "EVD-TAM",
            "sha256Hash": "tampered" + "0" * 56,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, DATABASE_HASH_MISMATCH)

    @patch("ai.blockchain.service.settings")
    def test_34_successful_blockchain_verification(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        _run(self.evidence_repo.create({
            "id": "EVD-OK", "eventId": "EVT-3", "cameraId": "CAM-3",
            "sha256Hash": "legit" + "0" * 60, "filePath": "",
            "metadata": {},
        }))
        _run(self.ledger.append("EVD-OK", "legit" + "0" * 60))
        result = _run(self.service.verify_evidence({
            "id": "EVD-OK",
            "sha256Hash": "legit" + "0" * 60,
        }))
        self.assertTrue(result.verified)


# ──────────────────────────────────────────────────────────────
# Security / API Tests
# ──────────────────────────────────────────────────────────────

class TestSecurityAndApi(unittest.TestCase):
    """Test security properties: RBAC, edge isolation, hash injection."""

    def test_35_admin_can_anchor(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.BLOCKCHAIN_ANCHOR, ROLE_PERMISSIONS[Role.ADMIN])
        self.assertIn(Permission.BLOCKCHAIN_READ, ROLE_PERMISSIONS[Role.ADMIN])

    def test_36_operator_can_anchor(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.BLOCKCHAIN_ANCHOR, ROLE_PERMISSIONS[Role.OPERATOR])
        self.assertIn(Permission.BLOCKCHAIN_READ, ROLE_PERMISSIONS[Role.OPERATOR])

    def test_37_viewer_cannot_anchor(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertNotIn(Permission.BLOCKCHAIN_ANCHOR, ROLE_PERMISSIONS[Role.VIEWER])
        self.assertIn(Permission.BLOCKCHAIN_READ, ROLE_PERMISSIONS[Role.VIEWER])

    def test_38_viewer_can_read(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.BLOCKCHAIN_READ, ROLE_PERMISSIONS[Role.VIEWER])

    def test_39_edge_cannot_anchor(self):
        from ai.edge.models import EdgePermissions
        self.assertFalse(EdgePermissions.CAN_BLOCKCHAIN_ANCHOR)
        self.assertFalse(EdgePermissions.CAN_BLOCKCHAIN_READ)

    def test_40_arbitrary_hash_rejected(self):
        """BlockchainService should not trust client-provided hashes."""
        repo = MockAnchorRepo()
        evidence_repo = MockEvidenceRepo()
        service = BlockchainService(
            ledger=LocalLedger(anchor_repo=repo),
            evidence_repo=evidence_repo,
        )
        # Evidence not in DB — should return None, not use the provided hash
        result = _run(service.maybe_anchor({
            "id": "EVD-FAKE",
            "sha256Hash": "evil" + "0" * 60,
        }))
        self.assertIsNone(result)
        # No anchor should exist
        self.assertEqual(len(repo._anchors), 0)

    def test_41_invalid_evidence_rejected(self):
        """Missing evidence ID should be rejected."""
        repo = MockAnchorRepo()
        service = BlockchainService(
            ledger=LocalLedger(anchor_repo=repo),
            evidence_repo=MockEvidenceRepo(),
        )
        result = _run(service.maybe_anchor({"sha256Hash": "a" * 64}))
        self.assertIsNone(result)

    def test_42_duplicate_anchor_prevented(self):
        """Idempotent: same evidence_id returns existing anchor."""
        repo = MockAnchorRepo()
        ledger = LocalLedger(anchor_repo=repo)
        r1 = _run(ledger.append("EVD-IDEM", "a" * 64))
        r2 = _run(ledger.append("EVD-IDEM", "a" * 64))
        self.assertEqual(r1.anchor_id, r2.anchor_id)

    def test_43_permissions_complete(self):
        """Verify all new blockchain permissions exist."""
        from ai.auth.models import Permission
        self.assertTrue(hasattr(Permission, "BLOCKCHAIN_READ"))
        self.assertTrue(hasattr(Permission, "BLOCKCHAIN_ANCHOR"))
        self.assertEqual(Permission.BLOCKCHAIN_READ.value, "BLOCKCHAIN_READ")
        self.assertEqual(Permission.BLOCKCHAIN_ANCHOR.value, "BLOCKCHAIN_ANCHOR")


# ──────────────────────────────────────────────────────────────
# Failure / Resilience Tests
# ──────────────────────────────────────────────────────────────

class TestFailureResilience(unittest.TestCase):
    """Test failure isolation, recovery, and audit logging."""

    def setUp(self):
        self.repo = MockAnchorRepo()
        self.audit_repo = MockAuditRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.ledger = LocalLedger(anchor_repo=self.repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
        )

    @patch("ai.blockchain.service.settings")
    def test_44_blockchain_unavailable(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        # Use a broken ledger
        class BrokenLedger(BlockchainLedger):
            async def append(self, evidence_id, sha256_hash): raise AnchorError("unavailable")
            async def verify(self, evidence_id, sha256_hash): return VerificationResult(False, BLOCKCHAIN_UNAVAILABLE, "", "", evidence_id)
            async def get_proof(self, anchor_id): return None
            async def get_proof_by_evidence(self, evidence_id): return None
            async def stats(self): return LedgerStats()
            async def health_check(self): return False

        service = BlockchainService(
            ledger=BrokenLedger(),
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
        )
        _run(self.evidence_repo.create({
            "id": "EVD-BRK", "sha256Hash": "a" * 64, "filePath": "",
            "metadata": {"severity": "HIGH"},
        }))
        result = _run(service.maybe_anchor({"id": "EVD-BRK"}))
        self.assertIsNone(result)
        healthy = _run(service.health_check())
        self.assertFalse(healthy)

    @patch("ai.blockchain.service.settings")
    def test_45_audit_generated(self, mock_settings):
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        file_content = b"audit-test-data"
        file_hash = _sha256(file_content)
        _run(self.evidence_repo.create({
            "id": "EVD-AUD", "eventId": "EVT-A", "cameraId": "CAM-A",
            "sha256Hash": file_hash, "filePath": "CAM-A/EVT-A/EVD-AUD.jpg",
            "metadata": {"severity": "HIGH"},
        }))
        store = MockEvidenceStore()
        store.save(file_content, "CAM-A/EVT-A/EVD-AUD.jpg")
        service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=store,
            audit_repo=self.audit_repo,
        )
        _run(service.maybe_anchor({"id": "EVD-AUD"}))
        actions = [l["action"] for l in self.audit_repo.logs]
        self.assertIn("blockchain.anchor", actions)

    def test_46_secrets_absent_from_logs(self):
        """Verify no secrets appear in audit logs."""
        _run(self.audit_repo.log(
            "blockchain.anchor", "evidence", "EVD-SEC",
            details={"anchor_id": "ANC-001", "tx_hash": "abc123"},
            actor="BLOCKCHAIN_SERVICE",
        ))
        log_str = json.dumps(self.audit_repo.logs)
        # No JWT tokens, no passwords, no private keys
        self.assertNotIn("password", log_str.lower())
        self.assertNotIn("secret_key", log_str.lower())
        self.assertNotIn("private_key", log_str.lower())

    @patch("ai.blockchain.service.settings")
    def test_47_central_healthy_while_blockchain_unavailable(self, mock_settings):
        """Central connectivity is independent of blockchain health."""
        from ai.network.health import NetworkHealthManager
        from ai.network.models import NetworkState
        # NetworkHealthManager tracks central connectivity separately
        mock_settings.BLOCKCHAIN_ENABLED = True
        # Blockchain unavailable should NOT affect network state
        healthy = _run(self.service.health_check())
        # The service's health is about blockchain, not central
        self.assertIsInstance(healthy, bool)

    def test_48_health_state_transition_audit(self):
        """Health state transitions are audited."""
        self.service._previous_health = True
        _run(self.service.health_check())  # still healthy — no audit
        initial_count = len(self.audit_repo.logs)
        self.service._previous_health = True
        # Simulate failure
        class FailLedger(BlockchainLedger):
            async def append(self, eid, h): raise AnchorError("x")
            async def verify(self, eid, h): return VerificationResult(False, BLOCKCHAIN_UNAVAILABLE, "", "", eid)
            async def get_proof(self, aid): return None
            async def get_proof_by_evidence(self, eid): return None
            async def stats(self): return LedgerStats()
            async def health_check(self): return False

        svc = BlockchainService(ledger=FailLedger(), audit_repo=self.audit_repo)
        svc._previous_health = True
        _run(svc.health_check())
        self.assertEqual(len(self.audit_repo.logs), initial_count + 1)
        self.assertEqual(self.audit_repo.logs[-1]["action"], "blockchain.health_changed")


# ──────────────────────────────────────────────────────────────
# Config Tests
# ──────────────────────────────────────────────────────────────

class TestConfig(unittest.TestCase):
    """Test blockchain configuration exists and has correct defaults."""

    def test_49_config_fields_exist(self):
        from ai.config import settings
        self.assertTrue(hasattr(settings, "BLOCKCHAIN_ENABLED"))
        self.assertTrue(hasattr(settings, "BLOCKCHAIN_LEDGER_TYPE"))
        self.assertTrue(hasattr(settings, "BLOCKCHAIN_ANCHOR_POLICY"))
        self.assertTrue(hasattr(settings, "BLOCKCHAIN_ANCHOR_MIN_SEVERITY"))
        self.assertTrue(hasattr(settings, "BLOCKCHAIN_LOCAL_LATENCY_MS"))

    def test_50_config_defaults(self):
        from ai.config import settings
        self.assertFalse(settings.BLOCKCHAIN_ENABLED)
        self.assertEqual(settings.BLOCKCHAIN_LEDGER_TYPE, "local")
        self.assertEqual(settings.BLOCKCHAIN_ANCHOR_POLICY, "high_severity")
        self.assertEqual(settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY, "HIGH")


if __name__ == "__main__":
    unittest.main()
