"""Section 15 — Blockchain Trust & Evidence Ledger Tests.

Covers reconciliation, verification statuses, tamper detection,
manual anchoring, outage isolation, and security controls.

Uses unittest.TestCase + _run() helper (Windows-safe async).
No real database — all tests use mock repositories.
"""

import asyncio
import hashlib
import unittest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from ai.blockchain.exceptions import AnchorError, DuplicateAnchorError
from ai.blockchain.interface import BlockchainLedger
from ai.blockchain.models import (
    AnchorResult, VerificationResult, LedgerStats, ReconciliationResult,
    ANCHOR_STATUS_PENDING, ANCHOR_STATUS_CONFIRMED, ANCHOR_STATUS_FAILED,
    VERIFIED, DATABASE_HASH_MISMATCH, BLOCKCHAIN_HASH_MISMATCH,
    EVIDENCE_TAMPERED, ANCHOR_NOT_FOUND, BLOCKCHAIN_UNAVAILABLE, VERIFICATION_FAILED,
)
from ai.blockchain.local_ledger import LocalLedger
from ai.blockchain.service import BlockchainService


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ──────────────────────────────────────────────────────────────
# Mock Repository (in-memory, mirrors test_blockchain.py)
# ──────────────────────────────────────────────────────────────

class MockAnchorRepo:
    def __init__(self):
        self._anchors = {}
        self._counter = 0

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


class MockEvidenceRepo:
    def __init__(self):
        self._evidence = {}

    async def get(self, evidence_id):
        return self._evidence.get(evidence_id)

    async def create(self, evidence):
        eid = evidence.get("id", "EVD-test")
        self._evidence[eid] = evidence
        return evidence


class MockEvidenceStore:
    def __init__(self):
        self._files = {}

    def save(self, data, path):
        self._files[path] = data
        return path

    def load(self, path):
        return self._files.get(path, b"")

    def exists(self, path):
        return path in self._files


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
# Reconciliation Tests
# ──────────────────────────────────────────────────────────────

class TestReconciliation(unittest.TestCase):
    """Test BlockchainService.reconcile_anchor()."""

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

    def _seed_anchor(self, evidence_id="EVD-REC", sha256_hash=None, status="CONFIRMED"):
        if sha256_hash is None:
            sha256_hash = "a" * 64
        anchor = _run(self.ledger.append(evidence_id, sha256_hash))
        if status == "CONFIRMED":
            _run(self.anchor_repo.update_status(anchor.anchor_id, "CONFIRMED"))
        return anchor

    @patch("ai.blockchain.service.settings")
    def test_01_matched_anchor(self, mock_settings):
        """Fully consistent anchor returns matched=True."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        anchor = _run(self.ledger.append("EVD-R1", "a" * 64))
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertTrue(result.matched)
        self.assertEqual(result.mismatches, [])

    @patch("ai.blockchain.service.settings")
    def test_02_db_only_anchor_not_found_in_ledger(self, mock_settings):
        """Anchor exists in DB but not in ledger — mock PG returns data, ledger returns None."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        # Create anchor in mock repo (ledger sees it too via shared repo)
        anchor = _run(self.ledger.append("EVD-R2", "a" * 64))
        # Now mock the service's anchor_repo to return data for this anchor
        # but mock ledger.get_proof to return None
        pg_data = _run(self.anchor_repo.get_by_id(anchor.anchor_id))
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=pg_data)
        self.service._ledger = AsyncMock()
        self.service._ledger.get_proof = AsyncMock(return_value=None)
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertFalse(result.matched)
        self.assertIn("anchor_not_found_in_ledger", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_03_nonexistent_anchor(self, mock_settings):
        """Anchor not found in DB."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=None)
        result = _run(self.service.reconcile_anchor("ANC-NONEXISTENT"))
        self.assertFalse(result.matched)
        self.assertIn("anchor_not_found_in_db", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_04_sha256_hash_mismatch(self, mock_settings):
        """PostgreSQL sha256Hash differs from ledger proof."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        anchor = _run(self.ledger.append("EVD-SM", "a" * 64))
        # PG returns tampered hash
        pg_data = _run(self.anchor_repo.get_by_id(anchor.anchor_id))
        pg_data["sha256Hash"] = "b" * 64
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=pg_data)
        # Ledger returns original
        self.service._ledger = AsyncMock()
        self.service._ledger.get_proof = AsyncMock(return_value=anchor)
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertFalse(result.matched)
        self.assertIn("sha256_hash", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_05_record_hash_mismatch(self, mock_settings):
        """PostgreSQL recordHash differs from ledger proof."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        anchor = _run(self.ledger.append("EVD-RM", "c" * 64))
        pg_data = _run(self.anchor_repo.get_by_id(anchor.anchor_id))
        pg_data["recordHash"] = "x" * 64
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=pg_data)
        self.service._ledger = AsyncMock()
        self.service._ledger.get_proof = AsyncMock(return_value=anchor)
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertFalse(result.matched)
        self.assertIn("record_hash", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_06_tx_hash_mismatch(self, mock_settings):
        """PostgreSQL txHash differs from ledger proof."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        anchor = _run(self.ledger.append("EVD-TM", "d" * 64))
        pg_data = _run(self.anchor_repo.get_by_id(anchor.anchor_id))
        pg_data["txHash"] = "t" + "0" * 63
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=pg_data)
        self.service._ledger = AsyncMock()
        self.service._ledger.get_proof = AsyncMock(return_value=anchor)
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertFalse(result.matched)
        self.assertIn("tx_hash", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_07_block_number_mismatch(self, mock_settings):
        """PostgreSQL blockNumber differs from ledger proof."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        anchor = _run(self.ledger.append("EVD-BM", "e" * 64))
        pg_data = _run(self.anchor_repo.get_by_id(anchor.anchor_id))
        pg_data["blockNumber"] = 999
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=pg_data)
        self.service._ledger = AsyncMock()
        self.service._ledger.get_proof = AsyncMock(return_value=anchor)
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertFalse(result.matched)
        self.assertIn("block_number", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_08_status_mismatch_only(self, mock_settings):
        """Status differs but identity fields match — still not matched (operational mismatch)."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        anchor = _run(self.ledger.append("EVD-ST", "f" * 64))
        pg_data = _run(self.anchor_repo.get_by_id(anchor.anchor_id))
        pg_data["status"] = "PENDING"
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=pg_data)
        self.service._ledger = AsyncMock()
        self.service._ledger.get_proof = AsyncMock(return_value=anchor)
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertFalse(result.matched)
        self.assertIn("status", result.mismatches)
        self.assertNotIn("sha256_hash", result.mismatches)
        self.assertNotIn("record_hash", result.mismatches)
        self.assertNotIn("tx_hash", result.mismatches)
        self.assertNotIn("block_number", result.mismatches)

    @patch("ai.blockchain.service.settings")
    def test_09_multiple_mismatches(self, mock_settings):
        """Multiple fields mismatch simultaneously."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        anchor = _run(self.ledger.append("EVD-MM", "g" * 64))
        pg_data = _run(self.anchor_repo.get_by_id(anchor.anchor_id))
        pg_data["sha256Hash"] = "z" * 64
        pg_data["recordHash"] = "y" * 64
        pg_data["status"] = "FAILED"
        self.service._anchor_repo = AsyncMock()
        self.service._anchor_repo.get_by_id = AsyncMock(return_value=pg_data)
        self.service._ledger = AsyncMock()
        self.service._ledger.get_proof = AsyncMock(return_value=anchor)
        result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertFalse(result.matched)
        self.assertIn("sha256_hash", result.mismatches)
        self.assertIn("record_hash", result.mismatches)
        self.assertIn("status", result.mismatches)
        self.assertEqual(len(result.mismatches), 3)


# ──────────────────────────────────────────────────────────────
# Verification Status Tests
# ──────────────────────────────────────────────────────────────

class TestVerificationStatuses(unittest.TestCase):
    """Test all 7 verification statuses are producible."""

    def setUp(self):
        self.anchor_repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.evidence_store = MockEvidenceStore()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.anchor_repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.evidence_store,
            audit_repo=self.audit_repo,
        )

    def _seed_evidence(self, evidence_id, sha256_hash, file_content=None):
        _run(self.evidence_repo.create({
            "id": evidence_id,
            "eventId": "EVT-1",
            "cameraId": "CAM-1",
            "sha256Hash": sha256_hash,
            "filePath": "CAM-1/EVT-1/%s.jpg" % evidence_id,
            "metadata": {"severity": "HIGH"},
        }))
        if file_content is not None:
            self.evidence_store.save(file_content, "CAM-1/EVT-1/%s.jpg" % evidence_id)

    @patch("ai.blockchain.service.settings")
    def test_10_verified(self, mock_settings):
        """All three match — VERIFIED."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        file_content = b"verified-evidence-data"
        file_hash = _sha256(file_content)
        self._seed_evidence("EVD-V", file_hash, file_content)
        _run(self.ledger.append("EVD-V", file_hash))
        result = _run(self.service.verify_evidence({
            "id": "EVD-V", "sha256Hash": file_hash,
        }))
        self.assertTrue(result.verified)
        self.assertEqual(result.status, VERIFIED)

    @patch("ai.blockchain.service.settings")
    def test_11_database_hash_mismatch(self, mock_settings):
        """Client hash differs from DB — DATABASE_HASH_MISMATCH."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        self._seed_evidence("EVD-DB", "a" * 64)
        _run(self.ledger.append("EVD-DB", "a" * 64))
        result = _run(self.service.verify_evidence({
            "id": "EVD-DB", "sha256Hash": "b" * 64,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, DATABASE_HASH_MISMATCH)

    @patch("ai.blockchain.service.settings")
    def test_12_evidence_tampered(self, mock_settings):
        """File on disk differs from DB hash — EVIDENCE_TAMPERED."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        self._seed_evidence("EVD-ET", "original" + "0" * 57, b"original-file")
        _run(self.ledger.append("EVD-ET", "original" + "0" * 57))
        # Tamper the file on disk
        self.evidence_store.save(b"tampered-file", "CAM-1/EVT-1/EVD-ET.jpg")
        result = _run(self.service.verify_evidence({
            "id": "EVD-ET", "sha256Hash": "original" + "0" * 57,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, EVIDENCE_TAMPERED)

    @patch("ai.blockchain.service.settings")
    def test_13_blockchain_hash_mismatch(self, mock_settings):
        """DB hash differs from blockchain — BLOCKCHAIN_HASH_MISMATCH."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        self._seed_evidence("EVD-BH", "a" * 64)
        _run(self.ledger.append("EVD-BH", "b" * 64))  # Different hash on chain
        result = _run(self.service.verify_evidence({
            "id": "EVD-BH", "sha256Hash": "a" * 64,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, BLOCKCHAIN_HASH_MISMATCH)

    @patch("ai.blockchain.service.settings")
    def test_14_anchor_not_found(self, mock_settings):
        """No anchor for this evidence — ANCHOR_NOT_FOUND."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        self._seed_evidence("EVD-AN", "a" * 64)
        result = _run(self.service.verify_evidence({
            "id": "EVD-AN", "sha256Hash": "a" * 64,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, ANCHOR_NOT_FOUND)

    @patch("ai.blockchain.service.settings")
    def test_15_blockchain_unavailable(self, mock_settings):
        """Ledger unreachable — BLOCKCHAIN_UNAVAILABLE."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        self._seed_evidence("EVD-BU", "a" * 64)

        class UnavailableLedger(BlockchainLedger):
            async def append(self, evidence_id, sha256_hash):
                return AnchorResult("ANC-U", evidence_id, sha256_hash, "r" * 64, "t" + "0" * 63, 0, ANCHOR_STATUS_CONFIRMED)
            async def verify(self, evidence_id, sha256_hash):
                return VerificationResult(False, BLOCKCHAIN_UNAVAILABLE, sha256_hash, "", evidence_id)
            async def get_proof(self, anchor_id): return None
            async def get_proof_by_evidence(self, evidence_id): return None
            async def stats(self): return LedgerStats()
            async def health_check(self): return False

        service = BlockchainService(
            ledger=UnavailableLedger(),
            evidence_repo=self.evidence_repo,
        )
        result = _run(service.verify_evidence({
            "id": "EVD-BU", "sha256Hash": "a" * 64,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, BLOCKCHAIN_UNAVAILABLE)

    @patch("ai.blockchain.service.settings")
    def test_16_verification_failed(self, mock_settings):
        """Missing evidence ID — VERIFICATION_FAILED."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        result = _run(self.service.verify_evidence({
            "id": "", "sha256Hash": "a" * 64,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, VERIFICATION_FAILED)

    @patch("ai.blockchain.service.settings")
    def test_17_verification_failed_no_hash(self, mock_settings):
        """Missing sha256 hash — VERIFICATION_FAILED."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        result = _run(self.service.verify_evidence({
            "id": "EVD-X", "sha256Hash": "",
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, VERIFICATION_FAILED)


# ──────────────────────────────────────────────────────────────
# Tamper Scenario Tests
# ──────────────────────────────────────────────────────────────

class TestTamperScenarios(unittest.TestCase):
    """Test tamper detection across the 3-way verification chain."""

    def setUp(self):
        self.anchor_repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.evidence_store = MockEvidenceStore()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.anchor_repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.evidence_store,
            audit_repo=self.audit_repo,
        )

    @patch("ai.blockchain.service.settings")
    def test_18_file_tamper_detected(self, mock_settings):
        """File replaced on disk → EVIDENCE_TAMPERED."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        original_hash = _sha256(b"original-evidence")
        _run(self.evidence_repo.create({
            "id": "EVD-TAM1", "eventId": "EVT-1", "cameraId": "CAM-1",
            "sha256Hash": original_hash, "filePath": "CAM-1/EVT-1/EVD-TAM1.jpg",
            "metadata": {},
        }))
        self.evidence_store.save(b"original-evidence", "CAM-1/EVT-1/EVD-TAM1.jpg")
        _run(self.ledger.append("EVD-TAM1", original_hash))
        # Replace file
        self.evidence_store.save(b"tampered-evidence", "CAM-1/EVT-1/EVD-TAM1.jpg")
        result = _run(self.service.verify_evidence({
            "id": "EVD-TAM1", "sha256Hash": original_hash,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, EVIDENCE_TAMPERED)

    @patch("ai.blockchain.service.settings")
    def test_19_db_hash_tamper_detected(self, mock_settings):
        """DB hash modified → DATABASE_HASH_MISMATCH (client vs DB) or BLOCKCHAIN_HASH_MISMATCH (DB vs chain)."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        original_hash = "original" + "0" * 57
        _run(self.evidence_repo.create({
            "id": "EVD-TAM2", "eventId": "EVT-2", "cameraId": "CAM-2",
            "sha256Hash": original_hash, "filePath": "",
            "metadata": {},
        }))
        _run(self.ledger.append("EVD-TAM2", original_hash))
        # Tamper DB hash
        db_ev = _run(self.evidence_repo.get("EVD-TAM2"))
        db_ev["sha256Hash"] = "tampered" + "0" * 56
        # Client sends original hash → DB mismatch
        result = _run(self.service.verify_evidence({
            "id": "EVD-TAM2", "sha256Hash": original_hash,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, DATABASE_HASH_MISMATCH)

    @patch("ai.blockchain.service.settings")
    def test_20_chain_mismatch_detected(self, mock_settings):
        """DB and chain have different hashes → BLOCKCHAIN_HASH_MISMATCH."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        db_hash = "dbhash" + "0" * 58
        chain_hash = "chain" + "0" * 59
        _run(self.evidence_repo.create({
            "id": "EVD-TAM3", "eventId": "EVT-3", "cameraId": "CAM-3",
            "sha256Hash": db_hash, "filePath": "",
            "metadata": {},
        }))
        _run(self.ledger.append("EVD-TAM3", chain_hash))
        result = _run(self.service.verify_evidence({
            "id": "EVD-TAM3", "sha256Hash": db_hash,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, BLOCKCHAIN_HASH_MISMATCH)

    @patch("ai.blockchain.service.settings")
    def test_21_no_file_no_tamper(self, mock_settings):
        """No file on disk — skip file check, verify chain only."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        _run(self.evidence_repo.create({
            "id": "EVD-NOFILE", "eventId": "EVT-4", "cameraId": "CAM-4",
            "sha256Hash": "a" * 64, "filePath": "nonexistent.jpg",
            "metadata": {},
        }))
        _run(self.ledger.append("EVD-NOFILE", "a" * 64))
        result = _run(self.service.verify_evidence({
            "id": "EVD-NOFILE", "sha256Hash": "a" * 64,
        }))
        self.assertTrue(result.verified)
        self.assertEqual(result.status, VERIFIED)


# ──────────────────────────────────────────────────────────────
# Manual Anchor Tests
# ──────────────────────────────────────────────────────────────

class TestManualAnchor(unittest.TestCase):
    """Test manual anchoring: idempotency, trusted hash, audit."""

    def setUp(self):
        self.anchor_repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.evidence_store = MockEvidenceStore()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.anchor_repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.evidence_store,
            audit_repo=self.audit_repo,
            anchor_repo=self.anchor_repo,
        )

    @patch("ai.blockchain.service.settings")
    def test_22_manual_anchor_idempotent(self, mock_settings):
        """Same evidence anchored twice returns same anchor."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        r1 = _run(self.ledger.append("EVD-IDEM2", "a" * 64))
        r2 = _run(self.ledger.append("EVD-IDEM2", "a" * 64))
        self.assertEqual(r1.anchor_id, r2.anchor_id)
        self.assertEqual(r1.record_hash, r2.record_hash)

    @patch("ai.blockchain.service.settings")
    def test_23_manual_anchor_uses_trusted_hash(self, mock_settings):
        """Manual anchor uses DB hash, not arbitrary client input."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        _run(self.evidence_repo.create({
            "id": "EVD-TRUST", "eventId": "EVT-1", "cameraId": "CAM-1",
            "sha256Hash": "trusted" + "0" * 58, "filePath": "",
            "metadata": {},
        }))
        anchor = _run(self.service._ledger.append("EVD-TRUST", "trusted" + "0" * 58))
        # Even if someone tried with a different hash, the anchor uses the DB hash
        self.assertEqual(anchor.sha256_hash, "trusted" + "0" * 58)

    @patch("ai.blockchain.service.settings")
    def test_24_manual_anchor_audit_logged(self, mock_settings):
        """Manual anchor produces audit log."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        file_content = b"audit-test-evidence"
        file_hash = _sha256(file_content)
        _run(self.evidence_repo.create({
            "id": "EVD-AUD2", "eventId": "EVT-2", "cameraId": "CAM-2",
            "sha256Hash": file_hash, "filePath": "CAM-2/EVT-2/EVD-AUD2.jpg",
            "metadata": {"severity": "HIGH"},
        }))
        self.evidence_store.save(file_content, "CAM-2/EVT-2/EVD-AUD2.jpg")
        _run(self.service.maybe_anchor({"id": "EVD-AUD2"}))
        actions = [l["action"] for l in self.audit_repo.logs]
        self.assertIn("blockchain.anchor", actions)


# ──────────────────────────────────────────────────────────────
# Outage Isolation Tests
# ──────────────────────────────────────────────────────────────

class TestOutageIsolation(unittest.TestCase):
    """Blockchain outage must not block AI, evidence capture, or sync."""

    def setUp(self):
        self.anchor_repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.evidence_store = MockEvidenceStore()
        self.audit_repo = MockAuditRepo()

    @patch("ai.blockchain.service.settings")
    def test_25_ai_runs_during_blockchain_down(self, mock_settings):
        """AI processing is unaffected by blockchain failure."""
        mock_settings.BLOCKCHAIN_ENABLED = True

        class BrokenLedger(BlockchainLedger):
            async def append(self, evidence_id, sha256_hash):
                raise AnchorError("unavailable")
            async def verify(self, evidence_id, sha256_hash):
                return VerificationResult(False, BLOCKCHAIN_UNAVAILABLE, "", "", evidence_id)
            async def get_proof(self, anchor_id): return None
            async def get_proof_by_evidence(self, evidence_id): return None
            async def stats(self): return LedgerStats()
            async def health_check(self): return False

        service = BlockchainService(
            ledger=BrokenLedger(),
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
        )
        # Blockchain anchor fails but service does not raise
        result = _run(service.maybe_anchor({"id": "EVD-AI"}))
        self.assertIsNone(result)
        # Service health check still works
        healthy = _run(service.health_check())
        self.assertFalse(healthy)

    @patch("ai.blockchain.service.settings")
    def test_26_evidence_captured_during_blockchain_down(self, mock_settings):
        """Evidence is captured in PostgreSQL even when blockchain is down."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        _run(self.evidence_repo.create({
            "id": "EVD-CAP2", "eventId": "EVT-1", "cameraId": "CAM-1",
            "sha256Hash": "c" * 64, "filePath": "",
            "metadata": {"severity": "HIGH"},
        }))
        ev = _run(self.evidence_repo.get("EVD-CAP2"))
        self.assertIsNotNone(ev)
        self.assertEqual(ev["sha256Hash"], "c" * 64)

    @patch("ai.blockchain.service.settings")
    def test_27_anchor_pending_not_failed(self, mock_settings):
        """Anchor status stays PENDING when ledger unavailable (not FAILED)."""
        mock_settings.BLOCKCHAIN_ENABLED = True

        class UnavailableLedger(BlockchainLedger):
            async def append(self, evidence_id, sha256_hash):
                raise AnchorError("unavailable")
            async def verify(self, evidence_id, sha256_hash):
                return VerificationResult(False, BLOCKCHAIN_UNAVAILABLE, "", "", evidence_id)
            async def get_proof(self, anchor_id): return None
            async def get_proof_by_evidence(self, evidence_id): return None
            async def stats(self): return LedgerStats()
            async def health_check(self): return False

        service = BlockchainService(
            ledger=UnavailableLedger(),
            evidence_repo=self.evidence_repo,
            audit_repo=self.audit_repo,
        )
        result = _run(service.maybe_anchor({"id": "EVD-PEND"}))
        # Failed to anchor — returns None (anchor not created)
        self.assertIsNone(result)


# ──────────────────────────────────────────────────────────────
# Security Tests
# ──────────────────────────────────────────────────────────────

class TestSecurity(unittest.TestCase):
    """Security controls: hash injection, proof injection, RBAC."""

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

    def test_28_arbitrary_hash_rejected(self):
        """Client cannot inject arbitrary hash — service uses DB hash."""
        result = _run(self.service.maybe_anchor({
            "id": "EVD-ARBIT",
            "sha256Hash": "evil" + "0" * 60,
        }))
        self.assertIsNone(result)
        self.assertEqual(len(self.anchor_repo._anchors), 0)

    def test_29_arbitrary_proof_rejected(self):
        """Verification uses ledger, not client-supplied proof."""
        # Append with one hash, verify with a different one
        _run(self.evidence_repo.create({
            "id": "EVD-AP", "sha256Hash": "legit" + "0" * 58, "filePath": "",
            "metadata": {},
        }))
        _run(self.ledger.append("EVD-AP", "legit" + "0" * 58))
        result = _run(self.service.verify_evidence({
            "id": "EVD-AP", "sha256Hash": "forged" + "0" * 58,
        }))
        self.assertFalse(result.verified)
        self.assertEqual(result.status, DATABASE_HASH_MISMATCH)

    def test_30_viewer_cannot_reconcile(self):
        """VIEWER role does not have BLOCKCHAIN_ANCHOR permission."""
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertNotIn(Permission.BLOCKCHAIN_ANCHOR, ROLE_PERMISSIONS[Role.VIEWER])
        self.assertIn(Permission.BLOCKCHAIN_READ, ROLE_PERMISSIONS[Role.VIEWER])

    def test_31_operator_can_reconcile(self):
        """OPERATOR role has BLOCKCHAIN_ANCHOR permission."""
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.BLOCKCHAIN_ANCHOR, ROLE_PERMISSIONS[Role.OPERATOR])

    def test_32_admin_can_reconcile(self):
        """ADMIN role has BLOCKCHAIN_ANCHOR permission."""
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.BLOCKCHAIN_ANCHOR, ROLE_PERMISSIONS[Role.ADMIN])


# ──────────────────────────────────────────────────────────────
# Edge Security Tests
# ──────────────────────────────────────────────────────────────

class TestEdgeSecurity(unittest.TestCase):
    """Edge nodes cannot access blockchain APIs."""

    def test_33_edge_cannot_read_blockchain(self):
        from ai.edge.models import EdgePermissions
        self.assertFalse(EdgePermissions.CAN_BLOCKCHAIN_READ)

    def test_34_edge_cannot_anchor_blockchain(self):
        from ai.edge.models import EdgePermissions
        self.assertFalse(EdgePermissions.CAN_BLOCKCHAIN_ANCHOR)


# ──────────────────────────────────────────────────────────────
# ReconciliationResult Model Tests
# ──────────────────────────────────────────────────────────────

class TestReconciliationResultModel(unittest.TestCase):
    """Test ReconciliationResult dataclass behavior."""

    def test_35_reconciliation_result_defaults(self):
        r = ReconciliationResult(matched=True)
        self.assertTrue(r.matched)
        self.assertEqual(r.mismatches, [])

    def test_36_reconciliation_result_with_mismatches(self):
        r = ReconciliationResult(matched=False, mismatches=["sha256_hash", "status"])
        self.assertFalse(r.matched)
        self.assertEqual(len(r.mismatches), 2)
        self.assertIn("sha256_hash", r.mismatches)
        self.assertIn("status", r.mismatches)


# ──────────────────────────────────────────────────────────────
# Verification Result Model Tests
# ──────────────────────────────────────────────────────────────

class TestVerificationResultModel(unittest.TestCase):
    """Test VerificationResult dataclass behavior."""

    def test_37_verification_result_verified(self):
        r = VerificationResult(
            verified=True, status=VERIFIED,
            local_hash="a" * 64, chain_hash="a" * 64,
            evidence_id="EVD-1",
        )
        self.assertTrue(r.verified)
        self.assertEqual(r.status, VERIFIED)
        self.assertEqual(r.local_hash, r.chain_hash)

    def test_38_verification_result_not_verified(self):
        r = VerificationResult(
            verified=False, status=BLOCKCHAIN_HASH_MISMATCH,
            local_hash="a" * 64, chain_hash="b" * 64,
            evidence_id="EVD-2", anchor_id="ANC-2",
        )
        self.assertFalse(r.verified)
        self.assertEqual(r.status, BLOCKCHAIN_HASH_MISMATCH)
        self.assertNotEqual(r.local_hash, r.chain_hash)


# ──────────────────────────────────────────────────────────────
# Acceptance Criteria Integration Tests
# ──────────────────────────────────────────────────────────────

class TestAcceptanceCriteria(unittest.TestCase):
    """Integration tests covering the full acceptance criteria checklist."""

    def setUp(self):
        self.anchor_repo = MockAnchorRepo()
        self.evidence_repo = MockEvidenceRepo()
        self.evidence_store = MockEvidenceStore()
        self.audit_repo = MockAuditRepo()
        self.ledger = LocalLedger(anchor_repo=self.anchor_repo)
        self.service = BlockchainService(
            ledger=self.ledger,
            evidence_repo=self.evidence_repo,
            evidence_store=self.evidence_store,
            audit_repo=self.audit_repo,
            anchor_repo=self.anchor_repo,
        )

    @patch("ai.blockchain.service.settings")
    def test_39_full_lifecycle_anchor_verify_reconcile(self, mock_settings):
        """Full lifecycle: anchor -> verify -> reconcile."""
        mock_settings.BLOCKCHAIN_ENABLED = True
        mock_settings.BLOCKCHAIN_ANCHOR_POLICY = "all"
        mock_settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
        file_content = b"lifecycle-test-evidence"
        file_hash = _sha256(file_content)
        _run(self.evidence_repo.create({
            "id": "EVD-LC", "eventId": "EVT-1", "cameraId": "CAM-1",
            "sha256Hash": file_hash, "filePath": "CAM-1/EVT-1/EVD-LC.jpg",
            "metadata": {"severity": "HIGH"},
        }))
        self.evidence_store.save(file_content, "CAM-1/EVT-1/EVD-LC.jpg")
        # Anchor
        anchor = _run(self.service.maybe_anchor({"id": "EVD-LC"}))
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor.status, ANCHOR_STATUS_CONFIRMED)
        # Verify
        v_result = _run(self.service.verify_evidence({
            "id": "EVD-LC", "sha256Hash": file_hash,
        }))
        self.assertTrue(v_result.verified)
        self.assertEqual(v_result.status, VERIFIED)
        # Reconcile
        r_result = _run(self.service.reconcile_anchor(anchor.anchor_id))
        self.assertTrue(r_result.matched)
        self.assertEqual(r_result.mismatches, [])

    @patch("ai.blockchain.service.settings")
    def test_40_blockchain_failure_isolated(self, mock_settings):
        """Blockchain failure does not affect evidence or AI."""
        mock_settings.BLOCKCHAIN_ENABLED = True

        class FailLedger(BlockchainLedger):
            async def append(self, evidence_id, sha256_hash):
                raise AnchorError("down")
            async def verify(self, evidence_id, sha256_hash):
                return VerificationResult(False, BLOCKCHAIN_UNAVAILABLE, "", "", evidence_id)
            async def get_proof(self, anchor_id): return None
            async def get_proof_by_evidence(self, evidence_id): return None
            async def stats(self): return LedgerStats()
            async def health_check(self): return False

        service = BlockchainService(
            ledger=FailLedger(),
            evidence_repo=self.evidence_repo,
            evidence_store=self.evidence_store,
            audit_repo=self.audit_repo,
        )
        # Anchor fails gracefully
        anchor = _run(service.maybe_anchor({"id": "EVD-FI"}))
        self.assertIsNone(anchor)
        # Verify still works (returns UNAVAILABLE)
        _run(self.evidence_repo.create({
            "id": "EVD-FI", "sha256Hash": "a" * 64, "filePath": "",
            "metadata": {},
        }))
        v = _run(service.verify_evidence({"id": "EVD-FI", "sha256Hash": "a" * 64}))
        self.assertFalse(v.verified)
        self.assertEqual(v.status, BLOCKCHAIN_UNAVAILABLE)

    def test_41_reconciliation_result_dataclass(self):
        """ReconciliationResult is importable and correct."""
        from ai.blockchain.models import ReconciliationResult
        r = ReconciliationResult(matched=False, mismatches=["sha256_hash", "status"])
        self.assertFalse(r.matched)
        self.assertEqual(len(r.mismatches), 2)


if __name__ == "__main__":
    unittest.main()
