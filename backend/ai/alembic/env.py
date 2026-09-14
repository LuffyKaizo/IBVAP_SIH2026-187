"""Alembic environment for IBVAP async PostgreSQL migrations."""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add project root to path so we can import ai modules
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_ai_dir = os.path.dirname(os.path.dirname(__file__))
if _ai_dir not in sys.path:
    sys.path.insert(0, _ai_dir)

# Load .env file from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(_project_root, ".env"))

from ai.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Read DATABASE_URL from environment (never from ini file)
DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_url():
    """Get async database URL from environment."""
    url = DATABASE_URL
    if not url:
        print("[ALEMBIC] WARNING: DATABASE_URL not set")
        return ""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    # Convert sslmode=require to ssl=require for asyncpg
    if "sslmode=require" in url:
        url = url.replace("sslmode=require", "ssl=require")
    elif "sslmode=verify-full" in url:
        url = url.replace("sslmode=verify-full", "ssl=verify-full")
    elif "sslmode=disable" in url:
        url = url.replace("sslmode=disable", "ssl=disable")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    if not url:
        print("[ALEMBIC] Skipping offline migration: no DATABASE_URL")
        return
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async online mode."""
    url = get_url()
    if not url:
        print("[ALEMBIC] Skipping migration: no DATABASE_URL")
        return

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    import asyncio
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
