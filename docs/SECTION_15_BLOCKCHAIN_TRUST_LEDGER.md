# Section 15: Blockchain Trust & Evidence Ledger

## Objective

Extend the blockchain trust layer with reconciliation capability — the ability to compare PostgreSQL anchor metadata against ledger proof to detect operational inconsistencies.

This is NOT a redesign of the blockchain architecture. It adds one new data model, one new service method, and one new API endpoint.

## Trust Model

| Component | Owns | Trust Level |
|-----------|------|-------------|
| **PostgreSQL** | Operational state: evidence metadata, anchor references, audit logs | Operational — mutable, admin-accessible |
| **EvidenceStore** | Evidence files (off-chain bytes) | Storage — tamper-detectable via SHA-256 |
| **BlockchainService** | Policy, orchestration, trusted input validation, verification logic, reconciliation | Application trust layer |
| **BlockchainLedger (ABC)** | Append, verify, proof retrieval, stats, health | Adapter contract — zero business logic |
| **LocalLedger** | Deterministic chained record store in PostgreSQL | Development ledger — NOT production blockchain |

## Three Distinct Hash Concepts

1. **Evidence SHA-256** (`sha256_hash`): SHA-256 of the actual evidence file bytes. Computed at capture time. Stored in `evidence.sha256_hash`. This is the authoritative fingerprint of the evidence.

2. **Record Hash** (`record_hash`): SHA-256 of the canonical blockchain record. Computed when anchoring. Stored in `blockchain_anchors.record_hash`. This chains records together.

3. **Transaction Hash** (`tx_hash`): Ledger transaction identifier. For LocalLedger, deterministic from canonical record. For Hyperledger Fabric, the actual Fabric transaction ID.

**These are conceptually distinct.** The evidence hash identifies the evidence. The record hash creates the tamper-evident chain. The transaction hash provides ledger proof.

## Verification Flow

```
1. Request verification for evidence_id
2. Retrieve trusted evidence from PostgreSQL
3. Compare provided hash against DB hash (DATABASE_HASH_MISMATCH if different)
4. Check file integrity if evidence store available (EVIDENCE_TAMPERED if different)
5. Query ledger for anchor (ANCHOR_NOT_FOUND if missing, BLOCKCHAIN_UNAVAILABLE if down)
6. Compare DB hash against anchored hash (BLOCKCHAIN_HASH_MISMATCH if different)
7. Return structured result with detailed status
```

### Verification Statuses

| Status | Condition |
|--------|-----------|
| `VERIFIED` | All three hashes match (file, DB, blockchain) |
| `DATABASE_HASH_MISMATCH` | Client-provided hash differs from DB |
| `EVIDENCE_TAMPERED` | File on disk differs from DB hash |
| `BLOCKCHAIN_HASH_MISMATCH` | DB hash differs from blockchain anchor |
| `ANCHOR_NOT_FOUND` | No anchor exists for this evidence |
| `BLOCKCHAIN_UNAVAILABLE` | Ledger unreachable |
| `VERIFICATION_FAILED` | Internal error |

## Reconciliation

### What Is Reconciliation?

Reconciliation compares PostgreSQL anchor metadata against ledger proof to detect inconsistencies. It answers: "Is what PostgreSQL thinks is on the ledger actually on the ledger?"

### Reconciliation Trust Model

**Authoritative identity/proof fields** drive the `matched` flag:
- `evidence_id`
- `sha256_hash`
- `record_hash`
- `tx_hash`
- `block_number`

**Status is operational metadata.** A status difference is reported as a mismatch but does not indicate cryptographic tampering. Status mismatches may occur due to:
- Asynchronous confirmation delays
- Ledger state transitions not yet reflected in PostgreSQL
- Operational inconsistencies separate from cryptographic integrity

### Reconciliation Result

```python
@dataclass
class ReconciliationResult:
    matched: bool
    mismatches: List[str]  # Field names that differ, e.g. ["sha256_hash", "status"]
```

### Reconciliation Workflow

```
1. Load PostgreSQL anchor by anchor_id
   → If not found: mismatch ["anchor_not_found_in_db"]
2. Query ledger for proof by anchor_id
   → If not found: mismatch ["anchor_not_found_in_ledger"]
3. Compare sha256_hash, record_hash, tx_hash, block_number
   → Each differing field added to mismatches
4. Compare status (operational metadata)
   → If different, added to mismatches
5. Return ReconciliationResult(matched=len(mismatches)==0, mismatches=mismatches)
```

### API

```
POST /blockchain/anchors/{anchor_id}/reconcile
Permission: BLOCKCHAIN_ANCHOR (ADMIN, OPERATOR only)
Response: { "matched": true/false, "mismatches": [...] }
```

## Automatic Anchoring Policies

| Policy | Behavior |
|--------|----------|
| `all` | Anchor every evidence record |
| `high_severity` | Anchor only HIGH and CRITICAL severity events |
| `manual_only` | Never auto-anchor; manual trigger required |

Policy is evaluated by `BlockchainService._should_anchor()`. Evidence that doesn't match the policy is skipped.

## Manual Anchoring

```
POST /blockchain/evidence/{evidence_id}/anchor
Permission: BLOCKCHAIN_ANCHOR
```

Rules:
- Must retrieve evidence from DB (never trust client-provided hashes)
- Idempotent: same evidence_id returns existing anchor
- Audit logged with actor user_id
- Requires BLOCKCHAIN_ANCHOR permission (VIEWER cannot)

## Blockchain Failure Isolation

Blockchain failure is **isolated** from all other subsystems:

- AI detection continues unaffected
- Evidence capture continues unaffected
- Central sync continues unaffected
- Network health monitoring continues unaffected
- Only anchoring is deferred

```python
# In EvidenceCapture.capture_snapshot():
if self._blockchain_service and self._blockchain_service.enabled:
    try:
        await self._blockchain_service.maybe_anchor(evidence)
    except Exception:
        pass  # Never crash the pipeline
```

Valid system state when blockchain is unavailable:
```
Central = CONNECTED
Database = HEALTHY
AI = RUNNING
Evidence = HEALTHY
Blockchain = UNAVAILABLE
```

## RBAC

| Permission | ADMIN | OPERATOR | VIEWER |
|-----------|-------|----------|--------|
| `BLOCKCHAIN_READ` | ✓ | ✓ | ✓ |
| `BLOCKCHAIN_ANCHOR` | ✓ | ✓ | ✗ |

Enforced via existing `require_permission()` dependency.

## Edge Security

Edge nodes **cannot** directly access blockchain APIs:

```python
class EdgePermissions:
    CAN_BLOCKCHAIN_READ = False
    CAN_BLOCKCHAIN_ANCHOR = False
```

Edge JWTs cannot be used for blockchain API calls.

## Audit Events

| Action | When |
|--------|------|
| `blockchain.anchor` | Evidence successfully anchored |
| `blockchain.anchor_failed` | Anchoring attempt failed |
| `blockchain.verify` | Evidence verified against chain |
| `blockchain.verify_failed` | Verification encountered error or file tampering |
| `blockchain.tamper_detected` | File hash != DB hash before anchoring |
| `blockchain.health_changed` | Ledger health state transition |

Actor: `BLOCKCHAIN_SERVICE`. No secrets, tokens, or credentials in audit records.

## API Endpoints

| Endpoint | Method | Permission | Description |
|----------|--------|------------|-------------|
| `/blockchain/health` | GET | `BLOCKCHAIN_READ` | Ledger health check |
| `/blockchain/stats` | GET | `BLOCKCHAIN_READ` | Anchor counts, timing |
| `/blockchain/anchors/{id}` | GET | `BLOCKCHAIN_READ` | Specific anchor details |
| `/blockchain/evidence/{id}` | GET | `BLOCKCHAIN_READ` | Anchor for evidence |
| `/blockchain/evidence/{id}/anchor` | POST | `BLOCKCHAIN_ANCHOR` | Manual anchoring |
| `/blockchain/evidence/{id}/verify` | POST | `BLOCKCHAIN_READ` | Verify against chain |
| `/blockchain/anchors/{id}/reconcile` | POST | `BLOCKCHAIN_ANCHOR` | Reconcile PG vs ledger |
| `/evidence/{id}` | GET | `EVIDENCE_READ` | Includes `blockchainAnchor` field |
| `/evidence/{id}/blockchain` | GET | `BLOCKCHAIN_READ` | Blockchain details for evidence |

## LocalLedger Limitations

The `LocalLedger` is a **development/testing adapter**, not a production blockchain:

- Single-node, no consensus
- Deterministic SHA-256 chaining via `previous_hash`
- Idempotent: duplicate evidence_id returns existing anchor
- Simulated latency configurable for testing
- Chain integrity is LocalLedger-specific; `previous_hash` has no meaning for Hyperledger Fabric

**The LocalLedger is a development/test adapter and is not a production distributed blockchain network.**

## Hyperledger-Ready Abstraction

The `BlockchainLedger` ABC is designed for backend swapping:

```python
class BlockchainLedger(ABC):
    async def append(evidence_id, sha256_hash) -> AnchorResult
    async def verify(evidence_id, sha256_hash) -> VerificationResult
    async def get_proof(anchor_id) -> AnchorResult | None
    async def get_proof_by_evidence(evidence_id) -> AnchorResult | None
    async def stats() -> LedgerStats
    async def health_check() -> bool
```

**Critical:** `record_hash` is an **application-level canonical record fingerprint**, NOT a Fabric block hash. For Hyperledger Fabric, the adapter would separately support:
- Application record hash (canonical record)
- Fabric transaction ID
- Fabric block number
- Fabric block hash/proof where available

A future `HyperledgerFabricLedger` would implement this interface without modifying `BlockchainService`.

## Security Limitations

1. **LocalLedger is not distributed** — single-node, no consensus. Use for development only.
2. **No real-time finality** — confirmation is immediate in local mode.
3. **No key management infrastructure** — production needs HSM/KMS integration.
4. **No cross-chain verification** — single ledger only.
5. **PostgreSQL remains the trust anchor for operations** — blockchain is supplementary.

## Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `ReconciliationResult` dataclass exists | ✓ |
| 2 | `reconcile_anchor()` method in service | ✓ |
| 3 | `POST /blockchain/anchors/{id}/reconcile` endpoint | ✓ |
| 4 | All 7 verification statuses producible | ✓ |
| 5 | File tampering → EVIDENCE_TAMPERED | ✓ |
| 6 | DB hash tampering → DATABASE_HASH_MISMATCH | ✓ |
| 7 | Blockchain mismatch → BLOCKCHAIN_HASH_MISMATCH | ✓ |
| 8 | Reconciliation prioritizes identity fields | ✓ |
| 9 | Status mismatch reported but not cryptographic failure | ✓ |
| 10 | Manual anchor idempotent + trusted hash | ✓ |
| 11 | Blockchain outage isolated from AI/sync/evidence | ✓ |
| 12 | VIEWER 403 on reconcile, OPERATOR 200 | ✓ |
| 13 | Edge token 403 on all blockchain endpoints | ✓ |
| 14 | All existing 50 blockchain tests pass | ✓ |
| 15 | All 41 Section 15 tests pass | ✓ |
| 16 | `tsc --noEmit` clean | ✓ |
| 17 | `npm run build` succeeds | ✓ |
| 18 | Documentation complete | ✓ |

## Files Modified (Section 15)

### Modified:
- `ai/blockchain/models.py` — Added `ReconciliationResult` dataclass, added `List` import
- `ai/blockchain/service.py` — Added `anchor_repo` constructor parameter, added `reconcile_anchor()` method, added file verification to `verify_evidence()`
- `ai/blockchain/routes.py` — Added `POST /blockchain/anchors/{id}/reconcile` endpoint
- `ai/main.py` — Added `anchor_repo=_blockchain_anchor_repo` to service construction
- `ai/tests/test_blockchain.py` — Fixed `test_21_verify_evidence` to use matching file hash

### Created:
- `ai/tests/test_section15_blockchain.py` — 41 tests covering reconciliation, verification, tamper detection, manual anchoring, outage isolation, security, and acceptance criteria
- `docs/SECTION_15_BLOCKCHAIN_TRUST_LEDGER.md` — This documentation
