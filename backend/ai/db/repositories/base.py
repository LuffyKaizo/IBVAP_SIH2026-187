"""Base repository with common async CRUD patterns.

Repositories do NOT store sessions. Each operation creates its own session
via get_db_session(). This ensures:
- No shared AsyncSession across camera pipelines
- Each transaction commits independently
- Each session closes after its operation
"""

import logging
from typing import Optional

from ai.db.session import get_db_session

logger = logging.getLogger("ibvap.db")

# Track last error time to avoid log spam
_last_error_times: dict = {}
_ERROR_LOG_INTERVAL = 30.0  # seconds between repeated error logs for same key


def _should_log_error(key: str) -> bool:
    """Rate-limit repeated error logs for the same operation."""
    import time
    now = time.time()
    last = _last_error_times.get(key, 0)
    if now - last >= _ERROR_LOG_INTERVAL:
        _last_error_times[key] = now
        return True
    return False


async def db_operation(operation_name: str, operation_fn):
    """Execute a database operation with per-operation session lifecycle.

    Args:
        operation_name: Name for logging (e.g. "camera.create")
        operation_fn: Async function that takes a session and returns a result

    Returns:
        Result of operation_fn on success, None on failure.
        Each operation gets its own session, commits, and closes.
    """
    if not is_db_available():
        return None

    async with get_db_session() as session:
        if session is None:
            return None
        try:
            return await operation_fn(session)
        except Exception as e:
            if _should_log_error(operation_name):
                logger.warning("[DB] %s failed: %s: %s", operation_name, type(e).__name__, e)
            return None


def is_db_available() -> bool:
    """Check if database engine is initialized."""
    from ai.db.session import _engine
    return _engine is not None
