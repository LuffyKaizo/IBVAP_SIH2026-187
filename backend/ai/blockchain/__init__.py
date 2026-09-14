"""Blockchain trust layer for IBVAP.

Provides tamper-evident anchoring of evidence SHA-256 hashes to a ledger.
PostgreSQL remains the operational database; evidence files remain off-chain.
The blockchain stores compact cryptographic trust records only.
"""
