"""Add profiles table for authentication and RBAC.

Revision ID: 002_add_profiles
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa

revision = "002_add_profiles"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False, server_default="VIEWER"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_profiles_email", "profiles", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_profiles_email", table_name="profiles")
    op.drop_table("profiles")
