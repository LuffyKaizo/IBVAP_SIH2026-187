"""add evidence table

Revision ID: 003_add_evidence
Revises: 002_add_profiles
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "003_add_evidence"
down_revision = "002_add_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.Text(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Text(),
            sa.ForeignKey("security_events.event_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "alert_id",
            sa.Text(),
            sa.ForeignKey("alerts.alert_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "camera_id",
            sa.Text(),
            sa.ForeignKey("cameras.camera_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("sha256_hash", sa.Text(), nullable=False),
        sa.Column("integrity_status", sa.Text(), nullable=False, server_default="VALID"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_evidence_event_id", "evidence", ["event_id"])
    op.create_index("idx_evidence_camera_id", "evidence", ["camera_id"])
    op.create_index("idx_evidence_timestamp", "evidence", ["timestamp"])


def downgrade() -> None:
    op.drop_index("idx_evidence_timestamp", table_name="evidence")
    op.drop_index("idx_evidence_camera_id", table_name="evidence")
    op.drop_index("idx_evidence_event_id", table_name="evidence")
    op.drop_table("evidence")
