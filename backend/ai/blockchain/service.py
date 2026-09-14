"""Blockchain service — orchestrates anchoring, verification, and policy evaluation.

This is the application-facing entry point for all blockchain operations.
It wraps a BlockchainLedger instance and adds:
- Configurable anchoring policy (all / high_severity / manual_only)
- Trusted input validation (never trusts client-provided hashes)
- Failure isolation (blockchain failures never stop AI or evidence capture)
- Audit logging integration
- Repository synchronization
"""

import logging
from typing import Optional

from ai.blockchain.exceptions import AnchorError, DuplicateAnchorError
from ai.blockchain.interface import BlockchainLedger
from ai.blockchain.models import (
    AnchorResult, VerificationResult, LedgerStats, ReconciliationResult,
    ANCHOR_STATUS_PENDING, ANCHOR_STATUS_FAILED,
    VERIFIED, DATABASE_HASH_MISMATCH, BLOCKCHAIN_HASH_MISMATCH,
    EVIDENCE_TAMPERED, ANCHOR_NOT_FOUND, BLOCKCHAIN_UNAVAILABLE, VERIFICATION_FAILED,
)
from ai.config import settings

logger = logging.getLogger("ibvap.blockchain.service")


class BlockchainService:
    """Application-facing blockchain orchestrator.

    Responsibilities:
    - Policy evaluation (should this evidence be anchored?)
    - Evidence validation (does evidence exist, is hash valid?)
    - Ledger invocation
    - Failure isolation (never crashes AI pipeline)
    - Audit integration
    """

    def __init__(
        self,
        ledger: BlockchainLedger,
        evidence_repo=None,
        evidence_store=None,
        audit_repo=None,
        sync_repo=None,
        anchor_repo=None,
    ):
        self._ledger = ledger
        self._evidence_repo = evidence_repo
        self._evidence_store = evidence_store
        self._audit_repo = audit_repo
        self._sync_repo = sync_repo
        self._anchor_repo = anchor_repo
        self._previous_health: Optional[bool] = None

    @property
    def enabled(self) -> bool:
        return settings.BLOCKCHAIN_ENABLED

    def _should_anchor(self, evidence_dict: dict) -> bool:
        """Evaluate anchoring policy against an evidence record.

        Returns True if this evidence qualifies for anchoring.
        """
        if not self.enabled:
            return False

        policy = settings.BLOCKCHAIN_ANCHOR_POLICY

        if policy == "manual_only":
            return False

        if policy == "all":
            return True

        if policy == "high_severity":
            metadata = evidence_dict.get("metadata") or {}
            severity = metadata.get("severity", "").upper()
            min_severity = settings.BLOCKCHAIN_ANCHOR_MIN_SEVERITY.upper()
            severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
            return severity_order.get(severity, 0) >= severity_order.get(min_severity, 2)

        # Unknown policy — do not anchor
        logger.warning("[BLOCKCHAIN] Unknown anchor policy: %s", policy)
        return False

    async def _get_trusted_evidence(self, evidence_id: str) -> Optional[dict]:
        """Retrieve evidence from PostgreSQL. Never trust client input."""
        if not self._evidence_repo:
            return None
        return await self._evidence_repo.get(evidence_id)

    async def maybe_anchor(self, evidence_dict: dict) -> Optional[AnchorResult]:
        """Conditionally anchor evidence based on policy.

        Called from EvidenceCapture after persisting evidence.
        Returns AnchorResult on success, None if skipped or failed.
        Never raises exceptions — fully fault-isolated.
        """
        if not self.enabled:
            return None

        evidence_id = evidence_dict.get("id", "")
        if not evidence_id:
            return None

        if not self._should_anchor(evidence_dict):
            return None

        try:
            # Get trusted evidence record from DB
            trusted = await self._get_trusted_evidence(evidence_id)
            if trusted is None:
                logger.warning(
                    "[BLOCKCHAIN] Cannot anchor %s: evidence not found in DB",
                    evidence_id,
                )
                return None

            # Validate stored hash exists
            stored_hash = trusted.get("sha256Hash", "")
            if not stored_hash:
                logger.warning(
                    "[BLOCKCHAIN] Cannot anchor %s: no SHA-256 hash in DB",
                    evidence_id,
                )
                return None

            # If file exists locally, verify hash matches before anchoring
            if self._evidence_store:
                file_path = trusted.get("filePath", "")
                if file_path and self._evidence_store.exists(file_path):
                    file_bytes = self._evidence_store.load(file_path)
                    from ai.evidence.capture import EvidenceCapture
                    actual_hash = EvidenceCapture.compute_sha256(file_bytes)
                    if actual_hash != stored_hash:
                        logger.warning(
                            "[BLOCKCHAIN] Cannot anchor %s: file hash mismatch "
                            "(DB=%s, file=%s)",
                            evidence_id, stored_hash[:12], actual_hash[:12],
                        )
                        await self._audit_log(
                            "blockchain.tamper_detected", "evidence", evidence_id,
                            {"expected": stored_hash, "actual": actual_hash},
                        )
                        return None

            # Submit to ledger
            anchor = await self._ledger.append(evidence_id, stored_hash)

            # Audit
            await self._audit_log(
                "blockchain.anchor", "evidence", evidence_id,
                {"anchor_id": anchor.anchor_id, "tx_hash": anchor.tx_hash},
            )

            return anchor

        except DuplicateAnchorError:
            logger.info("[BLOCKCHAIN] Evidence %s already anchored", evidence_id)
            return None
        except AnchorError as e:
            logger.warning("[BLOCKCHAIN] Anchor failed for %s: %s", evidence_id, e)
            await self._audit_log(
                "blockchain.anchor_failed", "evidence", evidence_id,
                {"error": str(e)},
            )
            return None
        except Exception as e:
            logger.warning("[BLOCKCHAIN] Unexpected error anchoring %s: %s", evidence_id, e)
            return None

    async def verify_evidence(self, evidence_dict: dict) -> VerificationResult:
        """Verify evidence integrity: file -> DB -> blockchain.

        Returns structured VerificationResult with detailed status.
        """
        evidence_id = evidence_dict.get("id", "")
        sha256_hash = evidence_dict.get("sha256Hash", "")

        if not evidence_id or not sha256_hash:
            return VerificationResult(
                verified=False,
                status=VERIFICATION_FAILED,
                local_hash=sha256_hash,
                chain_hash="",
                evidence_id=evidence_id,
            )

        try:
            # Step 1: Get trusted evidence from DB
            trusted = await self._get_trusted_evidence(evidence_id)
            if trusted is None:
                return VerificationResult(
                    verified=False,
                    status=VERIFICATION_FAILED,
                    local_hash=sha256_hash,
                    chain_hash="",
                    evidence_id=evidence_id,
                )

            db_hash = trusted.get("sha256Hash", "")

            # Step 2: Compare provided hash against DB hash
            if sha256_hash != db_hash:
                return VerificationResult(
                    verified=False,
                    status=DATABASE_HASH_MISMATCH,
                    local_hash=sha256_hash,
                    chain_hash=db_hash,
                    evidence_id=evidence_id,
                )

            # Step 2b: Check file integrity if evidence store is available
            if self._evidence_store:
                file_path = trusted.get("filePath", "")
                if file_path and self._evidence_store.exists(file_path):
                    file_bytes = self._evidence_store.load(file_path)
                    from ai.evidence.capture import EvidenceCapture
                    actual_file_hash = EvidenceCapture.compute_sha256(file_bytes)
                    if actual_file_hash != db_hash:
                        await self._audit_log(
                            "blockchain.verify_failed", "evidence", evidence_id,
                            {"reason": "file_tampered", "db_hash": db_hash, "file_hash": actual_file_hash},
                        )
                        return VerificationResult(
                            verified=False,
                            status=EVIDENCE_TAMPERED,
                            local_hash=actual_file_hash,
                            chain_hash=db_hash,
                            evidence_id=evidence_id,
                        )

            # Step 3: Compare against blockchain
            chain_result = await self._ledger.verify(evidence_id, db_hash)

            if chain_result.status == ANCHOR_NOT_FOUND:
                return VerificationResult(
                    verified=False,
                    status=ANCHOR_NOT_FOUND,
                    local_hash=sha256_hash,
                    chain_hash="",
                    evidence_id=evidence_id,
                )

            if chain_result.status == BLOCKCHAIN_UNAVAILABLE:
                return VerificationResult(
                    verified=False,
                    status=BLOCKCHAIN_UNAVAILABLE,
                    local_hash=sha256_hash,
                    chain_hash="",
                    evidence_id=evidence_id,
                )

            if not chain_result.verified:
                return VerificationResult(
                    verified=False,
                    status=BLOCKCHAIN_HASH_MISMATCH,
                    local_hash=sha256_hash,
                    chain_hash=chain_result.chain_hash,
                    evidence_id=evidence_id,
                    anchor_id=chain_result.anchor_id,
                )

            # All checks passed
            return VerificationResult(
                verified=True,
                status=VERIFIED,
                local_hash=sha256_hash,
                chain_hash=chain_result.chain_hash,
                evidence_id=evidence_id,
                anchor_id=chain_result.anchor_id,
            )

        except Exception as e:
            logger.warning("[BLOCKCHAIN] Verify failed for %s: %s", evidence_id, e)
            return VerificationResult(
                verified=False,
                status=VERIFICATION_FAILED,
                local_hash=sha256_hash,
                chain_hash="",
                evidence_id=evidence_id,
            )

    async def get_evidence_anchor(self, evidence_id: str) -> Optional[AnchorResult]:
        """Get the blockchain anchor for a specific evidence record."""
        try:
            return await self._ledger.get_proof_by_evidence(evidence_id)
        except Exception as e:
            logger.warning("[BLOCKCHAIN] get_evidence_anchor failed: %s", e)
            return None

    async def health_check(self) -> bool:
        """Check ledger health. Tracks state transitions for audit."""
        try:
            healthy = await self._ledger.health_check()

            if self._previous_health is not None and healthy != self._previous_health:
                await self._audit_log(
                    "blockchain.health_changed", "blockchain", "ledger",
                    {"healthy": healthy},
                )

            self._previous_health = healthy
            return healthy

        except Exception:
            self._previous_health = False
            return False

    async def get_stats(self) -> LedgerStats:
        """Get aggregate ledger statistics."""
        try:
            return await self._ledger.stats()
        except Exception:
            return LedgerStats()

    async def _audit_log(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict = None,
    ):
        """Fire-and-forget audit log."""
        try:
            if self._audit_repo:
                await self._audit_repo.log(
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    details=details,
                    actor="BLOCKCHAIN_SERVICE",
                )
        except Exception:
            pass

    async def reconcile_anchor(self, anchor_id: str) -> ReconciliationResult:
        """Compare PostgreSQL anchor metadata against ledger proof.

        Authoritative identity/proof fields drive the matched flag.
        Status is operational metadata — reported but not cryptographic failure.
        """
        pg_anchor = await self._anchor_repo.get_by_id(anchor_id) if self._anchor_repo else None
        if not pg_anchor:
            return ReconciliationResult(matched=False, mismatches=["anchor_not_found_in_db"])

        ledger_proof = await self._ledger.get_proof(anchor_id)
        if not ledger_proof:
            return ReconciliationResult(matched=False, mismatches=["anchor_not_found_in_ledger"])

        mismatches = []
        if pg_anchor.get("sha256Hash", "") != ledger_proof.sha256_hash:
            mismatches.append("sha256_hash")
        if pg_anchor.get("recordHash", "") != ledger_proof.record_hash:
            mismatches.append("record_hash")
        if pg_anchor.get("txHash", "") != ledger_proof.tx_hash:
            mismatches.append("tx_hash")
        if pg_anchor.get("blockNumber", 0) != ledger_proof.block_number:
            mismatches.append("block_number")

        if pg_anchor.get("status", "") != ledger_proof.status:
            mismatches.append("status")

        return ReconciliationResult(matched=len(mismatches) == 0, mismatches=mismatches)
