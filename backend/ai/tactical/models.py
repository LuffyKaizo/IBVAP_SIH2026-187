"""SQLAlchemy models for the tactical geospatial layer.

Tables are created at runtime via TacticalRepository.ensure_schema()
(CREATE TABLE IF NOT EXISTS — no auto-migration, no create_all) and
mirrored in alembic revision 008 for schema-as-code.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, Float, JSON, Text, TIMESTAMP

from ai.db.models import Base


def _utcnow():
    return datetime.now(timezone.utc)


class CameraGeoModel(Base):
    __tablename__ = "camera_geo"

    camera_id = Column(Text, primary_key=True)
    name = Column(Text, nullable=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    heading_deg = Column(Float, nullable=False, default=0.0)
    fov_deg = Column(Float, nullable=False, default=60.0)
    range_m = Column(Float, nullable=False, default=250.0)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow,
                        onupdate=_utcnow)


class ZeroLineModel(Base):
    __tablename__ = "tactical_zero_lines"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    camera_id = Column(Text, nullable=True)
    points = Column(JSON, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)


class BufferZoneModel(Base):
    __tablename__ = "tactical_buffer_zones"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    camera_id = Column(Text, nullable=True)
    polygon = Column(JSON, nullable=False)
    buffer_m = Column(Float, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=_utcnow)
