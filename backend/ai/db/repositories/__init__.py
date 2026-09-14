"""Repository layer for IBVAP database access."""

from ai.db.repositories.camera_repo import CameraRepository
from ai.db.repositories.zone_repo import ZoneRepository
from ai.db.repositories.event_repo import EventRepository
from ai.db.repositories.alert_repo import AlertRepository
from ai.db.repositories.anpr_repo import AnprRepository
from ai.db.repositories.audit_repo import AuditRepository
from ai.db.repositories.user_repo import UserRepository
from ai.db.repositories.evidence_repo import EvidenceRepository
from ai.db.repositories.sync_repo import SyncQueueRepository

__all__ = [
    "CameraRepository",
    "ZoneRepository",
    "EventRepository",
    "AlertRepository",
    "AnprRepository",
    "AuditRepository",
    "UserRepository",
    "EvidenceRepository",
    "SyncQueueRepository",
]
