"""Auth routes: login, register, me, logout."""

import secrets
import bcrypt
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status

from ai.auth.deps import get_current_user, require_permission
from ai.auth.jwt import create_access_token
from ai.auth.models import Permission, Role, UserContext
from ai.config import settings
from ai.db.repositories.user_repo import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])
_user_repo = UserRepository()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


@dataclass
class LoginRequest:
    email: str
    password: str


@dataclass
class RegisterRequest:
    email: str
    password: str
    full_name: str = ""
    role: str = "VIEWER"


@dataclass
class TokenResponse:
    access_token: str
    token_type: str
    user: dict


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await _user_repo.get_by_email(req.email)
    if user is None or not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not _verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = create_access_token(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        secret_key=settings.SECRET_KEY,
        expires_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={
            "user_id": user.user_id,
            "email": user.email,
            "full_name": user.full_name or "",
            "role": user.role,
        },
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    req: RegisterRequest,
    _admin: UserContext = Depends(require_permission(Permission.USER_ADMIN)),
):
    existing = await _user_repo.get_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    try:
        role = Role(req.role)
    except ValueError:
        role = Role.VIEWER

    user_id = secrets.token_hex(16)
    password_hash = _hash_password(req.password)
    user = await _user_repo.create(
        user_id=user_id,
        email=req.email,
        password_hash=password_hash,
        full_name=req.full_name or None,
        role=role.value,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )
    return {
        "user_id": user.user_id,
        "email": user.email,
        "full_name": user.full_name or "",
        "role": user.role,
    }


@router.get("/me")
async def get_me(user: UserContext = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role.value,
        "permissions": [p.value for p in user.permissions],
    }


@router.post("/logout")
async def logout(_user: UserContext = Depends(get_current_user)):
    return {"success": True, "detail": "Logged out"}


@router.post("/screening-login", response_model=TokenResponse)
async def screening_login():
    """Screening-mode auto-login: returns a real JWT for the configured admin user.

    Available ONLY when SCREENING_MODE=true (server-side env var).
    No password required — the endpoint is an opt-in demo/screening mechanism.
    Uses the ACTUAL admin user from the database; never fabricates an identity.
    """
    import os
    if os.getenv("SCREENING_MODE", "false").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Screening mode not enabled",
        )

    admin_email = settings.ADMIN_EMAIL
    if not admin_email:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_EMAIL not configured",
        )

    user = await _user_repo.get_by_email(admin_email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Admin user not found for {admin_email}. Run bootstrap first.",
        )
    if not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Admin user {admin_email} is disabled",
        )

    token = create_access_token(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        secret_key=settings.SECRET_KEY,
        expires_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={
            "user_id": user.user_id,
            "email": user.email,
            "full_name": user.full_name or "",
            "role": user.role,
        },
    )


async def bootstrap_admin(user_repo: UserRepository):
    count = await user_repo.count()
    if count > 0:
        return
    admin_email = settings.ADMIN_EMAIL
    admin_password = settings.ADMIN_PASSWORD or secrets.token_urlsafe(16)
    user_id = secrets.token_hex(16)
    password_hash = _hash_password(admin_password)
    await user_repo.create(
        user_id=user_id,
        email=admin_email,
        password_hash=password_hash,
        full_name="System Administrator",
        role=Role.ADMIN.value,
    )
    print("[AUTH] Bootstrap admin created: %s" % admin_email)
    if not settings.ADMIN_PASSWORD:
        print("[AUTH] Generated admin password: %s" % admin_password)
        print("[AUTH] SAVE THIS PASSWORD - it will not be shown again")
