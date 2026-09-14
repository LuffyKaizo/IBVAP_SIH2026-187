"""Blockchain-specific exceptions."""


class BlockchainError(Exception):
    """Base exception for blockchain operations."""
    pass


class AnchorError(BlockchainError):
    """Raised when an anchoring operation fails."""
    pass


class VerificationError(BlockchainError):
    """Raised when a verification operation encounters an error."""
    pass


class LedgerUnavailableError(BlockchainError):
    """Raised when the ledger backend is unreachable."""
    pass


class DuplicateAnchorError(BlockchainError):
    """Raised when attempting to anchor evidence that is already anchored."""
    pass
