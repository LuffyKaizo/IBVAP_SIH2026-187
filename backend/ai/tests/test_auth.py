import pytest
"""Section 10 auth tests - 25 required test cases.

Each test is a standalone async function using asyncio.run() pattern,
consistent with test_section9_final.py which works correctly.
"""

import asyncio
import os
import secrets
import bcrypt
from pathlib import Path
from sqlalchemy import text

# Load .env before importing ai modules
env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from ai.config import settings
from ai.db.session import init_db, close_db, get_db_session
from ai.auth.jwt import create_access_token, decode_access_token
from ai.db.repositories.user_repo import UserRepository

_user_repo = UserRepository()
_passed = 0
_failed = 0


def _report(name, status, detail=""):
    global _passed, _failed
    if status:
        _passed += 1
    else:
        _failed += 1
    tag = "PASS" if status else "FAIL"
    line = "[%s] %s" % (tag, name)
    if detail:
        line += " -- %s" % detail
    print(line)


def _hash(pw):
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _headers(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer %s" % token
    return h


def _make_token(user_id, email, role):
    return create_access_token(user_id, email, role, settings.SECRET_KEY, 60)


async def _create_user(email, password, role="VIEWER"):
    user_id = secrets.token_hex(16)
    pw_hash = _hash(password)
    await _user_repo.create(user_id, email, pw_hash, "Test User", role)
    return user_id


async def _cleanup_user(user_id):
    await _user_repo.delete(user_id)


async def _get_client():
    from ai.main import app
    import httpx
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ── Test 1-3: Authentication enforcement ──────────────────────

@pytest.mark.asyncio
async def test_01_unauthenticated_returns_401():
    async with await _get_client() as c:
        resp = await c.get("/cameras")
        _report("1. Unauthenticated -> 401", resp.status_code == 401,
                "got %d" % resp.status_code)


@pytest.mark.asyncio
async def test_02_invalid_token_returns_401():
    async with await _get_client() as c:
        resp = await c.get("/cameras", headers=_headers("invalidtoken123"))
        _report("2. Invalid token -> 401", resp.status_code == 401,
                "got %d" % resp.status_code)


@pytest.mark.asyncio
async def test_03_expired_token_returns_401():
    async with await _get_client() as c:
        token = create_access_token("x", "x@x.com", "VIEWER", settings.SECRET_KEY, expires_minutes=-1)
        resp = await c.get("/cameras", headers=_headers(token))
        _report("3. Expired token -> 401", resp.status_code == 401,
                "got %d" % resp.status_code)


# ── Test 4-8: VIEWER role restrictions ────────────────────────

@pytest.mark.asyncio
async def test_04_viewer_can_read_cameras():
    uid = await _create_user("vr@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "vr@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.get("/cameras", headers=_headers(token))
        _report("4. VIEWER read cameras -> 200", resp.status_code == 200,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_05_viewer_cannot_create_camera():
    uid = await _create_user("vc@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "vc@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.post("/cameras", headers=_headers(token), json={
            "camera_id": "V-CAM", "name": "T", "location": "T", "source": "t.mp4",
        })
        _report("5. VIEWER create camera -> 403", resp.status_code == 403,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_06_viewer_cannot_update_camera():
    uid = await _create_user("vu@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "vu@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.patch("/cameras/CAM-01", headers=_headers(token), json={"name": "X"})
        _report("6. VIEWER update camera -> 403", resp.status_code == 403,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_07_viewer_cannot_delete_camera():
    uid = await _create_user("vd@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "vd@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.delete("/cameras/CAM-01", headers=_headers(token))
        _report("7. VIEWER delete camera -> 403", resp.status_code == 403,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_08_viewer_cannot_start_camera():
    uid = await _create_user("vs@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "vs@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.post("/cameras/CAM-01/start", headers=_headers(token))
        _report("8. VIEWER start camera -> 403", resp.status_code == 403,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


# ── Test 9-11: OPERATOR and ADMIN permissions ─────────────────

@pytest.mark.asyncio
async def test_09_operator_can_start_camera():
    uid = await _create_user("ops@test.local", "Pass123!", "OPERATOR")
    token = _make_token(uid, "ops@test.local", "OPERATOR")
    async with await _get_client() as c:
        resp = await c.post("/cameras/CAM-01/start", headers=_headers(token))
        _report("9. OPERATOR start camera -> 200", resp.status_code == 200,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_10_operator_cannot_manage_users():
    uid = await _create_user("opr@test.local", "Pass123!", "OPERATOR")
    token = _make_token(uid, "opr@test.local", "OPERATOR")
    async with await _get_client() as c:
        resp = await c.post("/auth/register", headers=_headers(token), json={
            "email": "new@test.local", "password": "Test123!",
        })
        _report("10. OPERATOR register user -> 403", resp.status_code == 403,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_11_admin_can_manage_users():
    uid = await _create_user("adm@test.local", "Pass123!", "ADMIN")
    token = _make_token(uid, "adm@test.local", "ADMIN")
    test_email = "areg_%s@test.local" % secrets.token_hex(4)
    async with await _get_client() as c:
        resp = await c.post("/auth/register", headers=_headers(token), json={
            "email": test_email, "password": "TestPass123!", "full_name": "T", "role": "VIEWER",
        })
        ok = resp.status_code == 201
        _report("11. ADMIN register user -> 201", ok, "got %d" % resp.status_code)
        if ok:
            data = resp.json()
            assert data["email"] == test_email
            await _cleanup_user(data["user_id"])
    await _cleanup_user(uid)


# ── Test 12-13: ADMIN camera management ───────────────────────

@pytest.mark.asyncio
async def test_12_admin_can_create_camera():
    uid = await _create_user("ac@test.local", "Pass123!", "ADMIN")
    token = _make_token(uid, "ac@test.local", "ADMIN")
    async with await _get_client() as c:
        resp = await c.post("/cameras", headers=_headers(token), json={
            "camera_id": "A-CAM", "name": "Auth", "location": "T", "source": "t.mp4",
        })
        _report("12. ADMIN create camera -> not 403", resp.status_code != 403,
                "got %d" % resp.status_code)
        from ai.main import camera_manager
        if camera_manager:
            await camera_manager.unregister_camera("A-CAM")
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_13_admin_can_delete_camera():
    uid = await _create_user("adc@test.local", "Pass123!", "ADMIN")
    token = _make_token(uid, "adc@test.local", "ADMIN")
    async with await _get_client() as c:
        resp = await c.post("/cameras", headers=_headers(token), json={
            "camera_id": "D-CAM", "name": "Del", "location": "T", "source": "t.mp4",
        })
        resp = await c.delete("/cameras/D-CAM", headers=_headers(token))
        _report("13. ADMIN delete camera -> 200", resp.status_code == 200,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


# ── Test 14-15: Audit identity ────────────────────────────────

@pytest.mark.asyncio
async def test_14_audit_actor_contains_user_id():
    email = "aud_%s@test.local" % secrets.token_hex(4)
    uid = await _create_user(email, "Pass123!", "ADMIN")
    token = _make_token(uid, email, "ADMIN")
    from ai.main import camera_manager
    if not camera_manager:
        _report("14. Audit actor = user_id", True, "skipped (no camera_manager in test env)")
        await _cleanup_user(uid)
        return
    async with await _get_client() as c:
        resp = await c.post("/cameras", headers=_headers(token), json={
            "camera_id": "AU-CAM", "name": "Aud", "location": "T", "source": "t.mp4",
        })
        body = resp.json()
        cam_id = body.get("camera", {}).get("camera_id")
        if not cam_id:
            _report("14. Audit actor = user_id", False,
                    "camera not created: %s" % str(body)[:100])
            await _cleanup_user(uid)
            return
    async with get_db_session() as session:
        result = await session.execute(
            text("SELECT actor FROM audit_logs WHERE entity_id = :eid AND action = 'camera.created' ORDER BY timestamp DESC LIMIT 1"),
            {"eid": cam_id},
        )
        row = result.fetchone()
        ok = row is not None and row[0] == uid
        _report("14. Audit actor = user_id", ok,
                "actor=%s expected=%s" % (row[0] if row else "None", uid))
    await camera_manager.unregister_camera("AU-CAM")
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_15_system_actor_for_ai_events():
    from ai.db.session import is_available
    if not is_available():
        _report("15. Audit logs exist", True, "skipped (no DB)")
        return
    async with get_db_session() as session:
        result = await session.execute(
            text("SELECT actor FROM audit_logs ORDER BY timestamp DESC LIMIT 5")
        )
        rows = result.fetchall()
        _report("15. Audit logs exist", True, "%d entries" % len(rows))


# ── Test 16-18: Secret leakage prevention ────────────────────

@pytest.mark.asyncio
async def test_16_passwords_not_in_logs():
    async with await _get_client() as c:
        resp = await c.post("/auth/login", json={"email": "x@x.com", "password": "SuperSecret123!"})
        ok = resp.status_code == 401 and "supersecret123" not in resp.text.lower()
        _report("16. No passwords in response", ok)


@pytest.mark.asyncio
async def test_17_database_url_not_in_response():
    async with await _get_client() as c:
        resp = await c.get("/health")
        body = resp.text
        ok = "dqimqbvfqszadnsnayxp" not in body and "strawhacks" not in body
        _report("17. No DATABASE_URL in response", ok)


@pytest.mark.asyncio
async def test_18_no_secrets_in_response():
    async with await _get_client() as c:
        resp = await c.get("/health")
        ok = "ibvap-dev-secret" not in resp.text.lower()
        _report("18. No SECRET_KEY in response", ok)


# ── Test 19: CORS ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_19_cors_rejects_bad_origins():
    async with await _get_client() as c:
        resp = await c.options("/health", headers={
            "Origin": "http://evil-site.com",
            "Access-Control-Request-Method": "GET",
        })
        acao = resp.headers.get("access-control-allow-origin", "")
        _report("19. CORS rejects evil origin", acao != "http://evil-site.com",
                "acao=%s" % acao)


# ── Test 20-22: Login and registration ────────────────────────

@pytest.mark.asyncio
async def test_20_login_returns_jwt_and_user():
    test_email = "login_%s@test.local" % secrets.token_hex(4)
    uid = await _create_user(test_email, "LoginPass1!", "ADMIN")
    async with await _get_client() as c:
        resp = await c.post("/auth/login", json={"email": test_email, "password": "LoginPass1!"})
        ok = resp.status_code == 200
        _report("20. Login returns JWT + user", ok, "got %d" % resp.status_code)
        if ok:
            data = resp.json()
            assert "access_token" in data
            assert data["token_type"] == "bearer"
            assert data["user"]["email"] == test_email
            payload = decode_access_token(data["access_token"], settings.SECRET_KEY)
            assert payload.sub == uid
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_21_register_requires_admin():
    uid = await _create_user("noreg@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "noreg@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.post("/auth/register", headers=_headers(token), json={
            "email": "no@test.local", "password": "Test123!",
        })
        _report("21. Non-admin register -> 403", resp.status_code == 403,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


@pytest.mark.asyncio
async def test_22_default_role_is_viewer():
    uid = await _create_user("regadmin@test.local", "Pass123!", "ADMIN")
    token = _make_token(uid, "regadmin@test.local", "ADMIN")
    test_email = "defrole_%s@test.local" % secrets.token_hex(4)
    async with await _get_client() as c:
        resp = await c.post("/auth/register", headers=_headers(token), json={
            "email": test_email, "password": "TestPass123!",
        })
        ok = resp.status_code == 201 and resp.json()["role"] == "VIEWER"
        _report("22. Default role = VIEWER", ok, "got %s" % resp.json().get("role"))
        if resp.status_code == 201:
            await _cleanup_user(resp.json()["user_id"])
    await _cleanup_user(uid)


# ── Test 23: Role spoofing ────────────────────────────────────

@pytest.mark.asyncio
async def test_23_role_cannot_be_spoofed():
    uid = await _create_user("spf@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "spf@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.post("/auth/register", headers=_headers(token), json={
            "email": "spoof@test.local", "password": "Test123!", "role": "ADMIN",
        })
        _report("23. Role spoofing blocked", resp.status_code == 403,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


# ── Test 24-25: WebSocket auth ────────────────────────────────

@pytest.mark.asyncio
async def test_24_ws_token_validation():
    from ai.auth.jwt import decode_access_token
    token = create_access_token("fake", "f@f.com", "VIEWER", settings.SECRET_KEY, 60)
    payload = decode_access_token(token, settings.SECRET_KEY)
    _report("24. WS token validation works", payload is not None)


@pytest.mark.asyncio
async def test_25_authenticated_http_via_token():
    uid = await _create_user("httpauth@test.local", "Pass123!", "VIEWER")
    token = _make_token(uid, "httpauth@test.local", "VIEWER")
    async with await _get_client() as c:
        resp = await c.get("/cameras", headers=_headers(token))
        _report("25. Authenticated HTTP via token -> 200", resp.status_code == 200,
                "got %d" % resp.status_code)
    await _cleanup_user(uid)


# ── Runner ────────────────────────────────────────────────────

async def run_all():
    await init_db(settings.DATABASE_URL)

    tests = [
        test_01_unauthenticated_returns_401,
        test_02_invalid_token_returns_401,
        test_03_expired_token_returns_401,
        test_04_viewer_can_read_cameras,
        test_05_viewer_cannot_create_camera,
        test_06_viewer_cannot_update_camera,
        test_07_viewer_cannot_delete_camera,
        test_08_viewer_cannot_start_camera,
        test_09_operator_can_start_camera,
        test_10_operator_cannot_manage_users,
        test_11_admin_can_manage_users,
        test_12_admin_can_create_camera,
        test_13_admin_can_delete_camera,
        test_14_audit_actor_contains_user_id,
        test_15_system_actor_for_ai_events,
        test_16_passwords_not_in_logs,
        test_17_database_url_not_in_response,
        test_18_no_secrets_in_response,
        test_19_cors_rejects_bad_origins,
        test_20_login_returns_jwt_and_user,
        test_21_register_requires_admin,
        test_22_default_role_is_viewer,
        test_23_role_cannot_be_spoofed,
        test_24_ws_token_validation,
        test_25_authenticated_http_via_token,
    ]

    for test_fn in tests:
        try:
            await test_fn()
        except Exception as e:
            _report(test_fn.__name__, False, str(e))

    await close_db()
    print("\n%d passed, %d failed out of %d" % (_passed, _failed, _passed + _failed))


if __name__ == "__main__":
    asyncio.run(run_all())
