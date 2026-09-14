"""Blockchain domain models.

Pure dataclasses representing ledger operations. No SQLAlchemy, no Pydantic.
Keeps evidence hash (SHA-256 of file) conceptually distinct from record hash
(SHA-256 of canonical blockchain record).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


# ──────────────────────────────────────────────────────────────
# Anchor Statuses
# ──────────────────────────────────────────────────────────────

ANCHOR_STATUS_PENDING = "PENDING"
ANCHOR_STATUS_CONFIRMED = "CONFIRMED"
ANCHOR_STATUS_FAILED = "FAILED"


# ──────────────────────────────────────────────────────────────
# Verification Statuses
# ──────────────────────────────────────────────────────────────

VERIFIED = "VERIFIED"
DATABASE_HASH_MISMATCH = "DATABASE_HASH_MISMATCH"
BLOCKCHAIN_HASH_MISMATCH = "BLOCKCHAIN_HASH_MISMATCH"
EVIDENCE_TAMPERED = "EVIDENCE_TAMPERED"
ANCHOR_NOT_FOUND = "ANCHOR_NOT_FOUND"
BLOCKCHAIN_UNAVAILABLE = "BLOCKCHAIN_UNAVAILABLE"
VERIFICATION_FAILED = "VERIFICATION_FAILED"


# ──────────────────────────────────────────────────────────────
# Domain Models
# ──────────────────────────────────────────────────────────────

@dataclass
class AnchorResult:
    """Result of a blockchain anchoring operation."""
    anchor_id: str
    evidence_id: str
    sha256_hash: str
    record_hash: str
    tx_hash: str
    block_number: int
    status: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confirmation_time_ms: float = 0.0
    previous_hash: str = ""


@dataclass
class VerificationResult:
    """Result of verifying evidence against the blockchain."""
    verified: bool
    status: str
    local_hash: str
    chain_hash: str
    evidence_id: str
    anchor_id: str = ""


@dataclass
class LedgerStats:
    """Aggregate statistics from the ledger."""
    total_anchors: int = 0
    confirmed: int = 0
    pending: int = 0
    failed: int = 0
    avg_confirmation_ms: float = 0.0


@dataclass
class ReconciliationResult:
    """Result of reconciling PostgreSQL anchor metadata against ledger proof.

    Authoritative identity/proof fields (sha256_hash, record_hash, tx_hash,
    block_number) drive the matched flag. Status is operational metadata —
    reported but does not itself cause cryptographic reconciliation failure.
    """
    matched: bool
    mismatches: List[str] = field(default_factory=list)
