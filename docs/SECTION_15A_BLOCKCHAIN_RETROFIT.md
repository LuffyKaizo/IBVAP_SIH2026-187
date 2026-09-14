# Section 15A: Blockchain Trust Layer Retrofit

## Why Blockchain Exists

IBVAP operates in border security environments where evidence integrity is critical. A compromised actor with database access could modify detection records, timestamps, or evidence hashes without detection. The blockchain trust layer provides **tamper-evident anchoring** — cryptographic proof that a specific evidence hash existed at a specific time and has not been altered.

This is NOT a replacement for PostgreSQL. It is an additional trust layer that makes evidence tampering detectable.

## Architecture: Three Layers

```
AI = DETECT        (Sections 1-8: YOLO, tracking, behavior, ANPR)
Cybersecurity = PROTECT  (Sections 9-14: auth, evidence, sync, network, edge)
Blockchain = TRUST       (Section 15A: tamper-evident anchoring)
```

Lifecycle:
```
DETECT → PROTECT → RECORD → ANCHOR → VERIFY → RESPOND
```

## PostgreSQL vs Blockchain Responsibilities

| Concern | PostgreSQL | Blockchain |
|---------|-----------|------------|
| Operational queries | Primary store | Not queried |
| Evidence metadata | Authoritative | Reference only |
| File storage | Off-chain | Off-chain |
| Real-time access | Yes | No |
| Tamper detection | Limited | Core purpose |
| Audit trail | append-only | append-only |
| HA/DR | Existing infra | Future concern |

**PostgreSQL remains the operational database.** Blockchain stores compact cryptographic trust records only.

## Evidence Off-Chain Architecture

Evidence files (JPEG snapshots) are stored on the local filesystem at `ai/data/evidence/`. The blockchain never stores images or videos. The trust record is:

```
evidence file → SHA-256 → evidence hash → anchor to ledger
```

## SHA-256 Role

SHA-256 serves two distinct purposes:

1. **Evidence hash**: SHA-256 of the actual evidence file bytes. Computed at capture time. Stored in `evidence.sha256_hash`. This is the authoritative fingerprint of the evidence.

2. **Record hash**: SHA-256 of the canonical blockchain record. Computed when anchoring. Stored in `blockchain_anchors.record_hash`. This chains records together.

**These are conceptually distinct.** The evidence hash identifies the evidence. The record hash creates the tamper-evident chain.

## Anchor Lifecycle

```
1. Evidence captured → SHA-256 computed → stored in DB
2. BlockchainService evaluates policy (all/high_severity/manual_only)
3. If policy matches:
   a. Retrieve trusted evidence from PostgreSQL (never trust client)
   b. Optionally verify file hash matches DB hash
   c. Submit evidence hash to ledger
   d. Ledger creates canonical record, computes record_hash
   e. previous_hash chains to prior anchor
   f. Anchor persisted to blockchain_anchors table
   g. Audit log created
```

## Verification Lifecycle

```
1. Request verification for evidence_id
2. Retrieve trusted evidence from PostgreSQL
3. Compare provided hash against DB hash (DATABASE_HASH_MISMATCH if different)
4. Query ledger for anchor
5. Compare DB hash against anchored hash (BLOCKCHAIN_HASH_MISMATCH if different)
6. Return structured result with detailed status
```

Possible outcomes:
- `VERIFIED` — all hashes match
- `DATABASE_HASH_MISMATCH` — provided hash != DB hash
- `BLOCKCHAIN_HASH_MISMATCH` — DB hash != anchored hash
- `ANCHOR_NOT_FOUND` — no anchor exists for this evidence
- `BLOCKCHAIN_UNAVAILABLE` — ledger unreachable
- `VERIFICATION_FAILED` — internal error

## LocalLedger Design

The `LocalLedger` is a **development/testing adapter**, not a production blockchain.

- Stores anchors in PostgreSQL via `BlockchainAnchorRepository`
- Deterministic canonical record serialization (JSON, explicit field ordering)
- SHA-256 chaining: each record's `previous_hash` = prior record's `record_hash`
- Idempotent: duplicate `evidence_id` returns existing anchor
- Simulated latency configurable for testing

**The LocalLedger is a development/test adapter and is not a production distributed blockchain network.**

## Store-and-Forward Behavior

Blockchain anchoring uses the existing `SyncQueue` infrastructure:

- Entity type: `BLOCKCHAIN_ANCHOR`
- Operation: `ANCHOR`
- Only used when anchoring cannot complete immediately
- Exponential backoff with bounded retry
- Idempotent retries — same evidence does not create duplicate anchors

**Critical**: No queue recursion. `SyncManager` → `BlockchainService` → ledger. `BlockchainService` never calls back into `SyncManager`.

## Blockchain Failure Behavior

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

New permissions added to existing role system:

| Permission | ADMIN | OPERATOR | VIEWER |
|-----------|-------|----------|--------|
| `BLOCKCHAIN_READ` | ✓ | ✓ | ✓ |
| `BLOCKCHAIN_ANCHOR` | ✓ | ✓ | ✗ |

Enforced via existing `require_permission()` dependency. No second authorization system.

## Edge Security

Edge nodes **cannot** directly anchor blockchain records:

```python
class EdgePermissions:
    CAN_BLOCKCHAIN_READ = False
    CAN_BLOCKCHAIN_ANCHOR = False
```

Edge JWTs cannot be used for blockchain API calls. The central service handles all blockchain operations.

## Audit

All blockchain operations logged via `AuditRepository`:

| Action | When |
|--------|------|
| `blockchain.anchor` | Evidence successfully anchored |
| `blockchain.anchor_failed` | Anchoring attempt failed |
| `blockchain.verify` | Evidence verified against chain |
| `blockchain.verify_failed` | Verification encountered error |
| `blockchain.tamper_detected` | File hash != DB hash before anchoring |
| `blockchain.health_changed` | Ledger health state transition |

Actor: `BLOCKCHAIN_SERVICE`. No secrets, tokens, or credentials in audit records.

## API

| Endpoint | Method | Permission | Description |
|----------|--------|------------|-------------|
| `/blockchain/health` | GET | `BLOCKCHAIN_READ` | Ledger health check |
| `/blockchain/stats` | GET | `BLOCKCHAIN_READ` | Anchor counts, timing |
| `/blockchain/anchors/{id}` | GET | `BLOCKCHAIN_READ` | Specific anchor details |
| `/blockchain/evidence/{id}` | GET | `BLOCKCHAIN_READ` | Anchor for evidence |
| `/blockchain/evidence/{id}/anchor` | POST | `BLOCKCHAIN_ANCHOR` | Manual anchoring |
| `/blockchain/evidence/{id}/verify` | POST | `BLOCKCHAIN_READ` | Verify against chain |
| `/evidence/{id}` | GET | `EVIDENCE_READ` | Now includes `blockchainAnchor` field |
| `/evidence/{id}/blockchain` | GET | `BLOCKCHAIN_READ` | Blockchain details for evidence |

## Configuration

```bash
BLOCKCHAIN_ENABLED=false                    # Master switch
BLOCKCHAIN_LEDGER_TYPE=local                # local | hyperledger
BLOCKCHAIN_ANCHOR_POLICY=high_severity      # all | high_severity | manual_only
BLOCKCHAIN_ANCHOR_MIN_SEVERITY=HIGH         # Minimum severity for anchoring
BLOCKCHAIN_LOCAL_LATENCY_MS=0               # Simulated latency for testing
```

## Future Hyperledger Adapter

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

A future `HyperledgerFabricLedger` would implement this interface without modifying `BlockchainService` or any other application code.

## Security Limitations

1. **LocalLedger is not distributed** — single-node, no consensus. Use for development only.
2. **No real-time finality** — confirmation is immediate in local mode. Production blockchains have confirmation delays.
3. **No key management infrastructure** — production deployment needs HSM/KMS integration.
4. **No cross-chain verification** — single ledger only.
5. **PostgreSQL remains the trust anchor for operations** — blockchain is supplementary.

## Files Created/Modified

### New files:
- `ai/blockchain/__init__.py`
- `ai/blockchain/models.py`
- `ai/blockchain/interface.py`
- `ai/blockchain/exceptions.py`
- `ai/blockchain/repository.py`
- `ai/blockchain/local_ledger.py`
- `ai/blockchain/service.py`
- `ai/blockchain/routes.py`
- `ai/alembic/versions/006_add_blockchain_anchors.py`
- `ai/tests/test_blockchain.py`
- `docs/SECTION_15A_BLOCKCHAIN_RETROFIT.md`

### Modified files:
- `ai/config.py` — added BLOCKCHAIN settings
- `ai/auth/models.py` — added BLOCKCHAIN_READ, BLOCKCHAIN_ANCHOR permissions
- `ai/edge/models.py` — added CAN_BLOCKCHAIN_READ=False, CAN_BLOCKCHAIN_ANCHOR=False
- `ai/evidence/capture.py` — added blockchain_service parameter, anchoring integration
- `ai/evidence/routes.py` — added blockchain status in GET, new /blockchain endpoint
- `ai/main.py` — blockchain subsystem wiring
- `src/types.ts` — added BlockchainAnchor, BlockchainVerificationResult, etc.
