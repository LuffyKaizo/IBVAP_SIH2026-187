"""Async database session management for IBVAP.

Uses SQLAlchemy 2.0 async engine with asyncpg driver.
Provides connection pooling, per-operation sessions, and thread-safe scheduling.

Key design:
- Engine + session factory are module-level singletons (created once)
- Each database operation creates its OWN AsyncSession via get_db_session()
- Sessions commit and close after each operation
- Thread-safe helper for scheduling persistence from camera worker threads
"""

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[sessionmaker] = None
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_captured_at = 0.0
_shutdown_pending = False
_pending_tasks: list = []
_pending_lock = threading.Lock()


def _mask_url(url: str) -> str:
    """Return safe representation of database URL (no password)."""
    if not url:
        return "(not configured)"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or "unknown"
        port = parsed.port or 5432
        db = parsed.path.lstrip("/") or "postgres"
        return f"{host}:{port}/{db}"
    except Exception:
        return "(parse error)"


async def init_db(database_url: str = "") -> bool:
    """Initialize database engine and connection pool.

    Returns True if connection successful, False otherwise.
    Does NOT crash on failure — logs error and returns False.
    """
    global _engine, _session_factory, _main_event_loop, _loop_captured_at

    if not database_url:
        from ai.config import settings
        database_url = settings.DATABASE_URL

    if not database_url:
        print("[DB] DATABASE_URL not configured — running without persistence")
        return False

    # Capture the main event loop for thread-safe scheduling
    try:
        _main_event_loop = asyncio.get_running_loop()
        _loop_captured_at = time.time()
    except RuntimeError:
        _main_event_loop = None

    # Convert postgresql:// to postgresql+asyncpg:// for async driver
    async_url = database_url
    if async_url.startswith("postgresql://"):
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif async_url.startswith("postgres://"):
        async_url = async_url.replace("postgres://", "postgresql+asyncpg://", 1)

    # Convert sslmode=require to ssl=require for asyncpg
    if "sslmode=require" in async_url:
        async_url = async_url.replace("sslmode=require", "ssl=require")
    elif "sslmode=verify-full" in async_url:
        async_url = async_url.replace("sslmode=verify-full", "ssl=verify-full")
    elif "sslmode=disable" in async_url:
        async_url = async_url.replace("sslmode=disable", "ssl=disable")

    try:
        _engine = create_async_engine(
            async_url,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Test connection
        async with _engine.connect() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()

        print("[DB] Connected to PostgreSQL: %s" % _mask_url(database_url))
        return True

    except Exception as e:
        print("[DB] Connection failed: %s — %s" % (type(e).__name__, e))
        _engine = None
        _session_factory = None
        return False


async def close_db():
    """Dispose engine and close all connections."""
    global _engine, _session_factory, _shutdown_pending, _pending_tasks

    _shutdown_pending = True

    # Wait for pending tasks with a bounded timeout
    if _pending_tasks:
        print("[DB] Waiting for %d pending persistence tasks..." % len(_pending_tasks))
        deadline = time.time() + 5.0
        while _pending_tasks and time.time() < deadline:
            await asyncio.sleep(0.1)
        if _pending_tasks:
            print("[DB] %d tasks still pending after timeout, cancelling" % len(_pending_tasks))
            for task in _pending_tasks:
                task.cancel()
            _pending_tasks.clear()

    if _engine:
        try:
            await _engine.dispose()
        except Exception:
            pass
        _engine = None
        _session_factory = None
        print("[DB] Connection pool disposed")


@asynccontextmanager
async def get_db_session():
    """Get an async database session with per-operation lifecycle.

    Each call creates a NEW AsyncSession. The session is committed on success,
    rolled back on error, and always closed.

    Usage:
        async with get_db_session() as session:
            if session:
                result = await session.execute(...)

    Yields AsyncSession or None if DB unavailable.
    """
    if _session_factory is None:
        yield None
        return

    session = _session_factory()
    try:
        yield session
        if session.is_active:
            await session.commit()
    except Exception as e:
        try:
            if session.is_active:
                await session.rollback()
        except Exception:
            pass
        print("[DB] Session error: %s" % type(e).__name__)
    finally:
        try:
            await session.close()
        except Exception:
            pass


def schedule_async(coro):
    """Schedule an async coroutine from a native thread onto the main event loop.

    Thread-safe. Uses call_soon_threadsafe() instead of ensure_future().
    Does NOT create event loops inside worker threads.

    Returns the concurrent.futures.Future if scheduled, None if scheduling
    failed or shutdown pending.
    """
    global _shutdown_pending

    if _shutdown_pending:
        return None

    loop = _main_event_loop
    if loop is None or loop.is_closed():
        return None

    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)

        # Track the task for graceful shutdown
        with _pending_lock:
            _pending_tasks.append(future)

        # Clean up completed tasks periodically
        def _cleanup(f):
            with _pending_lock:
                if future in _pending_tasks:
                    _pending_tasks.remove(future)

        future.add_done_callback(_cleanup)
        return future

    except RuntimeError:
        # Event loop closed or not running
        return None
    except Exception:
        return None


def is_db_available() -> bool:
    """Check if database is available."""
    return _engine is not None


# Backward compatibility alias
is_available = is_db_available


def get_engine() -> Optional[AsyncEngine]:
    """Get the current async engine (or None if not initialized)."""
    return _engine
