"""add sync_queue table

Revision ID: 004_add_sync_queue
Revises: 003_add_evidence
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "004_add_sync_queue"
down_revision = "003_add_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_queue",
        sa.Column("sync_id", sa.Text(), primary_key=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False, server_default="CREATE"),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_sync_status", "sync_queue", ["status"])
    op.create_index("idx_sync_entity", "sync_queue", ["entity_type", "entity_id"])
    op.create_index("idx_sync_next_retry", "sync_queue", ["next_retry_at"])


def downgrade() -> None:
    op.drop_index("idx_sync_next_retry", table_name="sync_queue")
    op.drop_index("idx_sync_entity", table_name="sync_queue")
    op.drop_index("idx_sync_status", table_name="sync_queue")
    op.drop_table("sync_queue")
