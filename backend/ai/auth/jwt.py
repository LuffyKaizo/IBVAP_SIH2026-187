"""JWT token creation and verification."""

import time
from typing import Optional

from jose import jwt, JWTError

from ai.auth.models import TokenPayload


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    secret_key: str,
    expires_minutes: int = 60,
) -> str:
    now = time.time()
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + (expires_minutes * 60),
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_access_token(token: str, secret_key: str) -> Optional[TokenPayload]:
    try:
        data = jwt.decode(token, secret_key, algorithms=["HS256"])
        return TokenPayload(
            sub=data["sub"],
            email=data["email"],
            role=data["role"],
            exp=data["exp"],
            iat=data["iat"],
        )
    except (JWTError, KeyError):
        return None
