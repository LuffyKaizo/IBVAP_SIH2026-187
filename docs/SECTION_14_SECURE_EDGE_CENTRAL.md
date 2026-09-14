# Section 14: Secure Edge ↔ Central Communication

## 1. Threat Model

### Protected Against
- **Unauthorized Edge nodes**: Only registered nodes with valid secrets can authenticate
- **Stolen Edge credentials**: Short-lived tokens (5min default) limit exposure window
- **Token theft**: Tokens expire quickly; 401 triggers token refresh
- **Replay attacks**: Unique jti per token; idempotent sync operations via event_id/evidence_id
- **Man-in-the-middle**: TLS verification enabled by default; optional CA bundle
- **SSRF**: CentralSyncClient uses only configured CENTRAL_API_URL; no user-supplied URLs
- **Unauthorized evidence upload**: Edge authentication required for all sync operations
- **Evidence tampering**: SHA-256 hash verified independently by central server
- **Oversized uploads**: MAX_EVIDENCE_UPLOAD_MB configurable limit
- **Credential leakage**: Secrets/tokens never logged, never returned by APIs, never in frontend
- **Privilege escalation**: Edge tokens are separate from human JWTs; cannot cross-authenticate
- **Central server outage**: AI continues locally; sync queue preserved

### Not Protected Against (Out of Scope)
- Physical network compromise (transport-layer concerns outside software scope)
- Compromised Edge hardware
- Central server compromise
- Distributed denial of service at network level
- Zero-day cryptographic attacks

## 2. Edge Identity

Each Edge AI node has a unique identity:
- **EDGE_NODE_ID**: Unique identifier (e.g., "BOP-EDGE-001")
- **EDGE_NODE_SECRET**: Shared secret, stored as bcrypt hash in database

Configuration via environment variables:
```
EDGE_NODE_ID=BOP-EDGE-001
EDGE_NODE_SECRET=<secret>
EDGE_TOKEN_SECRET=<signing-key>
```

## 3. Machine Authentication

Edge nodes authenticate via `POST /edge/auth/token`:
```json
{
  "node_id": "BOP-EDGE-001",
  "secret": "..."
}
```

Response:
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 300,
  "node_id": "BOP-EDGE-001"
}
```

Security measures:
- Rate limiting (configurable max failures per window)
- Never logs secrets
- Never logs access tokens
- Rejects unknown/disabled nodes

## 4. Token Lifecycle

### Edge JWT Claims
| Claim | Value |
|-------|-------|
| `sub` | node_id |
| `iss` | "ibvap-edge" |
| `purpose` | "edge-sync" |
| `iat` | issued-at (unix epoch) |
| `exp` | expiration (unix epoch) |
| `jti` | unique token ID |

### Separate from Human JWTs
- **Different signing key**: `EDGE_TOKEN_SECRET` vs `SECRET_KEY`
- **Different claims**: Edge tokens have `purpose`; human tokens have `email`/`role`
- **Mutual exclusion**: Edge tokens cannot pass `get_current_user()`; human tokens cannot pass `require_edge_auth()`

### Token Refresh
- Tokens cached by `CentralSyncClient`
- Refreshed before expiry (configurable margin)
- On 401: token invalidated, new token acquired, request retried once
- No infinite retry loops

## 5. TLS

- **CENTRAL_VERIFY_TLS**: Enabled by default (`true`)
- **CENTRAL_CA_BUNDLE**: Optional custom CA certificate path
- **Development mode**: HTTP allowed for localhost (no forced TLS on dev)
- No `verify=False` production path

## 6. Certificate Validation

Standard httpx TLS verification:
- System CA bundle by default
- Custom CA bundle via `CENTRAL_CA_BUNDLE` config
- No custom TLS cryptography

## 7. Request Integrity

**Primary protection**: HTTPS + authenticated Edge JWT

No HMAC implementation (per design decision). HTTPS provides transport security; Edge JWT provides authentication and authorization. SHA-256 evidence verification ensures file integrity.

## 8. Replay Protection

- Short-lived tokens (5min default) limit replay window
- Unique `jti` per token for request identification
- Idempotent sync operations via `event_id` and `evidence_id`
- Existing Section 12 idempotency preserved

## 9. Evidence Transfer Security

Flow:
1. Edge authenticates → receives token
2. Edge uploads evidence with `Authorization: Bearer <token>`
3. Central verifies token
4. Central computes SHA-256 of received file
5. Compares with client-provided hash
6. Accepts or rejects based on match

## 10. Authorization

Edge nodes have fixed permissions:
| Operation | Allowed |
|-----------|---------|
| Sync events | Yes |
| Sync evidence metadata | Yes |
| Sync evidence files | Yes |
| Health check | Yes |
| Admin operations | No |
| Camera management | No |
| Settings management | No |
| Evidence deletion | No |
| User management | No |

## 11. Secret Management

- Secrets from environment configuration only
- Never committed to version control
- Never printed or logged
- Never returned by APIs
- Never in audit logs
- Never in exception messages
- Never in URLs
- Never in frontend JavaScript
- Stored as bcrypt hashes in database

## 12. Offline Behavior

**Edge AI remains operational when secure Edge-to-Central communication is unavailable.**

- Central auth unavailable → AI continues locally
- Central HTTPS unavailable → AI continues locally
- Token acquisition fails → AI continues locally
- Evidence upload fails → local evidence preserved
- Synchronization fails → queue preserved
- Central rejects authentication → queue remains pending/failed

## 13. Network Health Integration

Reuses Section 13 `NetworkHealthManager`. Does NOT create a second network health system.

Distinction maintained:
- **NETWORK UNREACHABLE**: NetworkHealthManager concern
- **TLS FAILURE**: Connection error → retryable
- **AUTHENTICATION FAILURE**: 401 → token refresh
- **AUTHORIZATION FAILURE**: 403 → not retryable
- **SERVER FAILURE**: 5xx → retryable

## 14. Audit Logging

Security events logged:
| Event | Description |
|-------|-------------|
| `EDGE_AUTH_SUCCESS` | Successful Edge authentication |
| `EDGE_AUTH_FAILURE` | Failed Edge authentication |
| `EDGE_TOKEN_REFRESH` | Token refreshed |
| `EDGE_TOKEN_REJECTED` | Token verification failed |
| `EDGE_NODE_DISABLED` | Disabled node attempted auth |
| `EDGE_NODE_ENABLED` | Node re-enabled |

Never logged: secrets, tokens, Authorization headers, database URLs.

## 15. Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `EDGE_NODE_ID` | "" | Edge node identifier |
| `EDGE_NODE_SECRET` | "" | Edge node secret (plaintext in env) |
| `EDGE_TOKEN_TTL_SECONDS` | 300 | Token lifetime (seconds) |
| `EDGE_TOKEN_SECRET` | "" | Separate signing key for Edge JWTs |
| `EDGE_TOKEN_ISSUER` | "ibvap-edge" | JWT issuer claim |
| `EDGE_LAST_SEEN_UPDATE_SECONDS` | 60 | Throttle for last_seen updates |
| `CENTRAL_VERIFY_TLS` | true | Enable TLS verification |
| `CENTRAL_CA_BUNDLE` | "" | Custom CA certificate path |
| `MAX_EVIDENCE_UPLOAD_MB` | 10 | Max evidence file size |
| `EDGE_AUTH_RATE_LIMIT_MAX` | 5 | Max auth failures per window |
| `EDGE_AUTH_RATE_LIMIT_WINDOW_SEC` | 300 | Rate limit window (seconds) |

## 16. API Endpoints

### Edge Authentication
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/edge/auth/token` | None (public) | Authenticate Edge node |

### Existing Endpoints (unchanged)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/login` | None | Human user login |
| POST | `/sync/events` | User JWT | Sync events |
| POST | `/sync/evidence` | User JWT | Sync evidence |
| GET | `/network/status` | User JWT | Network health |

## 17. Testing

45 tests covering:
- Edge authentication (1-10): Valid/invalid credentials, unknown/disabled node, token types
- Token management (11-15): Acquisition, caching, refresh, 401 handling
- TLS/transport (16-20): HTTPS, TLS verification, CA bundle, timeouts
- Authorization (21-24): Edge permissions, disabled node denial
- Idempotency/replay (25-28): Duplicate prevention, unique jti
- Evidence security (29-30): SHA-256, upload limits
- Security/secret handling (31-35): No secrets in logs, SSRF prevention
- Additional (36-45): Rate limiter, hashing, bootstrap, throttling

## 18. Limitations

- Single-node architecture (no distributed rate limiting)
- In-memory rate limiter resets on restart
- No token revocation (tokens expire naturally)
- No hardware security module (HSM) integration
- No mutual TLS (mTLS) — one-way TLS only
- No certificate pinning
- No encrypted evidence at rest
