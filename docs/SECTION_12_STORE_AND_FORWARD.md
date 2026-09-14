# Section 12 — Store-and-Forward Synchronization

## Architecture

```
CCTV → Edge AI → Event Detection → Local DB → Sync Queue → Central Server
                              ↓
                         Evidence → Local Store → Sync Queue → Central Server
```

### Offline Mode
```
CCTV → Edge AI → Event → Local DB
                    ↓
               Evidence → Local Store
                    ↓
              Sync Queue → PENDING
                    ↓
          AI CONTINUES NORMALLY
```

### Recovery Mode
```
Sync Queue → PENDING items → Auto Sync → SYNCED
```

## Queue States

| State | Description |
|-------|-------------|
| `PENDING` | Created, waiting for sync |
| `IN_PROGRESS` | Claimed by sync worker |
| `SYNCED` | Successfully synchronized |
| `FAILED` | Sync failed (retryable or permanent) |

## Retry Strategy

Bounded exponential backoff:
```
attempt 0 → 2s    (base × 2^0)
attempt 1 → 4s    (base × 2^1)
attempt 2 → 8s    (base × 2^2)
attempt 3 → 16s   (base × 2^3)
attempt 4 → 32s   (base × 2^4)
attempt 5+ → 60s  (capped at SYNC_BACKOFF_MAX_SEC)
```

### Failure Classification

| Response | Action |
|----------|--------|
| Network error / timeout | Retryable |
| HTTP 5xx | Retryable |
| HTTP 429 (rate limit) | Retryable with delay |
| HTTP 401/403 | **Not retryable** (auth failure) |
| HTTP 4xx (other) | **Not retryable** (validation error) |

## What Gets Synchronized

### Event Metadata
- event_id, camera_id, event_type, severity, status, timestamp, zone info

### Evidence Metadata
- evidence_id, event_id, camera_id, file_path, file_size, sha256_hash, integrity_status

### Evidence File
- Actual JPEG snapshot uploaded separately
- SHA-256 verified after transfer

## Sync Ordering

1. Event metadata → Central
2. Evidence metadata → Central
3. Evidence file → Central
4. SHA-256 verification

## API Endpoints

### `GET /sync/status`
Authenticated (any role). Returns connectivity state, queue counts, last success/failure.

### `POST /sync/run`
Authenticated (ADMIN/OPERATOR only). Manually trigger a sync pass.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_ENABLED` | `true` | Enable background sync |
| `SYNC_INTERVAL_SEC` | `10` | Seconds between sync passes |
| `SYNC_BATCH_SIZE` | `20` | Max items per sync pass |
| `SYNC_REQUEST_TIMEOUT_SEC` | `15` | HTTP timeout |
| `SYNC_MAX_RETRIES` | `5` | Max retry attempts |
| `SYNC_BACKOFF_BASE_SEC` | `2.0` | Backoff base |
| `SYNC_BACKOFF_MAX_SEC` | `60.0` | Backoff cap |
| `SYNC_CLEANUP_DAYS` | `30` | Delete old synced items |
| `CENTRAL_API_URL` | `http://localhost:8000` | Central server URL |
| `CENTRAL_API_KEY` | `""` | API key for central auth |

## Idempotency

Queue uses `ON CONFLICT DO NOTHING` on `(entity_type, entity_id)`. The same event or evidence cannot be enqueued twice while already pending/in-progress/failed.

Central endpoints should treat `event_id` and `evidence_id` as idempotency keys.

## Security

- JWT authentication on all sync endpoints
- RBAC: SYNC_READ (all roles), SYNC_CONTROL (ADMIN/OPERATOR)
- SHA-256 verification on evidence file transfer
- No credentials in logs
- Request timeout on all HTTP calls
- Path traversal prevention (evidence paths resolved from trusted DB records)

## Limitations

- Video clips not supported (snapshot-only evidence)
- Central server endpoints are mock/internal — full central deployment is a future section
- No GIS, BOP hierarchy, or multi-dashboard integration yet

## Test Results

```
Section 12 Sync:    28/28
Section 10 Auth:    25/25
Section 11 Evidence: 24/24
Events:             14/14
Pipeline:            9/9
Total:             100/100
```
