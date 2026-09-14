"""Blockchain trust layer API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ai.auth.deps import require_permission
from ai.auth.models import Permission, UserContext
from ai.config import settings

router = APIRouter(prefix="/blockchain", tags=["blockchain"])

# Set by main.py at startup
_blockchain_service = None


def init_blockchain_routes(blockchain_service):
    global _blockchain_service
    _blockchain_service = blockchain_service


@router.get("/health")
async def blockchain_health(
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_READ)),
):
    """Blockchain ledger health check."""
    if not _blockchain_service:
        return {"healthy": False, "enabled": False, "reason": "service not initialized"}
    healthy = await _blockchain_service.health_check()
    return {"healthy": healthy, "enabled": settings.BLOCKCHAIN_ENABLED}


@router.get("/stats")
async def blockchain_stats(
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_READ)),
):
    """Blockchain ledger statistics."""
    if not _blockchain_service:
        return {"total_anchors": 0, "confirmed": 0, "pending": 0, "failed": 0}
    stats = await _blockchain_service.get_stats()
    return {
        "total_anchors": stats.total_anchors,
        "confirmed": stats.confirmed,
        "pending": stats.pending,
        "failed": stats.failed,
        "avg_confirmation_ms": stats.avg_confirmation_ms,
    }


@router.get("/anchors/{anchor_id}")
async def get_anchor(
    anchor_id: str,
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_READ)),
):
    """Retrieve a specific blockchain anchor."""
    if not _blockchain_service:
        return JSONResponse(status_code=503, content={"detail": "Blockchain service not available"})
    try:
        from ai.blockchain.repository import BlockchainAnchorRepository
        repo = BlockchainAnchorRepository()
        result = await repo.get_by_id(anchor_id)
        if result is None:
            return JSONResponse(status_code=404, content={"detail": "Anchor not found"})
        return result
    except Exception:
        return JSONResponse(status_code=500, content={"detail": "Internal error"})


@router.get("/evidence/{evidence_id}")
async def get_evidence_anchor(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_READ)),
):
    """Get the blockchain anchor for a specific evidence record."""
    if not _blockchain_service:
        return JSONResponse(status_code=503, content={"detail": "Blockchain service not available"})
    anchor = await _blockchain_service.get_evidence_anchor(evidence_id)
    if anchor is None:
        return JSONResponse(status_code=404, content={"detail": "No anchor found for this evidence"})
    return {
        "anchorId": anchor.anchor_id,
        "evidenceId": anchor.evidence_id,
        "sha256Hash": anchor.sha256_hash,
        "recordHash": anchor.record_hash,
        "txHash": anchor.tx_hash,
        "blockNumber": anchor.block_number,
        "status": anchor.status,
        "confirmationTimeMs": anchor.confirmation_time_ms,
        "timestamp": anchor.timestamp,
    }


@router.post("/evidence/{evidence_id}/anchor")
async def manual_anchor(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_ANCHOR)),
):
    """Manually trigger blockchain anchoring for evidence.

    Must retrieve evidence from DB — does NOT accept arbitrary hashes.
    """
    if not _blockchain_service:
        return JSONResponse(status_code=503, content={"detail": "Blockchain service not available"})
    if not settings.BLOCKCHAIN_ENABLED:
        return JSONResponse(status_code=400, content={"detail": "Blockchain is disabled"})

    # Get trusted evidence from DB
    trusted = await _blockchain_service._get_trusted_evidence(evidence_id)
    if trusted is None:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})

    anchor = await _blockchain_service.maybe_anchor(trusted)
    if anchor is None:
        # Try again with manual policy override
        from ai.blockchain.exceptions import DuplicateAnchorError
        try:
            stored_hash = trusted.get("sha256Hash", "")
            if not stored_hash:
                return JSONResponse(status_code=400, content={"detail": "Evidence has no hash"})
            anchor = await _blockchain_service._ledger.append(evidence_id, stored_hash)
            await _blockchain_service._audit_log(
                "blockchain.anchor", "evidence", evidence_id,
                {"anchor_id": anchor.anchor_id, "actor": _user.user_id},
            )
        except DuplicateAnchorError:
            return JSONResponse(status_code=409, content={"detail": "Evidence already anchored"})
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": "Anchoring failed: %s" % e})

    return {
        "anchorId": anchor.anchor_id,
        "evidenceId": anchor.evidence_id,
        "txHash": anchor.tx_hash,
        "blockNumber": anchor.block_number,
        "status": anchor.status,
    }


@router.post("/evidence/{evidence_id}/verify")
async def verify_evidence_on_chain(
    evidence_id: str,
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_READ)),
):
    """Verify evidence integrity against the blockchain."""
    if not _blockchain_service:
        return JSONResponse(status_code=503, content={"detail": "Blockchain service not available"})

    trusted = await _blockchain_service._get_trusted_evidence(evidence_id)
    if trusted is None:
        return JSONResponse(status_code=404, content={"detail": "Evidence not found"})

    result = await _blockchain_service.verify_evidence(trusted)
    return {
        "evidence_id": evidence_id,
        "verified": result.verified,
        "status": result.status,
        "local_hash": result.local_hash,
        "chain_hash": result.chain_hash,
        "anchor_id": result.anchor_id,
    }


@router.post("/anchors/{anchor_id}/reconcile")
async def reconcile_anchor(
    anchor_id: str,
    _user: UserContext = Depends(require_permission(Permission.BLOCKCHAIN_ANCHOR)),
):
    """Reconcile PostgreSQL anchor metadata against ledger proof."""
    if not _blockchain_service:
        return JSONResponse(status_code=503, content={"detail": "Blockchain service not available"})
    result = await _blockchain_service.reconcile_anchor(anchor_id)
    return {
        "matched": result.matched,
        "mismatches": result.mismatches,
    }
