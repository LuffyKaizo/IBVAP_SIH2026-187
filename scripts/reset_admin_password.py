"""Reset admin password. Requires ADMIN_PASSWORD from environment."""
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

async def main():
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not password:
        print("ERROR: ADMIN_PASSWORD environment variable is not set or empty.", flush=True)
        print("Set ADMIN_PASSWORD in your .env file before running this script.", flush=True)
        sys.exit(1)

    from ai.config import settings
    import bcrypt
    from ai.db.session import init_db, get_db_session
    from sqlalchemy import text

    ok = await init_db(settings.DATABASE_URL)
    if not ok:
        print("DB_INIT_FAILED")
        return

    async with get_db_session() as sess:
        r = await sess.execute(text("SELECT count(*) FROM users"))
        count = r.scalar()
        print(f"Users found: {count}")

        if count == 0:
            print("No users. Bootstrap will create admin on next startup.")
        else:
            new_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            result = await sess.execute(
                text("UPDATE users SET password_hash = :pwd WHERE email = :email"),
                {"pwd": new_hash, "email": "admin@ibvap.local"},
            )
            await sess.commit()
            print(f"Admin password reset. Rows affected: {result.rowcount}")

asyncio.run(main())
