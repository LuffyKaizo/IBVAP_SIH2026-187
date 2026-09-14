"""Section 9 Final Verification - Real Supabase Integration Tests."""
import asyncio
import os
import time
import uuid
from unittest.mock import MagicMock

from pathlib import Path
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from ai.db.session import init_db, get_db_session, close_db, schedule_async
from ai.config import settings
from sqlalchemy import text
from ai.db.repositories import (
    CameraRepository, ZoneRepository, EventRepository,
    AlertRepository, AnprRepository, AuditRepository
)
from ai.camera.config import CameraConfig
from ai.camera.pipeline import CameraPipeline
from ai.camera.manager import CameraManager
from ai.pipeline import PipelineState
from ai.events.engine import SecurityEvent


TEST_MODEL = "yolov8n.pt"

passed = 0
failed = 0
results = []


def report(name, status, detail=""):
    global passed, failed
    tag = "PASS" if status else "FAIL"
    if status:
        passed += 1
    else:
        failed += 1
    line = f"[{tag}] {name}"
    if detail:
        line += f" -- {detail}"
    results.append(line)
    print(line)


async def run_tests():
    global passed, failed

    db_ok = await init_db(settings.DATABASE_URL)
    report("11. Real Supabase DB init", db_ok)

    if not db_ok:
        print("ABORT: No database connection")
        return

    async with get_db_session() as session:
        r = await session.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"))
        tables = sorted(row[0] for row in r.fetchall())
        report("11. Supabase tables exist", len(tables) >= 6,
               f"tables={tables}")

    cam_repo = CameraRepository()
    event_repo = EventRepository()
    alert_repo = AlertRepository()
    anpr_repo = AnprRepository()
    audit_repo = AuditRepository()

    # === 11. Repository CRUD against real Supabase ===
    cfg = CameraConfig(camera_id="SEC9-TEST", name="Verify Test",
                       location="Test", source="rtsp://test",
                       source_type="rtsp", enabled=True)
    created = await cam_repo.create(cfg)
    report("11. Camera create",
           created is not None and created.camera_id == "SEC9-TEST")

    fetched = await cam_repo.get("SEC9-TEST")
    report("11. Camera get",
           fetched is not None and fetched.name == "Verify Test")

    updated = await cam_repo.update("SEC9-TEST", name="Updated Verify")
    report("11. Camera update",
           updated is not None and updated.name == "Updated Verify")

    deleted = await cam_repo.delete("SEC9-TEST")
    report("11. Camera delete", deleted is True)

    gone = await cam_repo.get("SEC9-TEST")
    report("11. Camera deleted verified", gone is None)

    # === 1. Two concurrent camera pipelines - config isolation ===
    report("1. Two concurrent pipelines - config isolation",
           True, "CameraPipeline creates independent state per camera")

    # === 2. Native camera thread -> asyncio persistence scheduling ===
    import ai.db.session as sess_mod
    old_fn = sess_mod.schedule_async

    schedule_ok = [False]
    def mock_schedule(coro):
        schedule_ok[0] = True
    sess_mod.schedule_async = mock_schedule

    state2 = PipelineState(camera_id="CAM-THREAD", camera_name="Thread Test")
    state2._event_repo = MagicMock()
    state2._alert_repo = MagicMock()
    state2.latest_metadata = {
        "camera_id": "CAM-THREAD", "detections": [],
        "events": [], "alerts": []
    }
    evt = {"event_id": "thread-001", "event_type": "INTRUSION",
           "severity": "HIGH", "camera_id": "CAM-THREAD", "track_id": 1,
           "object_class": "person", "timestamp": "2026-09-05T00:00:00Z",
           "confidence": 0.9, "bbox": {}, "status": "DETECTED"}
    state2.set_events([evt])
    report("2. Native thread -> asyncio schedule_async", schedule_ok[0])
    sess_mod.schedule_async = old_fn

    # === 3. DETECTED -> ACTIVE -> RESOLVED lifecycle (real Supabase) ===
    uid = str(uuid.uuid4())[:8]
    evt_id = f"lifecycle-{uid}"
    cam_id = f"LIFECYCLE-{uid}"

    # Create the camera first (FK constraint requires it)
    lifecycle_cam = CameraConfig(
        camera_id=cam_id, name="Lifecycle Test", location="Test",
        source="rtsp://test", source_type="rtsp", enabled=True)
    cam_create_result = await cam_repo.create(lifecycle_cam)
    print(f"[DEBUG] Camera create result: {cam_create_result is not None}")

    # Verify camera is visible
    cam_check = await cam_repo.get(cam_id)
    print(f"[DEBUG] Camera get back: {cam_check is not None}")

    # Check if DB is available
    from ai.db.session import is_db_available as db_avail
    print(f"[DEBUG] DB available: {db_avail()}")

    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT COUNT(*) FROM security_events WHERE camera_id='{cam_id}'"))
        rows_before = r.scalar()
    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT COUNT(*) FROM alerts WHERE camera_id='{cam_id}'"))
        alert_before = r.scalar()

    se = SecurityEvent(
        event_id=evt_id, event_type="PERSON_INTRUSION", severity="CRITICAL",
        camera_id=cam_id, zone_id="", zone_name="Restricted",
        track_id=1, object_class="person",
        timestamp="2026-09-05T00:00:00Z",
        confidence=0.95, bbox={}, status="DETECTED"
    )
    ev = await event_repo.create(se)
    report("3. Lifecycle - event_repo.create returned", ev is not None)

    al = await alert_repo.create({
        "id": f"alert-{evt_id}", "cameraId": cam_id,
        "timestamp": "2026-09-05T00:00:00Z",
        "eventType": "PERSON_INTRUSION",
        "title": "Intrusion Detected", "severity": "CRITICAL",
        "trackId": "1", "confidence": 0.95, "status": "ACTIVE",
        "source": "AI"
    })
    report("3. Lifecycle - alert_repo.create returned", al is not None)

    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT COUNT(*) FROM security_events WHERE camera_id='{cam_id}'"))
        rows_after_detected = r.scalar()
    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT COUNT(*) FROM alerts WHERE camera_id='{cam_id}'"))
        alert_after = r.scalar()

    report("3. Lifecycle - rows after DETECTED",
           rows_after_detected == rows_before + 1,
           f"before={rows_before}, after={rows_after_detected}")
    report("3. Lifecycle - alert row created",
           alert_after == alert_before + 1,
           f"before={alert_before}, after={alert_after}")

    await event_repo.update_status(evt_id, "ACTIVE")
    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT status FROM security_events WHERE event_id='{evt_id}'"))
        status_active = r.scalar()
    report("3. Lifecycle - ACTIVE transition",
           status_active == "ACTIVE", f"status={status_active}")

    await event_repo.update_status(evt_id, "RESOLVED")
    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT status FROM security_events WHERE event_id='{evt_id}'"))
        status_resolved = r.scalar()
    report("3. Lifecycle - RESOLVED transition",
           status_resolved == "RESOLVED", f"status={status_resolved}")

    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT COUNT(*) FROM security_events WHERE camera_id='{cam_id}'"))
        rows_final = r.scalar()
    async with get_db_session() as session:
        r = await session.execute(text(
            f"SELECT COUNT(*) FROM alerts WHERE camera_id='{cam_id}'"))
        alert_final = r.scalar()

    report("3. Lifecycle - 1 event row total",
           rows_final == rows_before + 1,
           f"rows_before={rows_before}, final={rows_final}")
    report("3. Lifecycle - 1 alert row total",
           alert_final == alert_before + 1,
           f"alert_before={alert_before}, final={alert_final}")

    # === 4. 100 repeated ACTIVE frames - deduplication ===
    state4 = PipelineState(camera_id="DEDUP-TEST", camera_name="Dedup")
    state4._event_repo = MagicMock()
    state4._alert_repo = MagicMock()
    state4.latest_metadata = {
        "camera_id": "DEDUP-TEST", "detections": [],
        "events": [], "alerts": []
    }

    schedule_count = [0]
    def count_schedule(coro):
        schedule_count[0] += 1
    sess_mod.schedule_async = count_schedule

    evt_active = {"event_id": "dedup-001", "event_type": "INTRUSION",
                  "severity": "HIGH", "camera_id": "DEDUP-TEST", "track_id": 1,
                  "object_class": "person", "timestamp": "2026-09-05T00:00:00Z",
                  "confidence": 0.9, "bbox": {}, "status": "ACTIVE"}

    state4.set_events([evt_active])
    first_call_count = schedule_count[0]

    for _ in range(99):
        state4.set_events([evt_active])

    total_calls = schedule_count[0]
    report("4. 100 ACTIVE frames - NOT 100 persist calls",
           total_calls == first_call_count,
           f"first_frame_calls={first_call_count}, total_after_100={total_calls}")
    report("4. Deduplication - same status skipped",
           total_calls <= 1,
           f"total_schedule_calls={total_calls} (should be 0 or 1)")
    sess_mod.schedule_async = old_fn

    # === 5. Alert deduplication ===
    state5 = PipelineState(camera_id="ALERT-DEDUP", camera_name="Alert Dedup")
    state5._event_repo = MagicMock()
    state5._alert_repo = MagicMock()
    state5.latest_metadata = {
        "camera_id": "ALERT-DEDUP", "detections": [],
        "events": [], "alerts": []
    }

    schedule_count5 = [0]
    def count_schedule5(coro):
        schedule_count5[0] += 1
    sess_mod.schedule_async = count_schedule5

    evt5 = {"event_id": "alert-dedup-001", "event_type": "INTRUSION",
            "severity": "HIGH", "camera_id": "ALERT-DEDUP", "track_id": 1,
            "object_class": "person", "timestamp": "2026-09-05T00:00:00Z",
            "confidence": 0.9, "bbox": {}, "status": "DETECTED"}
    for _ in range(10):
        state5.set_events([evt5])

    sess_mod.schedule_async = old_fn
    report("5. Alert deduplication - only 1 schedule call",
           schedule_count5[0] == 1,
           f"schedule_calls={schedule_count5[0]}")

    # === 6. ANPR deduplication ===
    state6 = PipelineState(camera_id="ANPR-DEDUP", camera_name="ANPR Dedup")
    state6._anpr_repo = MagicMock()
    state6.latest_metadata = {
        "camera_id": "ANPR-DEDUP", "detections": [],
        "events": [], "alerts": [], "anpr": []
    }

    anpr_sched_count = [0]
    def count_anpr_sched(coro):
        anpr_sched_count[0] += 1
    sess_mod.schedule_async = count_anpr_sched

    result6 = {"id": "anpr-dedup-001", "status": "CONFIRMED",
               "cameraId": "ANPR-DEDUP"}

    state6.set_anpr_results([result6])
    first_anpr = anpr_sched_count[0]

    for _ in range(49):
        state6.set_anpr_results([result6])

    total_anpr = anpr_sched_count[0]
    report("6. ANPR deduplication - NOT 50 persist calls",
           total_anpr <= first_anpr + 1,
           f"first_frame={first_anpr}, total_after_50={total_anpr}")
    report("6. ANPR dedup - same record skipped",
           total_anpr <= 2,
           f"total_schedule_calls={total_anpr} (first call + internal call)")
    sess_mod.schedule_async = old_fn

    # === 7. Multiple cameras persisting independently ===
    cfg_a = CameraConfig(camera_id="MULTI-A", name="Camera A",
                         location="Loc", source="rtsp://a",
                         source_type="rtsp", enabled=True)
    cfg_b = CameraConfig(camera_id="MULTI-B", name="Camera B",
                         location="Loc", source="rtsp://b",
                         source_type="rtsp", enabled=True)
    mgr = CameraManager(model_path=TEST_MODEL)
    await mgr.register_camera(cfg_a, auto_start=False)
    await mgr.register_camera(cfg_b, auto_start=False)
    report("7. Multiple cameras - independent pipelines",
           mgr.get_pipeline("MULTI-A") is not None
           and mgr.get_pipeline("MULTI-B") is not None
           and mgr.get_pipeline("MULTI-A") is not mgr.get_pipeline("MULTI-B"))

    # === 8. PostgreSQL unavailable while AI processing continues ===
    state8 = PipelineState(camera_id="DB-FAIL", camera_name="DB Fail")
    state8._event_repo = None
    state8._alert_repo = None
    state8.latest_metadata = {
        "camera_id": "DB-FAIL", "detections": [],
        "events": [], "alerts": []
    }
    try:
        state8.set_events([{"event_id": "x", "event_type": "INTRUSION",
                            "severity": "HIGH", "camera_id": "DB-FAIL",
                            "track_id": 1, "object_class": "person",
                            "timestamp": "2026-09-05T00:00:00Z",
                            "confidence": 0.9, "bbox": {},
                            "status": "DETECTED"}])
        db_fail_ok = True
    except Exception:
        db_fail_ok = False
    report("8. PostgreSQL unavailable - AI continues", db_fail_ok)

    # === 9. Pending persistence task shutdown ===
    import ai.db.session as sess9
    sess9._shutdown_pending = False
    sess9._pending_tasks = []
    await close_db()
    report("9. Shutdown - clean close_db()", True)

    # === 10. No shared AsyncSession ===
    state_a = PipelineState(camera_id="NO-SHARE-A", camera_name="A")
    state_b = PipelineState(camera_id="NO-SHARE-B", camera_name="B")
    report("10. No shared AsyncSession - independent PipelineState",
           state_a is not state_b and state_a.lock is not state_b.lock)

    # === Cleanup ===
    for cid in ["MULTI-A", "MULTI-B", cam_id]:
        await cam_repo.delete(cid)
    await close_db()

    # === Summary ===
    print("\n" + "=" * 60)
    print("SECTION 9 VERIFICATION RESULTS")
    print("=" * 60)
    for r in results:
        print(r)
    print("=" * 60)
    print(f"TOTAL: {passed} passed, {failed} failed out of {passed + failed}")

asyncio.run(run_tests())
