"""FastAPI dependencies for authentication and authorization."""

import os

from fastapi import Depends, HTTPException, status, Query, WebSocket
from fastapi.security import OAuth2PasswordBearer

from ai.auth.jwt import decode_access_token
from ai.auth.models import (
    Permission, Role, UserContext, ROLE_PERMISSIONS,
)
from ai.config import is_production, settings
from ai.db.repositories.user_repo import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

_user_repo = UserRepository()

_DEV_BYPASS_TOKEN = "dev-bypass-token"
_DEV_ADMIN_USER = UserContext(
    user_id="dev-admin",
    email="admin@ibvap.local",
    role=Role.ADMIN,
    permissions=ROLE_PERMISSIONS.get(Role.ADMIN, []),
)


def _dev_bypass_enabled() -> bool:
    """Hardcoded bypass token is accepted ONLY with an explicit dev opt-in
    flag outside production. Production never honors it."""
    return (
        not is_production()
        and os.getenv("DEV_AUTH_BYPASS", "false").lower() == "true"
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> UserContext:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _dev_bypass_enabled() and token == _DEV_BYPASS_TOKEN:
        return _DEV_ADMIN_USER
    payload = decode_access_token(token, settings.SECRET_KEY)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await _user_repo.get_by_id(payload.sub)
    if user is None or not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled",
        )
    try:
        role = Role(user.role)
    except ValueError:
        role = Role.VIEWER
    return UserContext(
        user_id=user.user_id,
        email=user.email,
        role=role,
        permissions=ROLE_PERMISSIONS.get(role, []),
    )


def require_permission(permission: Permission):
    async def _check(user: UserContext = Depends(get_current_user)):
        if permission not in user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user
    return _check


async def get_user_from_token_query(token: str = Query(None)) -> UserContext:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    if _dev_bypass_enabled() and token == _DEV_BYPASS_TOKEN:
        return _DEV_ADMIN_USER
    payload = decode_access_token(token, settings.SECRET_KEY)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user = await _user_repo.get_by_id(payload.sub)
    if user is None or not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled",
        )
    try:
        role = Role(user.role)
    except ValueError:
        role = Role.VIEWER
    return UserContext(
        user_id=user.user_id,
        email=user.email,
        role=role,
        permissions=ROLE_PERMISSIONS.get(role, []),
    )


async def verify_ws_token(websocket: WebSocket) -> UserContext:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Not authenticated")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if _dev_bypass_enabled() and token == _DEV_BYPASS_TOKEN:
        return _DEV_ADMIN_USER
    payload = decode_access_token(token, settings.SECRET_KEY)
    if payload is None:
        await websocket.close(code=4001, reason="Invalid token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = await _user_repo.get_by_id(payload.sub)
    if user is None or not user.enabled:
        await websocket.close(code=4001, reason="User not found")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        role = Role(user.role)
    except ValueError:
        role = Role.VIEWER
    return UserContext(
        user_id=user.user_id,
        email=user.email,
        role=role,
        permissions=ROLE_PERMISSIONS.get(role, []),
    )
