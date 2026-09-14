"""Local development blockchain ledger adapter.

DEVELOPMENT/TESTING/CI ONLY — NOT a production distributed blockchain.

Implements deterministic SHA-256 chaining for local trust records.
Each record's previous_hash chains to the prior record's record_hash,
creating a tamper-evident sequence.

This adapter persists via the BlockchainAnchorRepository (PostgreSQL),
ensuring the database remains the single source of truth.
"""

import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from ai.blockchain.exceptions import (
    AnchorError, DuplicateAnchorError, LedgerUnavailableError,
)
from ai.blockchain.interface import BlockchainLedger
from ai.blockchain.models import (
    AnchorResult, VerificationResult, LedgerStats,
    ANCHOR_STATUS_CONFIRMED, ANCHOR_STATUS_FAILED,
    VERIFIED, ANCHOR_NOT_FOUND, BLOCKCHAIN_HASH_MISMATCH, BLOCKCHAIN_UNAVAILABLE,
)
from ai.blockchain.repository import BlockchainAnchorRepository

logger = logging.getLogger("ibvap.blockchain.local")

# Ledger record version — for future schema evolution
_RECORD_VERSION = "1.0"


def _compute_record_hash(canonical_data: str) -> str:
    """Compute SHA-256 of a canonical record string."""
    return hashlib.sha256(canonical_data.encode("utf-8")).hexdigest()


def _canonical_record(
    version: str,
    evidence_id: str,
    evidence_sha256: str,
    previous_hash: str,
    timestamp: str,
) -> str:
    """Build deterministic canonical record string.

    Field ordering is explicit and versioned.
    Do NOT hash unordered dictionaries.
    """
    return json.dumps(
        {
            "version": version,
            "evidence_id": evidence_id,
            "evidence_sha256": evidence_sha256,
            "previous_hash": previous_hash,
            "timestamp": timestamp,
        },
        sort_keys=False,
        separators=(",", ":"),
    )


class LocalLedger(BlockchainLedger):
    """Development blockchain ledger backed by PostgreSQL via repository.

    Each append creates a new blockchain_anchors row with:
    - Deterministic record_hash from canonical serialization
    - previous_hash chaining to the prior anchor's record_hash
    - Simulated block_number (monotonically increasing)
    - Idempotent: duplicate evidence_id returns existing anchor

    The repository IS the persistence layer. No in-memory state
    is relied upon for correctness.
    """

    def __init__(
        self,
        anchor_repo: Optional[BlockchainAnchorRepository] = None,
        simulated_latency_ms: float = 0.0,
    ):
        self._repo = anchor_repo or BlockchainAnchorRepository()
        self._simulated_latency_ms = simulated_latency_ms

    async def append(
        self,
        evidence_id: str,
        sha256_hash: str,
    ) -> AnchorResult:
        """Anchor an evidence hash to the local ledger.

        Idempotent: if evidence_id already has a confirmed/pending anchor,
        returns the existing anchor.

        Args:
            evidence_id: Unique evidence identifier.
            sha256_hash: SHA-256 hex digest of the evidence file.

        Returns:
            AnchorResult with ledger details.

        Raises:
            AnchorError: If anchoring fails.
        """
        try:
            # Simulated network latency (testing only)
            if self._simulated_latency_ms > 0:
                await _async_sleep(self._simulated_latency_ms / 1000.0)

            # Idempotency check
            existing = await self._repo.get_by_evidence(evidence_id)
            if existing and existing["status"] in (ANCHOR_STATUS_CONFIRMED, "PENDING"):
                logger.info(
                    "[LOCAL LEDGER] Evidence %s already anchored (anchor=%s)",
                    evidence_id, existing["anchorId"],
                )
                return AnchorResult(
                    anchor_id=existing["anchorId"],
                    evidence_id=evidence_id,
                    sha256_hash=existing["sha256Hash"],
                    record_hash=existing["recordHash"],
                    tx_hash=existing["txHash"],
                    block_number=existing["blockNumber"],
                    status=existing["status"],
                    timestamp=existing["createdAt"] or "",
                    confirmation_time_ms=existing["confirmationTimeMs"],
                )

            # Get previous hash from the most recent anchor
            recent_anchors = await self._repo.list_recent(limit=1)
            previous_hash = recent_anchors[0]["recordHash"] if recent_anchors else "0" * 64

            # Deterministic timestamp
            now = datetime.now(timezone.utc)
            timestamp = now.isoformat()

            # Compute canonical record hash
            canonical = _canonical_record(
                version=_RECORD_VERSION,
                evidence_id=evidence_id,
                evidence_sha256=sha256_hash,
                previous_hash=previous_hash,
                timestamp=timestamp,
            )
            record_hash = _compute_record_hash(canonical)

            # Generate deterministic tx_hash from canonical data
            tx_hash = _compute_record_hash("tx:" + canonical)

            # Anchor ID
            anchor_id = "ANC-" + secrets.token_hex(8)

            # Block number: count of existing anchors + 1
            stats = await self._repo.count_by_status()
            block_number = sum(stats.values()) + 1

            # Persist
            start_time = time.monotonic()
            result = await self._repo.create(
                anchor_id=anchor_id,
                evidence_id=evidence_id,
                sha256_hash=sha256_hash,
                record_hash=record_hash,
                tx_hash=tx_hash,
                block_number=block_number,
                previous_hash=previous_hash,
                status=ANCHOR_STATUS_CONFIRMED,
                confirmation_time_ms=0.0,
            )
            elapsed_ms = (time.monotonic() - start_time) * 1000

            if result is None:
                raise AnchorError("Failed to persist anchor to database")

            # Update confirmation time
            await self._repo.update_status(
                anchor_id, ANCHOR_STATUS_CONFIRMED,
                confirmation_time_ms=elapsed_ms,
            )

            logger.info(
                "[LOCAL LEDGER] Anchored %s (anchor=%s, block=%d)",
                evidence_id, anchor_id, block_number,
            )

            return AnchorResult(
                anchor_id=anchor_id,
                evidence_id=evidence_id,
                sha256_hash=sha256_hash,
                record_hash=record_hash,
                tx_hash=tx_hash,
                block_number=block_number,
                status=ANCHOR_STATUS_CONFIRMED,
                timestamp=timestamp,
                confirmation_time_ms=elapsed_ms,
                previous_hash=previous_hash,
            )

        except DuplicateAnchorError:
            raise
        except AnchorError:
            raise
        except Exception as e:
            logger.warning("[LOCAL LEDGER] Append failed: %s", e)
            raise AnchorError("Local ledger append failed: %s" % e)

    async def verify(
        self,
        evidence_id: str,
        sha256_hash: str,
    ) -> VerificationResult:
        """Verify evidence hash against the local ledger.

        Args:
            evidence_id: Unique evidence identifier.
            sha256_hash: Expected SHA-256 hex digest.

        Returns:
            VerificationResult with verification details.
        """
        try:
            anchor = await self._repo.get_by_evidence(evidence_id)
            if anchor is None:
                return VerificationResult(
                    verified=False,
                    status=ANCHOR_NOT_FOUND,
                    local_hash=sha256_hash,
                    chain_hash="",
                    evidence_id=evidence_id,
                )

            chain_hash = anchor["sha256Hash"]
            verified = sha256_hash == chain_hash
            status = VERIFIED if verified else BLOCKCHAIN_HASH_MISMATCH

            return VerificationResult(
                verified=verified,
                status=status,
                local_hash=sha256_hash,
                chain_hash=chain_hash,
                evidence_id=evidence_id,
                anchor_id=anchor["anchorId"],
            )

        except Exception as e:
            logger.warning("[LOCAL LEDGER] Verify failed: %s", e)
            return VerificationResult(
                verified=False,
                status=BLOCKCHAIN_UNAVAILABLE,
                local_hash=sha256_hash,
                chain_hash="",
                evidence_id=evidence_id,
            )

    async def get_proof(
        self,
        anchor_id: str,
    ) -> Optional[AnchorResult]:
        """Retrieve a stored anchor record."""
        try:
            row = await self._repo.get_by_id(anchor_id)
            if row is None:
                return None
            return AnchorResult(
                anchor_id=row["anchorId"],
                evidence_id=row["evidenceId"],
                sha256_hash=row["sha256Hash"],
                record_hash=row["recordHash"],
                tx_hash=row["txHash"],
                block_number=row["blockNumber"],
                status=row["status"],
                timestamp=row["createdAt"] or "",
                confirmation_time_ms=row["confirmationTimeMs"],
            )
        except Exception as e:
            logger.warning("[LOCAL LEDGER] get_proof failed: %s", e)
            return None

    async def get_proof_by_evidence(
        self,
        evidence_id: str,
    ) -> Optional[AnchorResult]:
        """Retrieve the canonical anchor for an evidence record."""
        try:
            row = await self._repo.get_by_evidence(evidence_id)
            if row is None:
                return None
            return AnchorResult(
                anchor_id=row["anchorId"],
                evidence_id=row["evidenceId"],
                sha256_hash=row["sha256Hash"],
                record_hash=row["recordHash"],
                tx_hash=row["txHash"],
                block_number=row["blockNumber"],
                status=row["status"],
                timestamp=row["createdAt"] or "",
                confirmation_time_ms=row["confirmationTimeMs"],
            )
        except Exception as e:
            logger.warning("[LOCAL LEDGER] get_proof_by_evidence failed: %s", e)
            return None

    async def stats(self) -> LedgerStats:
        """Return aggregate ledger statistics."""
        try:
            counts = await self._repo.count_by_status()
            confirmed = counts.get("CONFIRMED", 0)
            pending = counts.get("PENDING", 0)
            failed = counts.get("FAILED", 0)
            total = confirmed + pending + failed

            avg_ms = 0.0
            if confirmed > 0:
                recent = await self._repo.list_recent(limit=confirmed)
                times = [r["confirmationTimeMs"] for r in recent if r["confirmationTimeMs"] > 0]
                if times:
                    avg_ms = sum(times) / len(times)

            return LedgerStats(
                total_anchors=total,
                confirmed=confirmed,
                pending=pending,
                failed=failed,
                avg_confirmation_ms=avg_ms,
            )
        except Exception as e:
            logger.warning("[LOCAL LEDGER] stats failed: %s", e)
            return LedgerStats()

    async def health_check(self) -> bool:
        """Check if the local ledger database is reachable."""
        try:
            await self._repo.count_by_status()
            return True
        except Exception:
            return False


async def _async_sleep(seconds: float):
    """Async sleep helper."""
    import asyncio
    await asyncio.sleep(seconds)
