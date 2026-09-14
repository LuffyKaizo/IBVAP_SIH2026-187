"""SQLAlchemy ORM models for IBVAP PostgreSQL schema.

Defines tables: cameras, zones, security_events, alerts, anpr_records, audit_logs.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, Float, Integer, String, Text, TIMESTAMP, JSON, ForeignKey,
    Index,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


class CameraModel(Base):
    __tablename__ = "cameras"

    camera_id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    location = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False)
    camera_type = Column(Text, nullable=False, default="FIXED")
    enabled = Column(Boolean, nullable=False, default=True)
    sd_card_capable = Column(Boolean, nullable=False, default=False)
    sd_card_status = Column(Text, nullable=False, default="UNKNOWN")
    sd_card_capacity_gb = Column(Float, nullable=True)
    last_sync_at = Column(TIMESTAMP(timezone=True), nullable=True)
    pending_footage_count = Column(Integer, nullable=False, default=0)
    last_offline_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_online_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class ZoneModel(Base):
    __tablename__ = "zones"

    id = Column(Text, primary_key=True)
    camera_id = Column(Text, ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    points = Column(JSON, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    severity = Column(Text, nullable=False, default="CRITICAL")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("idx_zones_camera_id", "camera_id"),
    )


class SecurityEventModel(Base):
    __tablename__ = "security_events"

    event_id = Column(Text, primary_key=True)
    event_type = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    camera_id = Column(Text, ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    zone_id = Column(Text, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True)
    zone_name = Column(Text, nullable=True)
    track_id = Column(Integer, nullable=False)
    object_class = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    confidence = Column(Float, nullable=False)
    bbox = Column(JSON, nullable=False)
    status = Column(Text, nullable=False, default="DETECTED")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_events_camera_id", "camera_id"),
        Index("idx_events_timestamp", "timestamp"),
        Index("idx_events_status", "status"),
    )


class AlertModel(Base):
    __tablename__ = "alerts"

    alert_id = Column(Text, primary_key=True)
    event_id = Column(Text, ForeignKey("security_events.event_id", ondelete="SET NULL"), nullable=True)
    camera_id = Column(Text, ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    event_type = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    track_id = Column(Text, nullable=True)
    confidence = Column(Integer, nullable=True)
    zone = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="ACTIVE")
    source = Column(Text, nullable=False, default="AI")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_alerts_camera_id", "camera_id"),
        Index("idx_alerts_timestamp", "timestamp"),
        Index("idx_alerts_status", "status"),
    )


class AnprRecordModel(Base):
    __tablename__ = "anpr_records"

    record_id = Column(Text, primary_key=True)
    camera_id = Column(Text, ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    track_id = Column(Integer, nullable=False)
    vehicle_class = Column(Text, nullable=False)
    raw_plate_text = Column(Text, nullable=True)
    normalized_plate = Column(Text, nullable=True)
    corrected_plate = Column(Text, nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    plate_confidence = Column(Float, nullable=True)
    corrected = Column(Boolean, nullable=False, default=False)
    vehicle_bbox = Column(JSON, nullable=True)
    plate_bbox = Column(JSON, nullable=True)
    status = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    format_status = Column(Text, nullable=True)
    correction_note = Column(Text, nullable=True)
    observation_count = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_anpr_camera_id", "camera_id"),
        Index("idx_anpr_timestamp", "timestamp"),
        Index("idx_anpr_status", "status"),
        Index("idx_anpr_plate", "normalized_plate"),
    )


class ProfileModel(Base):
    __tablename__ = "profiles"

    user_id = Column(Text, primary_key=True)
    email = Column(Text, unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    full_name = Column(Text, nullable=True)
    role = Column(Text, nullable=False, default="VIEWER")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
    actor = Column(Text, nullable=True)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_timestamp", "timestamp"),
    )


class EvidenceModel(Base):
    __tablename__ = "evidence"

    evidence_id = Column(Text, primary_key=True)
    event_id = Column(Text, ForeignKey("security_events.event_id", ondelete="SET NULL"), nullable=True)
    alert_id = Column(Text, ForeignKey("alerts.alert_id", ondelete="SET NULL"), nullable=True)
    camera_id = Column(Text, ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    evidence_type = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(Text, nullable=False)
    sha256_hash = Column(Text, nullable=False)
    integrity_status = Column(Text, nullable=False, default="VALID")
    evidence_metadata = Column("metadata", JSON, nullable=True)
    created_by = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("idx_evidence_event_id", "event_id"),
        Index("idx_evidence_camera_id", "camera_id"),
        Index("idx_evidence_timestamp", "timestamp"),
    )


class SyncQueueModel(Base):
    __tablename__ = "sync_queue"

    sync_id = Column(Text, primary_key=True)
    entity_type = Column(Text, nullable=False)  # "EVENT" | "EVIDENCE"
    entity_id = Column(Text, nullable=False)
    operation = Column(Text, nullable=False, default="CREATE")
    status = Column(Text, nullable=False, default="PENDING")
    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(TIMESTAMP(timezone=True), nullable=True)
    next_retry_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
    synced_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_sync_status", "status"),
        Index("idx_sync_entity", "entity_type", "entity_id"),
        Index("idx_sync_next_retry", "next_retry_at"),
    )
