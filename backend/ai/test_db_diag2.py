"""Diagnostic: test event insert after camera create."""
import asyncio, os
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from ai.db.session import init_db, get_db_session, close_db
from ai.config import settings
from sqlalchemy import text
from ai.db.repositories import CameraRepository, EventRepository
from ai.camera.config import CameraConfig
from ai.events.engine import SecurityEvent

async def check():
    await init_db(settings.DATABASE_URL)

    cam_repo = CameraRepository()
    event_repo = EventRepository()

    # 1. Create camera
    cfg = CameraConfig(camera_id="DIAG-FK", name="FK Test", location="Test",
                       source="rtsp://test", source_type="rtsp", enabled=True)
    c = await cam_repo.create(cfg)
    print(f"Camera create: {c}")

    # 2. Verify camera visible in new session
    async with get_db_session() as session:
        r = await session.execute(text("SELECT camera_id FROM cameras WHERE camera_id='DIAG-FK'"))
        row = r.fetchone()
        print(f"Camera visible: {row}")

    # 3. Try event insert via raw SQL
    try:
        async with get_db_session() as session:
            await session.execute(text(
                "INSERT INTO security_events (event_id, event_type, severity, camera_id, track_id, object_class, timestamp, confidence, bbox, status) "
                "VALUES ('diag-evt-1', 'INTRUSION', 'HIGH', 'DIAG-FK', 1, 'person', '2026-09-05T00:00:00Z', 0.9, '{}', 'DETECTED')"
            ))
            print("Raw SQL INSERT: OK")
    except Exception as e:
        print(f"Raw SQL INSERT FAILED: {type(e).__name__}: {e}")

    # 4. Try event insert via repo
    se = SecurityEvent(
        event_id="diag-evt-2", event_type="INTRUSION", severity="HIGH",
        camera_id="DIAG-FK", zone_id="", zone_name="", track_id=1,
        object_class="person", timestamp="2026-09-05T00:00:00Z",
        confidence=0.9, bbox={}, status="DETECTED"
    )
    result = await event_repo.create(se)
    print(f"Repo create: {result}")

    # 5. Check if rows exist
    async with get_db_session() as session:
        r = await session.execute(text("SELECT event_id, status FROM security_events WHERE camera_id='DIAG-FK'"))
        for row in r.fetchall():
            print(f"  Row: {row}")

    # Cleanup
    await cam_repo.delete("DIAG-FK")
    await close_db()

asyncio.run(check())
