# Section 13: Network Health & Degraded Mode

## Overview
Section 13 makes the Edge AI node explicitly aware of its connection health to the central IBVAP platform. It implements a 4-state machine with hysteresis to prevent flapping, tracks latency with a bounded rolling window, and integrates with the SyncManager to coordinate store-and-forward behavior.

Central connectivity failure does **NOT** stop Edge AI processing — the node continues operating autonomously.

## Architecture

### State Machine
```
                    ┌──────────┐
          success   │          │  success (≥ recovery_threshold)
    ┌──────────────►│RECOVERING├──────────────────────┐
    │               │          │                       │
    │               └────┬─────┘                       │
    │                    │ failure                     │
    │                    ▼                             ▼
┌───┴─────┐       ┌──────────┐                 ┌──────────┐
│         │ fail  │          │ fail(threshold) │          │
│ OFFLINE │◄──────│ DEGRADED │◄────────────────│ CONNECTED│
│         │       │          │                 │          │
└─────────┘       └────┬─────┘                 └────┬─────┘
                       │ success(≥recovery)          │
                       └────────────────────────────►│
                                                     │
```

### State Transitions

| From | To | Trigger |
|------|-----|---------|
| OFFLINE | RECOVERING | 1 successful health check |
| RECOVERING | CONNECTED | `recovery_threshold` consecutive successes |
| RECOVERING | OFFLINE | 1 failed health check |
| CONNECTED | DEGRADED | `failure_threshold` consecutive failures OR high latency (>threshold) |
| DEGRADED | OFFLINE | 1 failed health check |
| DEGRADED | CONNECTED | `recovery_threshold` consecutive successes (resets failure count) |

### Hysteresis Parameters
- **failure_threshold** (default: 3) — consecutive failures before degrading
- **recovery_threshold** (default: 2) — consecutive successes before recovering
- **degraded_latency_ms** (default: 1000) — latency above this counts as failure

## Files

| File | Purpose |
|------|---------|
| `ai/network/__init__.py` | Package init |
| `ai/network/models.py` | `NetworkState` enum, `HealthCheckResult`, `HealthMetrics` dataclasses |
| `ai/network/health.py` | `NetworkHealthManager` — state machine, latency tracking, background worker |
| `ai/network/routes.py` | `GET /network/status`, `POST /network/check` |
| `ai/config.py` | 7 `NETWORK_*` settings added |
| `ai/sync/manager.py` | Modified to accept `network_health` param |
| `ai/main.py` | Lifespan wiring for `NetworkHealthManager` |
| `server.ts` | Express proxy routes for `/api/network/*` |
| `src/types.ts` | `NetworkHealthState`, `NetworkHealthStatus` TypeScript types |

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `NETWORK_HEALTH_ENABLED` | `true` | Enable/disable health monitoring |
| `NETWORK_HEALTH_INTERVAL_SEC` | `30` | Seconds between health checks |
| `NETWORK_HEALTH_TIMEOUT_SEC` | `5` | Timeout per health check |
| `NETWORK_DEGRADED_LATENCY_MS` | `1000` | Latency above this counts as failure |
| `NETWORK_FAILURE_THRESHOLD` | `3` | Failures before DEGRADED |
| `NETWORK_RECOVERY_THRESHOLD` | `2` | Successes before CONNECTED |
| `NETWORK_HEALTH_WINDOW_SIZE` | `20` | Rolling latency window size |

## API

### `GET /api/network/status` (SYNC_READ — all roles)
Returns current network health metrics.

### `POST /api/network/check` (SYNC_CONTROL — ADMIN/OPERATOR only)
Triggers an immediate health check.

## Tests

28 tests covering:
- **State machine** (1-13): All transition paths, hysteresis, threshold counting
- **Latency** (14-17): Tracking, rolling average, bounded window, high-latency degradation
- **Sync integration** (18-21): Connectivity propagation, offline/recovery state sync
- **API/RBAC** (22-25): Permission checks, model structure
- **Resilience** (26-28): Worker lifecycle, AI independence, no secrets in metrics

## Integration Points

- **SyncManager**: Receives connectivity state updates from NetworkHealthManager
- **CentralSyncClient**: Reused for health check HTTP calls
- **AuditRepo**: Logs significant state transitions
- **Config**: Settings from `ai/config.py`
