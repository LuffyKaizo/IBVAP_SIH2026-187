"""FastAPI dependencies for Edge node authentication.

Provides require_edge_auth() — a dependency that validates Edge JWT tokens
and returns an EdgeTokenPayload.

This is SEPARATE from ai.auth.deps.get_current_user():
- Edge tokens use a different signing key
- Edge tokens have purpose="edge-sync" claim
- Edge tokens do NOT carry email/role claims
- Human JWTs cannot pass require_edge_auth()
- Edge JWTs cannot pass get_current_user()
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai.edge.auth import EdgeTokenManager
from ai.edge.models import EdgeTokenPayload

logger = logging.getLogger("ibvap.edge")

# Bearer token extraction (separate from human auth's OAuth2PasswordBearer)
_edge_bearer = HTTPBearer(auto_error=False)

# Module-level reference set by init_edge_routes()
_token_manager: Optional[EdgeTokenManager] = None


def init_edge_deps(token_manager: EdgeTokenManager) -> None:
    """Initialize Edge auth dependencies with the token manager."""
    global _token_manager
    _token_manager = token_manager


async def require_edge_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_edge_bearer),
) -> EdgeTokenPayload:
    """FastAPI dependency that validates Edge JWT tokens.

    Extracts Bearer token from Authorization header.
    Verifies it's an Edge token (not a human token).
    Returns EdgeTokenPayload on success.
    Raises 401 on failure.

    Usage:
        @router.post("/sync/events")
        async def sync_event(
            payload: EdgeTokenPayload = Depends(require_edge_auth),
        ):
            ...
    """
    if _token_manager is None:
        raise HTTPException(status_code=503, detail="Edge auth not configured")

    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials
    payload = _token_manager.verify_token(token)

    if payload is None:
        logger.warning("[EDGE_AUTH] Token verification failed")
        raise HTTPException(status_code=401, detail="Invalid or expired Edge token")

    # Update last_seen (throttled)
    await _token_manager.update_last_seen(payload.sub)

    return payload
