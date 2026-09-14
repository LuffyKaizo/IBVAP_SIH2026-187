"""Synchronization API routes — status and manual trigger."""

from fastapi import APIRouter, Depends

from ai.auth.deps import require_permission
from ai.auth.models import Permission, UserContext

router = APIRouter(prefix="/sync", tags=["sync"])

# Set by main.py at startup
_sync_manager = None
_sync_repo = None


def init_sync_routes(sync_manager, sync_repo):
    global _sync_manager, _sync_repo
    _sync_manager = sync_manager
    _sync_repo = sync_repo


@router.get("/status")
async def sync_status(
    _user: UserContext = Depends(require_permission(Permission.SYNC_READ)),
):
    """Return current synchronization status."""
    state = _sync_manager.get_status() if _sync_manager else {
        "state": "OFFLINE", "enabled": False,
        "lastSuccessAt": None, "lastFailureAt": None,
    }
    counts = await _sync_repo.count_by_status() if _sync_repo else {
        "PENDING": 0, "IN_PROGRESS": 0, "FAILED": 0, "SYNCED": 0,
    }
    return {
        "state": state["state"],
        "enabled": state["enabled"],
        "pending": counts.get("PENDING", 0),
        "in_progress": counts.get("IN_PROGRESS", 0),
        "failed": counts.get("FAILED", 0),
        "synced": counts.get("SYNCED", 0),
        "lastSuccessAt": state["lastSuccessAt"],
        "lastFailureAt": state["lastFailureAt"],
    }


@router.post("/run")
async def trigger_sync(
    _user: UserContext = Depends(require_permission(Permission.SYNC_CONTROL)),
):
    """Manually trigger a synchronization pass (ADMIN/OPERATOR only)."""
    if not _sync_manager:
        return {"triggered": False, "error": "Sync manager not available"}
    stats = await _sync_manager.run_sync_pass()
    return {"triggered": True, "stats": stats}
