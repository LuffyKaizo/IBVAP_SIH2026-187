"""add tactical geospatial tables (camera_geo, zero lines, buffer zones)

Revision ID: 008_add_tactical_geo
Revises: 007_add_camera_sd_card_fields
Create Date: 2026-09-27
"""

from alembic import op
import sqlalchemy as sa


revision = "008_add_tactical_geo"
down_revision = "007_add_camera_sd_card_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: TacticalRepository.ensure_schema() may have already created
    # these tables at runtime (same columns) — skip them instead of failing.
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "camera_geo" not in existing:
        op.create_table(
            "camera_geo",
            sa.Column("camera_id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("lat", sa.Float(), nullable=False),
            sa.Column("lon", sa.Float(), nullable=False),
            sa.Column("heading_deg", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("fov_deg", sa.Float(), nullable=False, server_default=sa.text("60")),
            sa.Column("range_m", sa.Float(), nullable=False, server_default=sa.text("250")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if "tactical_zero_lines" not in existing:
        op.create_table(
            "tactical_zero_lines",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("camera_id", sa.Text(), nullable=True),
            sa.Column("points", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if "tactical_buffer_zones" not in existing:
        op.create_table(
            "tactical_buffer_zones",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("camera_id", sa.Text(), nullable=True),
            sa.Column("polygon", sa.JSON(), nullable=False),
            sa.Column("buffer_m", sa.Float(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "tactical_buffer_zones" in existing:
        op.drop_table("tactical_buffer_zones")
    if "tactical_zero_lines" in existing:
        op.drop_table("tactical_zero_lines")
    if "camera_geo" in existing:
        op.drop_table("camera_geo")
