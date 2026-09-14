"""Initial schema — cameras, zones, security_events, alerts, anpr_records, audit_logs

Revision ID: 001_initial
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # cameras
    op.create_table(
        "cameras",
        sa.Column("camera_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("camera_type", sa.Text(), nullable=False, server_default="FIXED"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # zones
    op.create_table(
        "zones",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("camera_id", sa.Text(), sa.ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("points", postgresql.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("severity", sa.Text(), nullable=False, server_default="CRITICAL"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_zones_camera_id", "zones", ["camera_id"])

    # security_events
    op.create_table(
        "security_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("camera_id", sa.Text(), sa.ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False),
        sa.Column("zone_id", sa.Text(), sa.ForeignKey("zones.id", ondelete="SET NULL"), nullable=True),
        sa.Column("zone_name", sa.Text(), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("object_class", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("bbox", postgresql.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="DETECTED"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_events_camera_id", "security_events", ["camera_id"])
    op.create_index("idx_events_timestamp", "security_events", ["timestamp"])
    op.create_index("idx_events_status", "security_events", ["status"])

    # alerts
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), sa.ForeignKey("security_events.event_id", ondelete="SET NULL"), nullable=True),
        sa.Column("camera_id", sa.Text(), sa.ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("track_id", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("zone", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("source", sa.Text(), nullable=False, server_default="AI"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_alerts_camera_id", "alerts", ["camera_id"])
    op.create_index("idx_alerts_timestamp", "alerts", ["timestamp"])
    op.create_index("idx_alerts_status", "alerts", ["status"])

    # anpr_records
    op.create_table(
        "anpr_records",
        sa.Column("record_id", sa.Text(), primary_key=True),
        sa.Column("camera_id", sa.Text(), sa.ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_class", sa.Text(), nullable=False),
        sa.Column("raw_plate_text", sa.Text(), nullable=True),
        sa.Column("normalized_plate", sa.Text(), nullable=True),
        sa.Column("corrected_plate", sa.Text(), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("plate_confidence", sa.Float(), nullable=True),
        sa.Column("corrected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("vehicle_bbox", postgresql.JSON(), nullable=True),
        sa.Column("plate_bbox", postgresql.JSON(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("format_status", sa.Text(), nullable=True),
        sa.Column("correction_note", sa.Text(), nullable=True),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_anpr_camera_id", "anpr_records", ["camera_id"])
    op.create_index("idx_anpr_timestamp", "anpr_records", ["timestamp"])
    op.create_index("idx_anpr_status", "anpr_records", ["status"])
    op.create_index("idx_anpr_plate", "anpr_records", ["normalized_plate"])

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSON(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_audit_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("idx_audit_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("anpr_records")
    op.drop_table("alerts")
    op.drop_table("security_events")
    op.drop_table("zones")
    op.drop_table("cameras")
