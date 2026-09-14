"""Network health API routes — status and manual check."""

from fastapi import APIRouter, Depends

from ai.auth.deps import require_permission
from ai.auth.models import Permission, UserContext

router = APIRouter(prefix="/network", tags=["network"])

# Set by main.py at startup
_network_health = None
_sync_repo = None


def init_network_routes(network_health, sync_repo):
    global _network_health, _sync_repo
    _network_health = network_health
    _sync_repo = sync_repo


@router.get("/status")
async def network_status(
    _user: UserContext = Depends(require_permission(Permission.SYNC_READ)),
):
    """Return current network health status and sync queue info."""
    if not _network_health:
        return {
            "state": "OFFLINE",
            "central_reachable": False,
            "latency_ms": 0,
            "average_latency_ms": 0,
            "min_latency_ms": 0,
            "max_latency_ms": 0,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "offline_since": None,
            "recovery_started_at": None,
            "checks_performed": 0,
            "sync_pending": 0,
            "sync_failed": 0,
        }

    metrics = _network_health.get_metrics()
    counts = await _sync_repo.count_by_status() if _sync_repo else {
        "PENDING": 0, "IN_PROGRESS": 0, "FAILED": 0, "SYNCED": 0,
    }

    return {
        "state": metrics.state,
        "central_reachable": metrics.central_reachable,
        "latency_ms": metrics.latency_ms,
        "average_latency_ms": metrics.average_latency_ms,
        "min_latency_ms": metrics.min_latency_ms,
        "max_latency_ms": metrics.max_latency_ms,
        "consecutive_failures": metrics.consecutive_failures,
        "consecutive_successes": metrics.consecutive_successes,
        "last_success_at": metrics.last_success_at,
        "last_failure_at": metrics.last_failure_at,
        "offline_since": metrics.offline_since,
        "recovery_started_at": metrics.recovery_started_at,
        "checks_performed": metrics.checks_performed,
        "sync_pending": counts.get("PENDING", 0),
        "sync_failed": counts.get("FAILED", 0),
    }


@router.post("/check")
async def trigger_health_check(
    _user: UserContext = Depends(require_permission(Permission.SYNC_CONTROL)),
):
    """Manually trigger an immediate central connectivity check (ADMIN/OPERATOR only)."""
    if not _network_health:
        return {"error": "Network health monitor not available"}

    result = await _network_health.check()
    metrics = _network_health.get_metrics()

    return {
        "result": {
            "reachable": result.reachable,
            "latency_ms": result.latency_ms,
            "timestamp": result.timestamp,
            "error": result.error,
        },
        "state": metrics.state,
        "consecutive_failures": metrics.consecutive_failures,
        "consecutive_successes": metrics.consecutive_successes,
    }
