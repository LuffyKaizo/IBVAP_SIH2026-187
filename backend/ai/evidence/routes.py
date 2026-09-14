"""Evidence management API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse

from ai.auth.deps import require_permission
from ai.auth.models import Permission, UserContext
from ai.config import settings

router = APIRouter(prefix="/evidence", tags=["evidence"])

# These are set by main.py at startup
_evidence_repo = None
_evidence_store = None
_evidence_capture = None
_blockchain_service = None


def init_evidence_routes(evidence_repo, evidence_store, evidence_capture, blockchain_service=None):
    global _evidence_repo, _evidence_store, _evidence_capture, _blockchain_service
    _evidence_repo = evidence_repo
    _evidence_store = evidence_store
    _evidence_capture = evidence_capture
    _blockchain_service = blockchain_service


@router.get("")
async def list_evidence(
    event_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: UserContext = Depends(require_permission(Permission.EVIDENCE_READ)),
):
    if not _evidence_repo:
        return {"evidence": [], "total": 0}
    if event_id:
        items = await _evidence_repo.list_for_event(event_id)
    elif camera_id:
        items = await _evidence_repo.list_for_camera(camera_id, limit=limit)
    else:
        items = await _evidence_repo.list_recent(limit=limit)
    return {"evidence": items, "total": len(items)}


@router.get("/{evidence_id}")
async def get_evidence(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.EVIDENCE_READ)),
):
    if not _evidence_repo:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    item = await _evidence_repo.get(evidence_id)
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    # Include blockchain anchor info if available
    if _blockchain_service:
        try:
            anchor = await _blockchain_service.get_evidence_anchor(evidence_id)
            if anchor:
                item["blockchainAnchor"] = {
                    "anchorId": anchor.anchor_id,
                    "txHash": anchor.tx_hash,
                    "blockNumber": anchor.block_number,
                    "status": anchor.status,
                    "recordHash": anchor.record_hash,
                }
        except Exception:
            pass
    return item


@router.get("/{evidence_id}/blockchain")
async def get_evidence_blockchain(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_READ)),
):
    """Return blockchain anchoring details for evidence."""
    if not _blockchain_service:
        return JSONResponse(status_code=503, content={"detail": "Blockchain service not available"})
    if not _evidence_repo:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    item = await _evidence_repo.get(evidence_id)
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    anchor = await _blockchain_service.get_evidence_anchor(evidence_id)
    if anchor is None:
        return {
            "evidence_id": evidence_id,
            "anchored": False,
            "anchor": None,
        }
    return {
        "evidence_id": evidence_id,
        "anchored": True,
        "anchor": {
            "anchorId": anchor.anchor_id,
            "txHash": anchor.tx_hash,
            "blockNumber": anchor.block_number,
            "status": anchor.status,
            "recordHash": anchor.record_hash,
            "sha256Hash": anchor.sha256_hash,
            "confirmationTimeMs": anchor.confirmation_time_ms,
            "timestamp": anchor.timestamp,
        },
    }


@router.get("/{evidence_id}/file")
async def download_evidence(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.EVIDENCE_READ)),
):
    if not _evidence_repo or not _evidence_store:
        return JSONResponse(status_code=404, content={"detail": "Evidence not available"})
    item = await _evidence_repo.get(evidence_id)
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    file_path = item.get("filePath", "")
    if not _evidence_store.exists(file_path):
        return JSONResponse(status_code=404, content={"detail": "Evidence file not found"})
    full_path = _evidence_store._full_path(file_path)
    return FileResponse(
        path=full_path,
        media_type=item.get("mimeType", "application/octet-stream"),
        filename=evidence_id + "." + (item.get("mimeType", "").split("/")[-1] or "bin"),
    )


@router.post("/{evidence_id}/verify")
async def verify_evidence(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.EVIDENCE_READ)),
):
    if not _evidence_repo or not _evidence_capture:
        return JSONResponse(status_code=404, content={"detail": "Evidence service not available"})
    item = await _evidence_repo.get(evidence_id)
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    is_valid = await _evidence_capture.verify_and_update(item)
    return {
        "evidence_id": evidence_id,
        "integrity_status": "VALID" if is_valid else "INTEGRITY_FAILURE",
        "expected_hash": item.get("sha256Hash", ""),
    }


@router.delete("/{evidence_id}")
async def delete_evidence(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.EVIDENCE_DELETE)),
):
    if not _evidence_repo:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    item = await _evidence_repo.get(evidence_id)
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})
    if _evidence_capture:
        await _evidence_capture.delete_evidence(item)
    else:
        await _evidence_repo.delete(evidence_id)
    return {"success": True, "deleted": evidence_id}
