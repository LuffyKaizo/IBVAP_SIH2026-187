"""add edge_nodes table

Revision ID: 005_add_edge_nodes
Revises: 004_add_sync_queue
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "005_add_edge_nodes"
down_revision = "004_add_sync_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edge_nodes",
        sa.Column("node_id", sa.Text(), primary_key=True),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_edge_node_id", "edge_nodes", ["node_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_edge_node_id", table_name="edge_nodes")
    op.drop_table("edge_nodes")
