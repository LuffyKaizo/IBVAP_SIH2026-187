"""Edge node authentication API.

POST /edge/auth/token — Authenticate Edge node and receive a short-lived JWT.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ai.edge.auth import EdgeTokenManager, AuthRateLimiter
from ai.edge.models import EdgeAuthRequest, EdgeTokenResponse

logger = logging.getLogger("ibvap.edge")

router = APIRouter(prefix="/edge", tags=["edge"])

# Module-level references set by init_edge_routes()
_token_manager: Optional[EdgeTokenManager] = None
_rate_limiter: Optional[AuthRateLimiter] = None


def init_edge_routes(
    token_manager: EdgeTokenManager,
    rate_limiter: AuthRateLimiter,
) -> None:
    """Initialize Edge routes with dependencies."""
    global _token_manager, _rate_limiter
    _token_manager = token_manager
    _rate_limiter = rate_limiter


class _EdgeAuthBody(BaseModel):
    """Request body for Edge authentication."""
    node_id: str
    secret: str

    model_config = {"str_max_length": 256}


@router.post("/auth/token")
async def get_edge_token(
    body: _EdgeAuthBody,
    request: Request,
) -> dict:
    """Authenticate an Edge node and return a short-lived access token.

    Security:
    - Validates node_id and secret against the registry
    - Rate limits repeated failures per node_id + client IP
    - Never logs the secret
    - Never logs the access token
    """
    if _token_manager is None:
        raise HTTPException(status_code=503, detail="Edge auth not configured")

    # Rate limit check
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{body.node_id}:{client_ip}"

    if _rate_limiter and not _rate_limiter.check_and_record(rate_key):
        logger.warning("[EDGE_AUTH] Rate limited: node=%s ip=%s", body.node_id, client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts. Try again later.",
        )

    # Authenticate
    token = await _token_manager.authenticate(body.node_id, body.secret)

    if token is None:
        raise HTTPException(status_code=401, detail="Invalid node credentials")

    # Reset rate limiter on success
    if _rate_limiter:
        _rate_limiter.reset(rate_key)

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": _token_manager._token_ttl,
        "node_id": body.node_id,
    }
