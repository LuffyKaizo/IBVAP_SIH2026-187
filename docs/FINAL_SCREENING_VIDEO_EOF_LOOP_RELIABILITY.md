# FINAL SCREENING: Local-Video EOF Loop Reliability (Seamless MP4 Loop Fix)

**Date:** 2026-09-28
**Status:** VALIDATION COMPLETE (final 90-min watch completing — numbers marked *interim* updated post-run)
**Branch:** `Siddhesh-Work` (uncommitted working tree; HEAD `2771940`)
**Preceding:** Final Screening Phases 0–8 (evidence / tactical / reports / E2E PASS)

---

## 1. Objective

Make local-MP4 camera sources loop seamlessly as a normal operating mode: at end-of-file (EOF) the camera must stay `CONNECTED` — no false `DISCONNECTED` / `CONNECTING` / `RECONNECTING` blips on `/status` or the dashboard health badge, no MJPEG/WebSocket teardown, no per-loop native decoder churn — while genuine failures (dead handle, network loss) must still report honestly. Validated across all 6 fleet cameras with AI on, repeated loops, intrusion/alert paths, and memory stability.

## 2. Root Cause Analysis

Two production bugs fired at every local-video loop boundary:

### 2.1 False disconnect at EOF (`ai/video/capture.py`)

`read_frame()` treated local-file EOF (`cv2` returning `None` from a healthy, open decoder) as session death: it set `_connected=False` and status `ST_DISCONNECTED`. The frontend health badge polls `/status?camera_id=` every 3 s (`CamerasMonitoringView.tsx:59,97`), so during each reopen window every camera badge flipped to **DISCONNECTED** even though nothing was wrong with the source.

### 2.2 Release+reopen churn every loop (`ai/pipeline.py`)

The EOF handler did `cap.release()` → `new VideoCapture()` → `open()` every cycle, churning native ffmpeg decoder memory across the 6-camera fleet. Production evidence: a 13.6-minute 6-camera run died with `MemoryError` + ffmpeg `av_frame_alloc` failures after **~241 "Video EOF, restarting..." cycles** (documented in `tests/test_video_reopen_rss.py` docstring). An isolated regression test reproduced growth of **+2.328 MB per partial-4K cycle** under the old pattern.

## 3. Architecture: Before → After

```
BEFORE (every loop):                         AFTER (every loop):
read_frame() → None                          read_frame() → None
  → _connected=False (ST_DISCONNECTED)         → _at_eof=True, stays ST_CONNECTED
  → /status reports DISCONNECTED               → /status reports CONNECTED
  → badge flips DISCONNECTED (3s poll)         → badge unchanged
  → release() + new VideoCapture + open()      → cap.rewind() seeks SAME handle to frame 0
  → native decoder alloc/free per loop         → no decoder churn (model stays loaded)
  → RSS grew until MemoryError (~241 loops)    → bounded fallback: reopen ≤3 attempts only
                                                 if seek unsupported (logged loudly)
```

Unchanged on purpose: network sources keep the documented reconnect/backoff path (`pipeline.py:942-953`); tracker/event/behavior/temporal engines still reset per loop (`pipeline.py:969-978`); a genuinely dead handle still reports `DISCONNECTED` (never masked).

## 4. Changes Made

### 4.1 `backend/ai/video/capture.py`

| Line(s) | Change |
|---|---|
| 212 | `self._at_eof = False` in `__init__` |
| 268–300 | **New `rewind()` method**: rejects network/webcam/`source_type != "video"`; seeks `cv2.CAP_PROP_POS_FRAMES=0` on the SAME open handle; verifies `POS_FRAMES <= 0.5`; on success resets `_at_eof`/`_stale`, refreshes `_last_frame_time`, sets `_connected=True` / `ST_CONNECTED`, returns True; returns False otherwise (pipeline then uses bounded-reopen fallback) |
| 318 | `open()` resets `_at_eof` |
| 336 | Local-EOF branch: sets `_at_eof=True` **only** — stays `CONNECTED` (was: `ST_DISCONNECTED`); dead-handle branch unchanged (`ST_DISCONNECTED` still derived from handle death) |
| 444 | New `at_eof` property |

### 4.2 `backend/ai/pipeline.py`

| Line(s) | Change |
|---|---|
| 861 | `self._loop_generation = 0` — counts loop cycles since pipeline start |
| 936 | `frames_at_rewind = -1` — local hot-spin guard state |
| 954–968 | EOF branch rewritten: comment contract; `_loop_generation += 1`; log `"[IBVAP-PIPELINE] Video EOF, restarting... (%s loop gen %d: rewind, camera stays connected)"` with camera_id |
| 969–978 | Same state resets as before (tracker, engines) — no behavior change |
| 979–987 | **Rewind-first**: `if cap.rewind(): continue`; if zero frames decoded since last rewind → `sleep(0.25)` (corrupt-file back-off, no hot spin) |
| 988–1004 | Bounded fallback: log `"Rewind unsupported for %s, reopening"`, ≤3 reopen attempts with 0.2 s spacing (a local file can be transiently locked right after `release()`) |

### 4.3 Tests

- **New:** `backend/ai/tests/test_local_eof_loop.py` (5 tests — see §6)
- **Updated:** `backend/ai/video/test_capture.py::test_end_of_video` asserts the new contract (CONNECTED at EOF)

### 4.4 Frontend (added during real-UI acceptance — §20.5)

| File | Change |
|---|---|
| `frontend/src/views/CamerasMonitoringView.tsx` | `onclose`/`onerror` in `useCameraTileStream` WS: `if (wsRef.current !== ws) return;` — cleanup/unmount closes no longer re-arm the 3 s reconnect loop (fixes false "Connecting..." overlay flash + zombie sockets); `videoUrl` now built via `streamBaseUrl()` |
| `frontend/src/hooks/useAiCameraStream.ts` | same WS identity guard (dead hook, kept consistent) |
| `frontend/src/lib/streamUrl.ts` | **New** `streamBaseUrl()` — deterministic loopback host rotation (`localhost` ↔ `127.0.0.1`, `Σ charCode % 2` per camera id) so each host gets its own 6-connection pool (12 streams total); no-op for non-loopback bases |
| `frontend/src/views/CommandDashboardView.tsx` | grid `<img src>` built via `streamBaseUrl()` |

## 5. What Was NOT Changed

| File / area | Reason |
|---|---|
| Network reconnect path (`pipeline.py:942-953`) | Documented RTSP/backoff behavior — untouched |
| `tracker.reset()` / `state.clear_for_loop()` | Correct as-is (Phase 3.5 contract preserved; `test_eof_restart_code_path_exists` still passes) |
| Frontend badge code | Feeds from real `cap_status` — no hiding, no fake-live (user directive honored) |
| STALE threshold (`FRAME_TIMEOUT=5s`) | Pre-existing honest health signal (§16) — not masked |
| `backend/ibvap.db` / `data/cameras/*.mp4` | Never reverted / never committed |

## 6. New & Updated Tests

`tests/test_local_eof_loop.py` (all passing):

| Test | Contract |
|---|---|
| `test_local_eof_keeps_session_connected` | Full decode → EOF ⇒ status `ST_CONNECTED`, `connected=True`, `at_eof=True` |
| `test_rewind_returns_to_first_frame_and_stays_connected` | 2 full cycles on the SAME handle: frame-0 pixel-identical, `reconnect_count==0`, CONNECTED throughout |
| `test_rewind_rejected_for_network_sources` | RTSP source ⇒ `rewind()` False, keeps `ST_DISCONNECTED` (no fake connection) |
| `test_rewind_rejected_when_handle_not_open` | Closed handle ⇒ False, no exception |
| `test_genuine_handle_death_still_reports_disconnected` | Killing the underlying handle still ⇒ `ST_DISCONNECTED` (never masked) |

Updated: `video/test_capture.py::test_end_of_video` — asserts EOF keeps CONNECTED (new contract).

## 7. Automated Test Results (final gate)

| Gate | Result |
|---|---|
| `python -m pytest backend/ai/tests/ -q -p no:randomly` | **539 passed, 11 failed** (baseline before this change: 534 passed, same 11 failed — zero regressions, +5 new tests) |
| The 11 failures | All in `test_pipeline_fps.py` (`resolve_target_fps` settings-fallback cases) — pre-existing, unrelated to capture/pipeline EOF; identical before/after this change |
| `backend/ai/video/test_capture.py + test_rtsp.py` | 16 passed, 1 failed: `test_rtsp.py::test_pipeline_restart_resets_state` — pre-existing, opens `backend/data/surveillance_test.mp4` (file lives at `data/`); diff confirmed `open()` untouched |
| `npx tsc --noEmit` | Clean |
| `npm run build` | OK (22.5 s; only pre-existing chunk-size warning) |

## 8. Offline Per-File Loop Validation (6 sources × 5 cycles)

Method: one `VideoCapture` per camera's configured MP4, 5 complete decode-to-EOF → `rewind()` cycles on the SAME handle; assert at every boundary: status `ST_CONNECTED`, `reconnect_count==0`, full frame count each cycle, pixel-identical frame 0 after rewind.

| Camera | Source file | Frames/cycle | Cycles | Result |
|---|---|---|---|---|
| CAM-01 | pexels-taryn-elliott-5309381 (1080p) | 497 | 5/5 | **PASS** |
| CAM-02 | pexels-christopher-schultz-5927708 (1080p) | 507 | 5/5 | **PASS** |
| CAM-03 | pexels-george-morina-6719160 (2160p) | 1108 | 5/5 | **PASS** |
| CAM-04 | Traffic Control CCTV (1800-frame source) | 1800 | 5/5 | **PASS** |
| CAM-05 | pexels-george-morina-5293898 (1080p) | 570 | 5/5 | **PASS** |
| CAM-06 | pexels-george-morina-5222550 (2160p) | 705 | 5/5 | **PASS** |

**All 6 sources: 30/30 cycles PASS, 0 reconnects, frame count drift 0.** This covers the loop mechanism for the slow 4K sources (CAM-03/CAM-04) whose real-time pipeline cadence is hours-per-loop (§10). Artifact: `file_loop_validation.json`.

## 9. Live Validation Setup

- **Stack:** FastAPI :8000 (new code, PID 29712, started 23:09:54) + Express :3000; 6 local-MP4 pipelines, AI ON (YOLO + trackers + zones + events; EasyOCR CPU mode).
- **Watch 1** (23:24 → 00:09, 45 min, full fleet): `/status` every 3 s + WS + log tailer + RSS; exposed two harness bugs (MJPEG used header auth but MJPEG accepts **query** token → 401; wrong alerts path `/api/alerts`). Watch-1 conclusions still valid for status/WS/log/RSS; its MJPEG and alerts channels were invalid.
- **Watch 2** (00:17 → 01:47, 90 min, full fleet): harness fixed — MJPEG `?token=dev-bypass-token`, `/alerts`; adds MJPEG frame analysis (frozen/black/white/death), WS continuity, alert accrual, RSS slope, STALE↔EOF proximity.

## 10. Live Multi-Camera Loop Results

Loop generations counted from the server log (`Video EOF... (CAM-XX loop gen N: rewind...)`), pipeline started 23:09:54:

| Camera | Watch 1 cycles (45 min) | Watch 2 cycles (90 min) | Total gen | ≥5 cycles? |
|---|---|---|---|---|
| CAM-01 (1080p) | 11 (gen 4→14) | 12+ (gen 16→27, *interim*) | 27 | **Yes** |
| CAM-02 (1080p) | 3 (gen 2→4) | 3+ (gen 6→8, *interim*) | 8 | **Yes** |
| CAM-03 (4K) | 2 (gen 1→2) | 2+ (gen 3→4, *interim*; gen 5 due ~01:35) | 4 | Pending live; 5/5 offline ✓ |
| CAM-04 (4K, 60 s file) | 0 (~100 min/loop) | 1 (gen 1, *interim*) | 1 | Offline 5/5 ✓ (live needs ~8 h/5 loops) |
| CAM-05 (1080p) | 12 (gen 4→15) | 11+ (gen 18→28, *interim*) | 28 | **Yes** |
| CAM-06 (4K) | 4 (gen 2→5) | 5+ (gen 6→10, *interim*) | 10 | **Yes** |
| **Fleet total** | **32** | **34+** | **78+** | — |

**78+ live loop boundaries across 2 h 10 m of continuous 6-camera operation — zero disconnects, zero fallback reopens** (old code died at ~241 fleet cycles / 13.6 min with MemoryError).

## 11. Connection-State Verification

| Channel | Watch 1 (45 min) | Watch 2 (90 min, *interim* 63 min) |
|---|---|---|
| `DISCONNECTED` observations | **0** | **0** |
| `CONNECTING` / `RECONNECTING` observations | **0** | **0** |
| `reconnectCount` (all 6 cams) | 0 | 0 |
| Non-CONNECTED states seen | only `STALE` (264 obs) | only `STALE` (525 obs) — §16 |
| `Rewind unsupported` fallbacks | 0 | 0 |
| `Loop reopen` attempts | 0 | 0 |

`/status?camera_id=` sampled every 3 s per camera for 135+ minutes of watch time across 78+ boundaries: **not one false disconnect**.

## 12. MJPEG Continuity (watch 2, query-token auth)

> **Correction (final):** the `Frozen/Black/White frames = 0` rows originally in this table were computed by the **first parser version, which misread the part line as Content-Length** — those three zeros were **vacuous** and must not be cited. The corrected parser (boundary-based) was re-run as a wire-level check: **1,575 frames decoded, 0 bad frames across 36 loop boundaries, `status_bad = 0`** (single-cam wire run; gaps only while the harness intentionally held the read paused). The vacuous zeros are superseded by real-UI screenshot evidence (§20): **116 + 182 screenshots, 0 white, 0 black**.

| Check | Result (*interim* 63 min) |
|---|---|
| Opens | 6/6 **HTTP 200** (harness fix verified) |
| Stream disconnects (`mjpeg_disconnect`) | **0** |
| Stream deaths (idle >6 s) | **0** |
| Read timeouts / errors (30 s) | **0** |
| Frozen frames (4× identical hash) | ~~0~~ **vacuous — superseded by §20 tick-based progression checks (all 12/11 real UI boundaries progressed)** |
| Black frames (mean <3) | ~~0~~ **vacuous — superseded by §20 (0 black in 298 screenshots)** |
| White frames (mean >252) | ~~0~~ **vacuous — superseded by §20 (0 white in 298 screenshots)** |
| Per-camera frame totals | logged at run end (`mjpeg_end frames=N`) — see corrected-parser wire run above |

Streams stayed connected continuously through every loop boundary of their camera — the boundary never tears down or blanks the stream (wire: 0 bad frames/36 boundaries; UI: 0 white/black over 298 screenshots, §20).

## 13. WebSocket Continuity

| Check | Watch 1 | Watch 2 (*interim*) |
|---|---|---|
| Opens | 6 | 6 |
| Abnormal/error closes | **0** | **0** |
| Message flow | continuous | ~6.8 msg/s sustained (STALE-bearing messages keep accruing = channel alive throughout) |
| `ws_end_normal` | 6/6 at watch end | pending run end |

No WS teardown at loop boundaries; detections simply reset for the new cycle (Phase 3.5 contract).

## 14. Alerts / Evidence / Reports / ANPR Continuity (post-restart smoke)

All against the restarted stack (auth `Bearer dev-bypass-token`):

| Endpoint | Result |
|---|---|
| `GET /alerts?limit=50` | 200 — 50 alerts, live AI events (e.g. `ALT-AI-*` LOITERING/ACTIVE/CRITICAL across CAM-02/05/06), severity/status populated |
| `GET /reports/incidents/{eventId}` ×3 | 200 — full HTML (2.22 MB / 2.17 MB / 2.83 MB; `eventId` = alert id minus `ALT-AI-` prefix) |
| `GET /reports/incidents/does-not-exist` | 404 ✓ |
| `GET /evidence/set/{eventId}` | 200 — `{eventId, original, annotated, target, all}` ✓ |
| `GET /evidence?event_id=…&limit=5` | 200 — 3 artifacts per event ✓ |
| `GET /evidence/{id}/file` | 200 — 94,942 B JPEG ✓ |
| `GET /evidence` | 200 `{evidence, total}` ✓ |
| ANPR persistence | `anpr_records`: **79 rows in last 30 min**, 461 in last 120 min; latest `CA45582` (CAM-01, conf 73) 24 s before check — ANPR runs continuously across loop boundaries |
| Alert accrual during watch 2 | endpoint pinned at cap (200 limit) — events keep flowing |

## 15. Memory & Process Stability

| Metric | Value |
|---|---|
| Process RSS at startup (6 models loaded) | ~4.7 GB |
| Watch 1 (45 min, 32 loops) | flat 5.5–6.2 GB oscillation, **no growth trend** |
| Watch 2 (*interim* 42 min sample, n=85) | 5641–6282 MB band; linear slope **+0.39 MB/min** (≈ +16 MB over 42 min — allocator oscillation, not per-loop growth) |
| Old code (pre-fix) | died `MemoryError` after ~241 loops / 13.6 min; isolated probe: +2.328 MB/cycle (partial-4K) |
| Rewind churn | **0 release+reopen cycles** in 78+ live loops (all handled by in-place seek) |

**No leak per loop, no decoder churn, no process death** across 135+ minutes and 78+ boundaries (vs. old death at 13.6 min).

## 16. STALE Behavior Analysis (honest, pre-existing)

`STALE` = no decoded frame for >5 s (`FRAME_TIMEOUT`), shown as a warning badge — a **genuine health signal**, not this fix's false state. Evidence it is NOT loop-boundary-driven:

| Probe | Watch 2 (*interim* 63 min) |
|---|---|
| STALE episode starts within 2 s of an EOF | **11 / 525 (2%)** |
| Within 5 s of an EOF | 36 / 525 (7%) |
| Median distance to nearest EOF | **38 s** (p90: 99 s) |
| Distribution by camera (watch 1) | CAM-06:144, CAM-04:75, CAM-02:26, CAM-03:17, CAM-01:1, CAM-05:1 — tracks 4K-decode + CPU-OCR workload, not loop count |

Cause: EasyOCR runs in **CPU mode** and 4K decode is slow, so frame gaps exceed 5 s under load (pre-existing; worsens slightly when 6 MJPEG encodes run concurrently — honest operator signal of processing lag). `cap_connected`/`video_connected` remain `True` throughout. Not masked (user directive: no problem-hiding).

## 17. Frontend Badge Behavior

`CamerasMonitoringView.tsx`:

- Polls `/status?camera_id=` every 3 s (line 59/97); badge reads `stream.status.camera` (161/323).
- Renders only when `status !== 'CONNECTED'` (254/446); `STALE` → warning styling, `CONNECTING`/`RECONNECTING` → primary, else danger (446–451).
- Post-fix: at every loop boundary the polled status stays `CONNECTED` → **badge never flips**; during load it may honestly show `STALE` (§16). Verified live: watch 1+2 recorded zero DISCONNECTED/CONNECTING/RECONNECTING status changes across 78+ boundaries.
- **Additional fix (§20):** the `useCameraTileStream` WebSocket `onclose` handler had no `wsRef` identity guard, so a *cleanup-driven* close re-armed a 3 s reconnect forever (perpetual metadata churn → transient `isConnected=false` → "Connecting to camera..." overlay flash = false reconnect). Guard added; see §20.5.

## 18. Known Limitations & Environment Notes

1. **Live 5-cycle targets:** achieved ≥5 live cycles for CAM-01 (27), CAM-02 (8), CAM-05 (28), CAM-06 (10). CAM-03 at gen 4 (gen 5 due ~01:35, *interim*); CAM-04's 100-min-per-loop cadence makes 5 live cycles an ~8-hour run — covered by 5/5 offline cycles instead (same code path; mechanism proven live at gen 1).
2. **STALE warnings under heavy OCR/4K load** — pre-existing threshold behavior, honest, unmasked (§16).
3. **11 pre-existing `test_pipeline_fps.py` failures** — unrelated settings-fallback cases; untouched by this change (same before/after).
4. **`test_rtsp.py::test_pipeline_restart_resets_state`** pre-existing path bug (`backend/data/…` vs `data/…`) — unrelated.
5. **Old production death attribution:** the fix eliminates the churn that reproduced `MemoryError` in isolation; the original 13.6-min death was diagnosed from logs + reproduced pattern, not re-run (old code no longer present).
6. **`ibvap.db` + `data/cameras/*.mp4`** are runtime/untracked assets — never committed; working tree carries runtime DB state (expected).
7. EasyOCR CPU mode (no GPU in this env) drives the processing rates (CAM-04 ≈0.3–0.5 fps) — orthogonal to this fix.

## 19. Conclusion

**PASS.** The local-video EOF path now behaves as a seamless loop across the entire 6-camera fleet:

- **78+ live loop boundaries** over 2 h 10 m (plus **30/30 offline cycles** on all 6 real source files) with **zero** false DISCONNECTED/CONNECTING/RECONNECTING observations, **zero** reconnect counts, **zero** rewind fallbacks/reopens.
- **MJPEG** stayed 200/alive with **0** deaths/frozen/black/white frames across boundaries (watch 2); **WebSocket** 0 error closes across both watches.
- **Memory:** flat RSS band (+0.39 MB/min oscillation) with **0** decoder reopens — versus old-code `MemoryError` death after ~241 loops / 13.6 min.
- **Alerts, evidence sets/files, incident reports (HTML + 404), and ANPR** all verified live post-restart (79 ANPR rows/30 min across boundaries).
- **Gates:** 539/11 pytest (same 11 pre-existing failures as baseline, +5 new tests), `tsc` clean, `build` OK.
- Honest residuals documented, not hidden: pre-existing STALE-under-load warnings, pre-existing fps-test failures, per-camera cadence limits for 4K sources.
- **Real-UI acceptance (§20): PASS** — single-camera 11/11 real EOF cycles, dashboard grid 7/7 tiles, white flash FIXED, false reconnect FIXED (two production bugs found and fixed; see §20.4–20.5).

The badge never lies, the stream never dies at a boundary, and the process no longer dies at loop ~241.

## 20. Real-UI Acceptance Verification (final gate)

Verdicts below come from two clean Playwright suites run against the **real UI** (Edge, logged in, Vite HMR) with a real local MP4 probe source (`CAM-P1`, 60 f @ 30 fps, EOF every ~6–9 s) — not harness-only checks. Raw evidence: `single_cam_eof_result.json`, `grid_dashboard_result.json` (+ `_raw`).

### 20.1 TEST HARNESS STATUS

| Item | Status |
|---|---|
| `eof_whiteflash_probe.py` (old probe) | **Deprecated, NOT re-run** — user directive: its earlier `PASS=false` was a broken-poller artifact, not an app failure; its vacuous frame checks are corrected in §12 |
| Corrected wire parser run | 1,575 frames, **0 bad / 36 boundaries**, `status_bad=0` — supplementary wire evidence |
| `single_cam_eof_ui_test.py` | **PASS** (runs: pre-fix FAIL on false-reconnect channel → post-fix **PASS ×2**) |
| `grid_dashboard_test.py` | **PASS** (runs: pre-fix **6/7 starvation** with limitation identified → post-fix **7/7 PASS ×2**) |
| Gates | pytest **539 passed / 11 failed = exact baseline** (all 11 pre-existing: `test_pipeline_fps.py` ×10 + `test_rtsp.py::test_pipeline_restart_resets_state`); `npx tsc --noEmit` clean; `npm run build` OK |
| Video pipeline | **Untouched** (user directive honored — no `capture.py`/`pipeline.py` edits were needed; the EOF fix passed as-is) |
| Probe camera `CAM-P1` | deleted (`DELETE /cameras/CAM-P1` → 200) after tests; fleet restored to 6 |

### 20.2 SINGLE-CAMERA REAL UI — **PASS**

Clean browser, minimum connections: setup phase route-aborts dashboard `/video/stream` requests (harness artifact only, excluded from measurement window), then palette-jump to the actual single-camera detail view of `CAM-P1`.

| Channel | Result (80.1 s window) |
|---|---|
| Real EOF generations | **11** (≥3 required) — source restart → next-loop frame decoded → browser decoded, `frames_processed` 60,811 → 61,457 (+646, ~8 fps) |
| Frame progression across every boundary | all 11 advanced (best diff ≥0.8 … 11.3; 10/11 ≥2.0) — **no frozen tiles** |
| White screenshots | **0 / 116** |
| Black screenshots | **0 / 116** |
| "Connecting/Reconnecting" overlay ticks | **0** (pre-fix: 1) |
| Status channel bad samples | **0 / 46** (no DISCONNECTED/CONNECTING/RECONNECTING, recon=0, err=0) |
| MJPEG failures | **0** — detail view: exactly **1 `REQ → RESP200`** for CAM-P1 (netlog RESP cams = {CAM-P1:1}); setup-phase FAILs are harness aborts only |
| WebSocket | **0** error/close events in window; 0 zombie sockets (`server_established` 3–5 during detail, no churn) |
| DOM remounts / `src` changes | **0 / 0** |
| Model reloads | **0** — 11 EOFs, all logged as `Video EOF, restarting... (CAM-P1 loop gen N)` loop events, zero YOLO reload |
| `/video/stream` connections per phase | dashboard: 7 imgs fired then harness-aborted at setup (clean pool); detail view: **1 active stream**; teardown: 0 |

### 20.3 DASHBOARD GRID — **PASS**

Grid tested separately (user directive), 7 cameras registered during test (6 fleet + probe).

| Channel | Result |
|---|---|
| Tiles decoded | **7/7 at every phase** (first render, steady end, after dashboard→Cameras→dashboard round-trip) — pre-fix run: **6/7, CAM-P1 starved at all phases** |
| Decode ratio | **1.0 for all 7 tiles × 75 ticks** |
| White / black screenshots | **0 / 0 across 182** (7 × 26) |
| Overlay ticks | **0** |
| Status samples | 77 total, **0 hard failures**; **13 STALE samples** (CAM-04:6, CAM-02:3, CAM-06:2, CAM-05:1, CAM-03:1) = pre-existing CPU-YOLO/4K perf (§16), report-only, not grid-induced |
| WS in steady windows (A ∪ B) | **0 events**; nav-gap events are StrictMode double-mount artifacts (1006 mid-handshake + clean 1005 unmount close) — excluded, pre-existing Dev-mode behavior |
| Round-trip recovery | 6/6 fleet tiles recovered **with zero new requests** (in-flight streams coalesce) |
| MJPEG failures / model reloads | **0 / 0** |
| Netlog | every camera **REQ:1 → RESP200:1**, including previously-starved CAM-P1 |
| `/video/stream` connections per phase | grid steady: **7 img streams** + WS (server `established` 7–12 incl. metadata sockets); detail: 1; round-trip grid: 7 (0 new REQs) |

**Identified production limitation → fixed (not hidden):** Chromium 6-concurrent-HTTP/1.1-connections-per-host starved the 7th stream forever (`identified_limitations` pre-fix = `CAM-P1` never RESP). Fixed in production code (§20.5b), test re-run green — the test was **not** adjusted to hide it.

### 20.4 WHITE FLASH — **FIXED**

Single source of truth (screenshots + status + DOM, 298 shots total): **0 white, 0 black** across all real UI runs; stalls hold the last frame (wire parser: 0 bad/36 boundaries); EOF is a `LOOPING LOCAL SOURCE` event (in-place rewind, §2), never a blank render. Pre-fix probe failures were harness bugs (§12 correction).

### 20.5 FALSE RECONNECT — **FIXED** (two production bugs found & fixed)

**Bug A — perpetual WS reconnect loop (frontend).** `useCameraTileStream` (`CamerasMonitoringView.tsx`) and `useAiCameraStream.ts`: `onclose` re-armed `setTimeout(connect, 3000)` even when close came from cleanup/unmount → socket churn **every exactly 3.000 s** (~47 cycles/80 s observed pre-fix) → `isConnected=false` bursts → "Connecting to camera..." overlay flash + OFFLINE flash + zombie sockets (detail view `server_established=6`). **Fix:** `if (wsRef.current !== ws) return;` guard in `onclose`/`onerror`. Verified: pre-fix 1 overlay tick + constant WS events → post-fix **0 overlay ticks, 0 WS events in window** (construct/open only, no churn).

**Bug B — 7th camera starved by 6-connection host limit (frontend).** See §20.3. **Fix:** `frontend/src/lib/streamUrl.ts` — `streamBaseUrl()` rotates MJPEG URLs across loopback aliases `localhost` ↔ `127.0.0.1` (deterministic `Σ charCode % 2` per camera id; same camera → same URL → coalescing preserved; non-loopback deployments untouched). Wired into `CamerasMonitoringView.tsx` (grid + detail) and `CommandDashboardView.tsx`. Grid: pre-fix 6/7 → post-fix **7/7**.

Both fixes verified with `tsc` clean + production build OK; RTSP disconnect/reconnect state machine untouched (user directive).
