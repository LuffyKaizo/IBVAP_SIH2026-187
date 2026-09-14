"""Edge node data models.

Defines Edge node identity, token payload, and authorization constants.
Edge tokens are SEPARATE from human JWT tokens — they use different signing
keys, different claims, and different verification paths.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ──────────────────────────────────────────────────────────────
# Edge Node Identity
# ──────────────────────────────────────────────────────────────

@dataclass
class EdgeNode:
    """Represents a registered Edge AI node."""
    node_id: str
    secret_hash: str
    display_name: str
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None


# ──────────────────────────────────────────────────────────────
# Edge Token Payload
# ──────────────────────────────────────────────────────────────

# Token purpose claim — distinguishes Edge tokens from human tokens
EDGE_TOKEN_PURPOSE = "edge-sync"
EDGE_TOKEN_ISSUER_DEFAULT = "ibvap-edge"

# Human token purpose (for cross-validation)
HUMAN_TOKEN_ISSUER = "ibvap"


@dataclass
class EdgeTokenPayload:
    """Decoded Edge JWT claims.

    Edge tokens carry:
    - sub: node_id (NOT user_id)
    - iss: "ibvap-edge"
    - purpose: "edge-sync"
    - iat: issued-at
    - exp: expiration
    - jti: unique token ID
    """
    sub: str        # node_id
    iss: str        # issuer
    purpose: str    # "edge-sync"
    iat: float      # issued-at (unix epoch)
    exp: float      # expiration (unix epoch)
    jti: str        # unique token ID


# ──────────────────────────────────────────────────────────────
# Edge Authorization
# ──────────────────────────────────────────────────────────────

class EdgePermissions:
    """What an authenticated Edge node is allowed to do.

    Edge nodes have a FIXED set of permissions — no role-based granularity.
    They are machine principals, not human users.
    """
    # Allowed
    CAN_SYNC_EVENT = True
    CAN_SYNC_EVIDENCE_METADATA = True
    CAN_SYNC_EVIDENCE_FILE = True
    CAN_HEALTH_CHECK = True

    # Denied (human-only operations)
    CAN_READ_NETWORK_STATUS = False
    CAN_ADMIN = False
    CAN_MANAGE_CAMERAS = False
    CAN_MANAGE_SETTINGS = False
    CAN_DELETE_EVIDENCE = False
    CAN_MANAGE_USERS = False
    CAN_MANUAL_SYNC_CONTROL = False

    # Denied (blockchain operations are human-only)
    CAN_BLOCKCHAIN_READ = False
    CAN_BLOCKCHAIN_ANCHOR = False


# ──────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────

@dataclass
class EdgeAuthRequest:
    """POST /edge/auth/token request body."""
    node_id: str
    secret: str


@dataclass
class EdgeTokenResponse:
    """POST /edge/auth/token response body."""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 300
    node_id: str = ""
