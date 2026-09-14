"""Create admin@ibvap.local user. Requires ADMIN_PASSWORD from environment."""
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
    from ai.db.session import init_db
    from ai.db.repositories.user_repo import UserRepository

    ok = await init_db(settings.DATABASE_URL)
    print("DB init:", ok, flush=True)
    if not ok:
        return

    user_repo = UserRepository()

    existing = await user_repo.get_by_email("admin@ibvap.local")
    if existing:
        print("Admin user exists. Updating password...", flush=True)
        import bcrypt
        new_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        await user_repo.update(existing.user_id, password_hash=new_hash)
        print("Admin password updated.", flush=True)
    else:
        print("Creating admin@ibvap.local...", flush=True)
        import bcrypt
        import secrets
        user_id = secrets.token_hex(16)
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = await user_repo.create(
            user_id=user_id,
            email="admin@ibvap.local",
            password_hash=password_hash,
            full_name="System Administrator",
            role="ADMIN",
        )
        if user:
            print(f"Admin created: {user.email} (id={user.user_id})", flush=True)
        else:
            print("FAILED to create admin", flush=True)

asyncio.run(main())
