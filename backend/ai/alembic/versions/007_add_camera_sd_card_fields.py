"""add SD-card recording fallback fields to cameras

Revision ID: 007_add_camera_sd_card_fields
Revises: 006_add_blockchain_anchors
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "007_add_camera_sd_card_fields"
down_revision = "006_add_blockchain_anchors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("sd_card_capable", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("cameras", sa.Column("sd_card_status", sa.Text(), nullable=False, server_default="UNKNOWN"))
    op.add_column("cameras", sa.Column("sd_card_capacity_gb", sa.Float(), nullable=True))
    op.add_column("cameras", sa.Column("last_sync_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("cameras", sa.Column("pending_footage_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("cameras", sa.Column("last_offline_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("cameras", sa.Column("last_online_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "last_online_at")
    op.drop_column("cameras", "last_offline_at")
    op.drop_column("cameras", "pending_footage_count")
    op.drop_column("cameras", "last_sync_at")
    op.drop_column("cameras", "sd_card_capacity_gb")
    op.drop_column("cameras", "sd_card_status")
    op.drop_column("cameras", "sd_card_capable")
