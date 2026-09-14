"""Check profiles table and reset admin password."""
import sys, asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def main():
    from ai.config import settings
    from ai.db.session import init_db, get_db_session
    from sqlalchemy import text

    ok = await init_db(settings.DATABASE_URL)
    print("DB init:", ok, flush=True)
    if not ok:
        return

    async with get_db_session() as sess:
        r = await sess.execute(text("SELECT count(*) FROM profiles"))
        count = r.scalar()
        print(f"Profiles: {count}", flush=True)

        r2 = await sess.execute(text("SELECT email, role, substring(password_hash, 1, 30) FROM profiles LIMIT 5"))
        for row in r2.fetchall():
            print(f"  {row[0]} | {row[1]} | {row[2]}...", flush=True)

asyncio.run(main())
