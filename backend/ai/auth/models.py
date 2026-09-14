"""Auth models: roles, permissions, token payload, user context."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Role(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class Permission(str, Enum):
    CAMERA_READ = "CAMERA_READ"
    CAMERA_WRITE = "CAMERA_WRITE"
    CAMERA_CONTROL = "CAMERA_CONTROL"
    ZONE_READ = "ZONE_READ"
    ZONE_WRITE = "ZONE_WRITE"
    ALERT_READ = "ALERT_READ"
    ALERT_RESOLVE = "ALERT_RESOLVE"
    ANPR_READ = "ANPR_READ"
    EVIDENCE_READ = "EVIDENCE_READ"
    EVIDENCE_DELETE = "EVIDENCE_DELETE"
    REPORT_READ = "REPORT_READ"
    SETTINGS_READ = "SETTINGS_READ"
    SETTINGS_WRITE = "SETTINGS_WRITE"
    USER_ADMIN = "USER_ADMIN"
    DIAGNOSTICS = "DIAGNOSTICS"
    SYNC_READ = "SYNC_READ"
    SYNC_CONTROL = "SYNC_CONTROL"
    BLOCKCHAIN_READ = "BLOCKCHAIN_READ"
    BLOCKCHAIN_ANCHOR = "BLOCKCHAIN_ANCHOR"


ROLE_PERMISSIONS = {
    Role.ADMIN: [
        Permission.CAMERA_READ,
        Permission.CAMERA_WRITE,
        Permission.CAMERA_CONTROL,
        Permission.ZONE_READ,
        Permission.ZONE_WRITE,
        Permission.ALERT_READ,
        Permission.ALERT_RESOLVE,
        Permission.ANPR_READ,
        Permission.EVIDENCE_READ,
        Permission.EVIDENCE_DELETE,
        Permission.REPORT_READ,
        Permission.SETTINGS_READ,
        Permission.SETTINGS_WRITE,
        Permission.USER_ADMIN,
        Permission.DIAGNOSTICS,
        Permission.SYNC_READ,
        Permission.SYNC_CONTROL,
        Permission.BLOCKCHAIN_READ,
        Permission.BLOCKCHAIN_ANCHOR,
    ],
    Role.OPERATOR: [
        Permission.CAMERA_READ,
        Permission.CAMERA_CONTROL,
        Permission.ZONE_READ,
        Permission.ZONE_WRITE,
        Permission.ALERT_READ,
        Permission.ALERT_RESOLVE,
        Permission.ANPR_READ,
        Permission.EVIDENCE_READ,
        Permission.REPORT_READ,
        Permission.DIAGNOSTICS,
        Permission.SYNC_READ,
        Permission.SYNC_CONTROL,
        Permission.BLOCKCHAIN_READ,
        Permission.BLOCKCHAIN_ANCHOR,
    ],
    Role.VIEWER: [
        Permission.CAMERA_READ,
        Permission.ZONE_READ,
        Permission.ALERT_READ,
        Permission.ANPR_READ,
        Permission.EVIDENCE_READ,
        Permission.REPORT_READ,
        Permission.SETTINGS_READ,
        Permission.SYNC_READ,
        Permission.BLOCKCHAIN_READ,
    ],
}


@dataclass
class TokenPayload:
    sub: str
    email: str
    role: str
    exp: float
    iat: float


@dataclass
class UserContext:
    user_id: str
    email: str
    role: Role
    permissions: List[Permission] = field(default_factory=list)
