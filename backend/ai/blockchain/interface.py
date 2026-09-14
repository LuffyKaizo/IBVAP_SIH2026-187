"""Abstract blockchain ledger interface.

Defines the contract that any ledger backend must implement.
Current: LocalLedger (development/testing).
Future: HyperledgerFabricLedger, EthereumLedger, etc.

The BlockchainService depends on this interface, NOT on concrete implementations.
"""

from abc import ABC, abstractmethod

from ai.blockchain.models import AnchorResult, VerificationResult, LedgerStats


class BlockchainLedger(ABC):
    """Abstract interface for blockchain ledger backends.

    All methods are async to support network-bound ledger operations
    without blocking the AI pipeline.
    """

    @abstractmethod
    async def append(
        self,
        evidence_id: str,
        sha256_hash: str,
    ) -> AnchorResult:
        """Anchor an evidence hash to the ledger.

        Args:
            evidence_id: Unique evidence identifier.
            sha256_hash: SHA-256 hex digest of the evidence file.

        Returns:
            AnchorResult with ledger details.

        Raises:
            AnchorError: If anchoring fails.
            DuplicateAnchorError: If evidence is already anchored.
        """

    @abstractmethod
    async def verify(
        self,
        evidence_id: str,
        sha256_hash: str,
    ) -> VerificationResult:
        """Verify an evidence hash against the ledger.

        Args:
            evidence_id: Unique evidence identifier.
            sha256_hash: Expected SHA-256 hex digest.

        Returns:
            VerificationResult with verification details.
        """

    @abstractmethod
    async def get_proof(
        self,
        anchor_id: str,
    ) -> AnchorResult | None:
        """Retrieve a stored anchor record.

        Args:
            anchor_id: Unique anchor identifier.

        Returns:
            AnchorResult if found, None otherwise.
        """

    @abstractmethod
    async def get_proof_by_evidence(
        self,
        evidence_id: str,
    ) -> AnchorResult | None:
        """Retrieve the canonical anchor for an evidence record.

        Args:
            evidence_id: Unique evidence identifier.

        Returns:
            AnchorResult if found, None otherwise.
        """

    @abstractmethod
    async def stats(self) -> LedgerStats:
        """Return aggregate ledger statistics."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the ledger backend is reachable and operational."""
