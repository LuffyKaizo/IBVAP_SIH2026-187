"""§24 E2E acceptance test: HTTP MJPEG delivery rate + WebSocket metadata rate.

Runs the REAL server (uvicorn subprocess, same entry as production) and
measures over real sockets:

  1. MJPEG frames delivered on GET /video/stream/{id} over a 10 s window
  2. WebSocket messages delivered on /ws/cameras/{id} over a 10 s window
  3. Pipeline analytics FPS during the same window (ground truth)

PASS criteria (relative to measured analytics FPS, since the source clip and
loop-restart gaps bound the absolute rate):
  - MJPEG rate within max(3 fps, 20%) of analytics  (was hard-capped ~20 Hz
    by a fixed 50 ms poll before the event-driven fix)
  - WS rate within max(3 fps, 20%) of analytics     (was capped ~20 Hz)
  - MJPEG > 20.5 fps when analytics > 22 fps        (direct proof the old
    20 Hz ceiling is gone)

Usage (from backend/):  python -u scripts\\bench_stream_e2e.py
Exit code 0 = PASS, 1 = FAIL.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "backend"
sys.path.insert(0, str(_BACKEND))
os.chdir(_BACKEND)

from ai.config import settings  # noqa: E402  (thread discipline must load first)

import httpx  # noqa: E402

CLIP = os.path.join(_REPO_ROOT, "data", "cameras",
                    "pexels-george-morina-5293898 (1080p).mp4")
CAM_ID = "E2E-STREAM-01"
TOKEN = "dev-bypass-token"
HDRS = {"Authorization": "Bearer %s" % TOKEN}
PORT = 8791
BASE = "http://127.0.0.1:%d" % PORT
WS_BASE = "ws://127.0.0.1:%d" % PORT
WINDOW_S = 10.0
CONNECT_DEADLINE_S = 90.0
LOG = Path(os.environ.get("TEMP", ".")) / "ibvap_e2e_server.log"


def _spawn_server():
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    # Isolated DB: the shared dev ibvap.db may contain stale registered
    # cameras (incl. 4K sources) that would auto-start and skew the run.
    # An empty temp DB seeds only CAM-01; we add our own camera on top.
    import tempfile
    e2e_db = Path(tempfile.gettempdir()) / "ibvap_e2e.db"
    try:
        e2e_db.unlink()
    except FileNotFoundError:
        pass
    env["DATABASE_URL"] = "sqlite+aiosqlite:///%s" % e2e_db.as_posix()
    log = open(LOG, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ai.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(_BACKEND), env=env,
        stdout=log, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("uvicorn exited early (%s) — log: %s"
                               % (proc.returncode, LOG))
        try:
            r = httpx.get(BASE + "/openapi.json", timeout=2.0)
            if r.status_code == 200:
                return proc
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("uvicorn did not become ready — log: %s" % LOG)


def _count_mjpeg(seconds):
    """Count multipart JPEG boundaries on a real HTTP socket."""
    n = 0
    tail = b""
    t0 = time.time()
    timeout = httpx.Timeout(30.0, connect=10.0, read=15.0)
    with httpx.stream("GET", BASE + "/video/stream/%s?token=%s" % (CAM_ID, TOKEN),
                      timeout=timeout) as resp:
        if resp.status_code != 200:
            raise RuntimeError("MJPEG HTTP %s" % resp.status_code)
        for chunk in resp.iter_bytes(chunk_size=65536):
            data = tail + chunk
            n += data.count(b"--frame")
            tail = data[-16:]
            if time.time() - t0 >= seconds:
                break
    return n, time.time() - t0


async def _count_ws_async(seconds):
    import websockets
    msgs = 0
    versions = set()
    t0 = time.time()
    async with websockets.connect(
        "%s/ws/cameras/%s?token=%s" % (WS_BASE, CAM_ID, TOKEN),
        open_timeout=10, close_timeout=2,
    ) as ws:
        while time.time() - t0 < seconds:
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            if isinstance(msg, bytes):
                continue
            import json
            data = json.loads(msg)
            msgs += 1
            v = data.get("metadata_version")
            if v is not None:
                versions.add(v)
    return msgs, len(versions), time.time() - t0


def _write_artifact(result: dict, failures: list, verdict: str) -> None:
    """Persist the run's numbers + verdict to reports/bench/e2e_stream_*.json."""
    result["verdict"] = verdict
    result["failures"] = list(failures)
    out_dir = _REPO_ROOT / "reports" / "bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ("e2e_stream_%s.json"
                     % time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("[E2E] artifact -> %s" % out, flush=True)


def main():
    import faulthandler
    faulthandler.dump_traceback_later(300, exit=True)

    failures = []
    proc = None
    result = {
        "benchmark": "e2e_stream",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "window_s": WINDOW_S,
        "camera_id": CAM_ID,
        "source_clip": os.path.relpath(CLIP, _REPO_ROOT),
        "python": sys.version.split()[0],
        "measurements": {},
    }
    print("[E2E] spawning uvicorn on %s ..." % BASE, flush=True)
    try:
        proc = _spawn_server()
        print("[E2E] server up (log=%s)" % LOG, flush=True)

        with httpx.Client(timeout=10.0) as client:
            r = client.post(BASE + "/cameras", headers=HDRS, json={
                "camera_id": CAM_ID,
                "name": "E2E stream",
                "location": "bench",
                "source": CLIP,
            })
            body = r.json() if r.status_code in (200, 201) else {}
            if "success" not in body:
                print("[E2E] FAIL camera create -> %s %s" % (r.status_code, r.text[:300]))
                failures.append("camera create failed (HTTP %s)" % r.status_code)
                _write_artifact(result, failures, "FAIL")
                return 1
            print("[E2E] camera %s registered" % CAM_ID, flush=True)
            try:
                t0 = time.time()
                status = None
                while time.time() - t0 < CONNECT_DEADLINE_S:
                    g = client.get(BASE + "/cameras/%s" % CAM_ID, headers=HDRS)
                    if g.status_code == 200:
                        info = g.json()
                        status = info.get("status")
                        if status and status.get("video_connected"):
                            break
                    time.sleep(0.5)
                if not (status and status.get("video_connected")):
                    failures.append("camera never connected within %.0fs"
                                    % CONNECT_DEADLINE_S)
                    _write_artifact(result, failures, "FAIL")
                    return 1
                print("[E2E] connected after %.1fs" % (time.time() - t0), flush=True)
                time.sleep(6.0)  # warm models / reach steady state

                print("[E2E] measuring MJPEG for %.0fs ..." % WINDOW_S, flush=True)
                n_frames, dt1 = _count_mjpeg(WINDOW_S)
                mjpeg_fps = n_frames / dt1
                print("[E2E] MJPEG: %d frames / %.1fs = %.2f fps"
                      % (n_frames, dt1, mjpeg_fps), flush=True)
                result["measurements"].update(
                    mjpeg_frames=n_frames, mjpeg_window_s=round(dt1, 2),
                    mjpeg_fps=round(mjpeg_fps, 2))

                print("[E2E] measuring WS for %.0fs ..." % WINDOW_S, flush=True)
                n_msgs, n_versions, dt2 = asyncio.run(_count_ws_async(WINDOW_S))
                ws_fps = n_msgs / dt2
                print("[E2E] WS: %d messages / %.1fs = %.2f fps (%d distinct versions)"
                      % (n_msgs, dt2, ws_fps, n_versions), flush=True)
                result["measurements"].update(
                    ws_messages=n_msgs, ws_window_s=round(dt2, 2),
                    ws_fps=round(ws_fps, 2), ws_distinct_versions=n_versions)

                g = client.get(BASE + "/cameras/%s" % CAM_ID, headers=HDRS)
                st = (g.json() or {}).get("status") or {}
                analytics = float(st.get("processing_fps") or 0.0)
                print("[E2E] analytics=%.2f fps | stages=%s"
                      % (analytics, st.get("stage_ms")), flush=True)
                print("[E2E] jpeg_version=%s metadata_version=%s"
                      % (st.get("jpeg_version"), st.get("metadata_version")), flush=True)
                result["measurements"].update(
                    analytics_fps=analytics, stage_ms=st.get("stage_ms"),
                    jpeg_version=st.get("jpeg_version"),
                    metadata_version=st.get("metadata_version"))

                def close(a, b):
                    return abs(a - b) <= max(3.0, 0.2 * max(a, b))

                if analytics <= 0:
                    failures.append("no analytics fps measured")
                if not close(mjpeg_fps, analytics):
                    failures.append("MJPEG %.2f vs analytics %.2f outside tolerance"
                                    % (mjpeg_fps, analytics))
                if not close(ws_fps, analytics):
                    failures.append("WS %.2f vs analytics %.2f outside tolerance"
                                    % (ws_fps, analytics))
                if analytics > 22 and mjpeg_fps <= 20.5:
                    failures.append("MJPEG %.2f still <= 20.5 fps (old 20 Hz cap?)"
                                    % mjpeg_fps)
                if n_versions < max(3, int(analytics * WINDOW_S * 0.6)):
                    failures.append("WS distinct versions %d too low" % n_versions)
            finally:
                resp = client.delete(BASE + "/cameras/%s" % CAM_ID, headers=HDRS)
                print("[E2E] camera unregistered -> %s" % resp.status_code, flush=True)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        print("[E2E] server stopped", flush=True)

    if failures:
        for f in failures:
            print("[E2E] FAIL: %s" % f, flush=True)
        _write_artifact(result, failures, "FAIL")
        return 1
    print("[E2E] PASS: MJPEG + WS delivery tracks real pipeline FPS", flush=True)
    _write_artifact(result, failures, "PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
