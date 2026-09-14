"""add blockchain_anchors table

Revision ID: 006_add_blockchain_anchors
Revises: 005_add_edge_nodes
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "006_add_blockchain_anchors"
down_revision = "005_add_edge_nodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blockchain_anchors",
        sa.Column("anchor_id", sa.Text(), primary_key=True),
        sa.Column(
            "evidence_id",
            sa.Text(),
            sa.ForeignKey("evidence.evidence_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sha256_hash", sa.Text(), nullable=False),
        sa.Column("record_hash", sa.Text(), nullable=False),
        sa.Column("tx_hash", sa.Text(), nullable=False),
        sa.Column("block_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("previous_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column(
            "confirmation_time_ms",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_anchor_evidence_id", "blockchain_anchors", ["evidence_id"])
    op.create_index("idx_anchor_status", "blockchain_anchors", ["status"])
    op.create_index("idx_anchor_created_at", "blockchain_anchors", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_anchor_created_at", table_name="blockchain_anchors")
    op.drop_index("idx_anchor_status", table_name="blockchain_anchors")
    op.drop_index("idx_anchor_evidence_id", table_name="blockchain_anchors")
    op.drop_table("blockchain_anchors")
