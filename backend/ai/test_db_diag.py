"""Quick diagnostic: why does event_repo.create fail?"""
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

async def check():
    await init_db(settings.DATABASE_URL)

    # Check constraints on security_events
    async with get_db_session() as session:
        r = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'security_events'::regclass
        """))
        print("security_events constraints:")
        for row in r.fetchall():
            print(f"  {row[0]} type={row[1]} def={row[2]}")

    # Check constraints on alerts
    async with get_db_session() as session:
        r = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'alerts'::regclass
        """))
        print("alerts constraints:")
        for row in r.fetchall():
            print(f"  {row[0]} type={row[1]} def={row[2]}")

    # Try a direct insert
    import uuid
    uid = str(uuid.uuid4())[:8]
    try:
        async with get_db_session() as session:
            await session.execute(text(f"""
                INSERT INTO security_events (event_id, event_type, severity, camera_id, track_id, object_class, timestamp, confidence, bbox, status)
                VALUES ('diag-{uid}', 'INTRUSION', 'HIGH', 'DIAG-TEST', 1, 'person', '2026-09-05T00:00:00Z', 0.9, '{{}}', 'DETECTED')
            """))
            print(f"Direct INSERT OK: diag-{uid}")
    except Exception as e:
        print(f"Direct INSERT FAILED: {type(e).__name__}: {e}")

    # Try via repository
    from ai.db.repositories import EventRepository
    from ai.events.engine import SecurityEvent
    repo = EventRepository()
    se = SecurityEvent(
        event_id=f"repo-{uid}", event_type="INTRUSION", severity="HIGH",
        camera_id="DIAG-TEST", zone_id="", zone_name="", track_id=1,
        object_class="person", timestamp="2026-09-05T00:00:00Z",
        confidence=0.9, bbox={}, status="DETECTED"
    )
    result = await repo.create(se)
    print(f"repo.create returned: {result}")

    # Verify row exists
    async with get_db_session() as session:
        r = await session.execute(text(f"SELECT event_id, status FROM security_events WHERE event_id='repo-{uid}'"))
        row = r.fetchone()
        print(f"Row in DB: {row}")

    await close_db()

asyncio.run(check())
