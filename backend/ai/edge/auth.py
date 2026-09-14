"""Edge node machine-to-machine authentication.

Provides EdgeTokenManager for issuing/verifying Edge JWTs and
AuthRateLimiter for protecting the auth endpoint against brute force.

Edge tokens are SEPARATE from human user JWTs:
- Different signing key (EDGE_TOKEN_SECRET vs SECRET_KEY)
- Different claims (purpose="edge-sync" vs email/role)
- Different verification paths (require_edge_auth vs get_current_user)
"""

import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from ai.edge.models import (
    EdgeNode,
    EdgeTokenPayload,
    EdgePermissions,
    EDGE_TOKEN_PURPOSE,
    EDGE_TOKEN_ISSUER_DEFAULT,
)
from ai.edge.registry import EdgeNodeRepository

logger = logging.getLogger("ibvap.edge")


# ──────────────────────────────────────────────────────────────
# Secret Hashing
# ──────────────────────────────────────────────────────────────

def hash_secret(plaintext: str) -> str:
    """Hash an Edge node secret using bcrypt. Never log the input."""
    return bcrypt.hashpw(
        plaintext.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def verify_secret(plaintext: str, secret_hash: str) -> bool:
    """Verify a plaintext secret against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plaintext.encode("utf-8"),
            secret_hash.encode("utf-8"),
        )
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Edge Token Manager
# ──────────────────────────────────────────────────────────────

class EdgeTokenManager:
    """Manages Edge node JWT lifecycle.

    Responsibilities:
    - Authenticate Edge nodes by ID + secret
    - Issue short-lived JWTs with edge-specific claims
    - Verify Edge tokens (separate from human JWT verification)
    - Track last_seen timestamps (throttled)
    """

    def __init__(
        self,
        token_secret: str,
        token_ttl: int = 300,
        issuer: str = EDGE_TOKEN_ISSUER_DEFAULT,
        node_registry: Optional[EdgeNodeRepository] = None,
        audit_repo=None,
        last_seen_interval: int = 60,
    ):
        if not token_secret:
            raise ValueError("EDGE_TOKEN_SECRET must be configured")
        self._token_secret = token_secret
        self._token_ttl = token_ttl
        self._issuer = issuer
        self._registry = node_registry
        self._audit_repo = audit_repo
        self._last_seen_interval = last_seen_interval
        self._last_seen_cache: dict[str, float] = {}

    async def authenticate(self, node_id: str, secret: str) -> Optional[str]:
        """Authenticate an Edge node and return a JWT token.

        Returns None on failure. Never logs the secret.
        """
        # 1. Look up node
        node = await self._registry.get_by_id(node_id) if self._registry else None
        if node is None:
            logger.warning("[EDGE_AUTH] Unknown node: %s", node_id)
            await self._audit_log("EDGE_AUTH_FAILURE", node_id, "unknown_node")
            return None

        # 2. Check enabled
        if not node.get("enabled", True):
            logger.warning("[EDGE_AUTH] Disabled node: %s", node_id)
            await self._audit_log("EDGE_AUTH_FAILURE", node_id, "node_disabled")
            return None

        # 3. Verify secret
        secret_hash = node.get("secret_hash", "")
        if not verify_secret(secret, secret_hash):
            logger.warning("[EDGE_AUTH] Invalid credentials: %s", node_id)
            await self._audit_log("EDGE_AUTH_FAILURE", node_id, "invalid_secret")
            return None

        # 4. Issue token
        token = self.create_token(node_id)
        logger.info("[EDGE_AUTH] Token issued for node: %s", node_id)
        await self._audit_log("EDGE_AUTH_SUCCESS", node_id, "token_issued")

        return token

    def create_token(self, node_id: str) -> str:
        """Create a signed Edge JWT with edge-specific claims."""
        now = time.time()
        payload = {
            "sub": node_id,
            "iss": self._issuer,
            "purpose": EDGE_TOKEN_PURPOSE,
            "iat": now,
            "exp": now + self._token_ttl,
            "jti": secrets.token_hex(16),
        }
        return jwt.encode(payload, self._token_secret, algorithm="HS256")

    def verify_token(self, token: str) -> Optional[EdgeTokenPayload]:
        """Verify an Edge JWT and return its payload.

        Returns None if:
        - Signature is invalid
        - Token is expired
        - Issuer is wrong
        - Purpose claim is missing or wrong
        """
        try:
            data = jwt.decode(
                token,
                self._token_secret,
                algorithms=["HS256"],
                issuer=self._issuer,
            )
            purpose = data.get("purpose")
            if purpose != EDGE_TOKEN_PURPOSE:
                return None

            return EdgeTokenPayload(
                sub=data["sub"],
                iss=data["iss"],
                purpose=data["purpose"],
                iat=data["iat"],
                exp=data["exp"],
                jti=data.get("jti", ""),
            )
        except JWTError:
            return None
        except (KeyError, TypeError):
            return None

    def is_edge_token(self, token: str) -> bool:
        """Check if a token is an Edge token without full verification."""
        payload = self.verify_token(token)
        return payload is not None

    @staticmethod
    def is_human_token_payload(decoded: dict) -> bool:
        """Check if a decoded JWT payload belongs to a human user.

        Human tokens have 'email' and 'role' claims.
        Edge tokens have 'purpose' claim.
        """
        return "email" in decoded and "role" in decoded and "purpose" not in decoded

    @staticmethod
    def is_edge_token_payload(decoded: dict) -> bool:
        """Check if a decoded JWT payload belongs to an Edge node."""
        return decoded.get("purpose") == EDGE_TOKEN_PURPOSE

    async def update_last_seen(self, node_id: str) -> None:
        """Update last_seen_at, throttled to once per interval."""
        now = time.time()
        last = self._last_seen_cache.get(node_id, 0)
        if now - last < self._last_seen_interval:
            return
        self._last_seen_cache[node_id] = now
        if self._registry:
            await self._registry.update_last_seen(node_id)

    async def _audit_log(self, action: str, node_id: str, detail: str) -> None:
        """Log security events. Never includes secrets or tokens."""
        if self._audit_repo:
            try:
                await self._audit_repo.log(
                    action=action,
                    entity_type="edge_node",
                    entity_id=node_id,
                    details={"result": detail},
                    actor="EDGE_AUTH",
                )
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────
# In-Memory Rate Limiter
# ──────────────────────────────────────────────────────────────

class AuthRateLimiter:
    """Sliding window rate limiter for Edge authentication failures.

    Tracks failures per key (node_id:client_ip) within a time window.
    Lightweight, in-memory, resets on restart. Suitable for single-node
    demo deployments; production should use infrastructure-level limiting.
    """

    MAX_KEYS = 10000  # Prevent memory exhaustion from diverse attacker IPs

    def __init__(self, max_failures: int = 5, window_sec: int = 300):
        self._max_failures = max_failures
        self._window_sec = window_sec
        self._failures: dict[str, list[float]] = {}

    def check_and_record(self, key: str) -> bool:
        """Check if request is allowed. Records failure if so.

        Returns True if allowed, False if rate limited.
        """
        now = time.time()
        self._cleanup(key, now)

        # Evict oldest keys if too many tracked
        if len(self._failures) > self.MAX_KEYS:
            self._evict_oldest()

        attempts = self._failures.get(key, [])
        if len(attempts) >= self._max_failures:
            return False

        attempts.append(now)
        self._failures[key] = attempts
        return True

    def _cleanup(self, key: str, now: float) -> None:
        """Remove expired entries for a key."""
        attempts = self._failures.get(key, [])
        cutoff = now - self._window_sec
        self._failures[key] = [t for t in attempts if t > cutoff]

    def _evict_oldest(self) -> None:
        """Remove the oldest 10% of keys to prevent memory exhaustion."""
        if not self._failures:
            return
        # Sort by most recent activity, remove oldest 10%
        sorted_keys = sorted(
            self._failures.keys(),
            key=lambda k: self._failures[k][-1] if self._failures[k] else 0,
        )
        evict_count = max(1, len(sorted_keys) // 10)
        for k in sorted_keys[:evict_count]:
            del self._failures[k]

    def reset(self, key: str) -> None:
        """Reset failure count for a key (e.g. on successful auth)."""
        self._failures.pop(key, None)


# ──────────────────────────────────────────────────────────────
# Bootstrap
# ──────────────────────────────────────────────────────────────

async def bootstrap_edge_node(
    registry: EdgeNodeRepository,
    node_id: str,
    secret: str,
    display_name: str = "",
) -> None:
    """Bootstrap an Edge node from environment configuration.

    Creates the node in the database if it doesn't exist.
    The secret is hashed before storage.
    Called during application startup.
    """
    if not node_id or not secret:
        return

    if len(secret) < 16:
        logger.warning("[EDGE] WARNING: EDGE_NODE_SECRET is shorter than 16 characters. Use a stronger secret for production.")

    existing = await registry.get_by_id(node_id)
    if existing:
        logger.info("[EDGE] Node already registered: %s", node_id)
        return

    secret_hash = hash_secret(secret)
    await registry.create(
        node_id=node_id,
        secret_hash=secret_hash,
        display_name=display_name or node_id,
    )
    logger.info("[EDGE] Bootstrap node registered: %s", node_id)
