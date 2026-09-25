"""Shared test configuration for Section 10 auth tests."""

import secrets
import pytest
import pytest_asyncio
import bcrypt

from ai.config import settings
from ai.auth.jwt import create_access_token
from ai.db.session import init_db, close_db, is_available
from ai.db.repositories.user_repo import UserRepository

_user_repo = UserRepository()

ADMIN_EMAIL = "test_admin_%s@test.local" % secrets.token_hex(4)
ADMIN_PASSWORD = "TestAdmin@2026"
OPERATOR_EMAIL = "test_operator_%s@test.local" % secrets.token_hex(4)
OPERATOR_PASSWORD = "TestOperator@2026"
VIEWER_EMAIL = "test_viewer_%s@test.local" % secrets.token_hex(4)
VIEWER_PASSWORD = "TestViewer@2026"

_admin_user_id = None
_operator_user_id = None
_viewer_user_id = None


@pytest.fixture(autouse=True)
def _ensure_current_event_loop():
    """Python 3.14: asyncio.get_event_loop() raises when no loop is set.

    Some suites (test_evidence, test_sync) call
    asyncio.get_event_loop().run_until_complete(...) directly, while other
    tests use asyncio.run()/loop.close() which clear the current loop — so
    whether these tests pass depended on test execution order. Ensure every
    test starts with a usable current loop.
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except Exception:
        asyncio.set_event_loop(asyncio.new_event_loop())
    yield


def _create_user(email, password, role="VIEWER"):
    user_id = secrets.token_hex(16)
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return user_id, email, password_hash, role


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    ok = await init_db(settings.DATABASE_URL)
    if not ok:
        yield
        return
    yield
    await close_db()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_users():
    from ai.db.session import is_available
    if not is_available():
        yield
        return

    global _admin_user_id, _operator_user_id, _viewer_user_id

    _admin_user_id, _, admin_hash, _ = _create_user(ADMIN_EMAIL, ADMIN_PASSWORD, "ADMIN")
    _operator_user_id, _, op_hash, _ = _create_user(OPERATOR_EMAIL, OPERATOR_PASSWORD, "OPERATOR")
    _viewer_user_id, _, viewer_hash, _ = _create_user(VIEWER_EMAIL, VIEWER_PASSWORD, "VIEWER")

    await _user_repo.create(_admin_user_id, ADMIN_EMAIL, admin_hash, "Test Admin", "ADMIN")
    await _user_repo.create(_operator_user_id, OPERATOR_EMAIL, op_hash, "Test Operator", "OPERATOR")
    await _user_repo.create(_viewer_user_id, VIEWER_EMAIL, viewer_hash, "Test Viewer", "VIEWER")

    yield

    await _user_repo.delete(_admin_user_id)
    await _user_repo.delete(_operator_user_id)
    await _user_repo.delete(_viewer_user_id)


@pytest.fixture(scope="session")
def tokens():
    admin_token = create_access_token(_admin_user_id, ADMIN_EMAIL, "ADMIN", settings.SECRET_KEY, 60)
    operator_token = create_access_token(_operator_user_id, OPERATOR_EMAIL, "OPERATOR", settings.SECRET_KEY, 60)
    viewer_token = create_access_token(_viewer_user_id, VIEWER_EMAIL, "VIEWER", settings.SECRET_KEY, 60)
    return admin_token, operator_token, viewer_token


@pytest.fixture(scope="session")
def user_ids():
    return _admin_user_id, _operator_user_id, _viewer_user_id
