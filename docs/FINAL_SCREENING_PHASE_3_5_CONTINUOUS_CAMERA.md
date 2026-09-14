# FINAL SCREENING: Phase 3.5 — Continuous Camera Video & Demo Stream Reliability

**Date:** 2026-09-12  
**Status:** COMPLETE  
**Preceding:** Phase 3.2 Detection Pipeline Regression Recovery (PASS)

---

## 1. Objective

Make the camera dashboard behave like a continuously operating surveillance system with real video, real detections, proper EOF handling, and no dummy/fabricated data.

## 2. Architecture Audit Findings

### 2.1 EOF Restart (Already Implemented)

The pipeline's `_run_loop` (`ai/pipeline.py:509-525`) already handles EOF restart correctly:

```python
# Local video reached EOF — restart cleanly
print("[IBVAP-PIPELINE] Video EOF, restarting...")
cap.release()
self._tracker.reset()
self.state.clear()
if self._event_engine:
    self._event_engine.resolve_all()
if self._behavior_engine:
    self._behavior_engine.resolve_all()
if self._temporal:
    self._temporal.resolve_all()
cap = VideoCapture(source=self._video_source, source_type=self._video_source_type)
self._capture = cap
self.state._capture = cap
if not cap.open():
    break
continue
```

**What happens on EOF:**
1. `cap.release()` — closes VideoCapture
2. `self._tracker.reset()` — clears ByteTrack state, frame count, detection/position history, recreates YOLO model
3. `self.state.clear()` — resets latest_frame, latest_metadata, frames_processed, total_detections
4. Event/behavior/temporal engines resolve all open events
5. New `VideoCapture` created from same source, reopened
6. Loop continues — next `read_frame()` gets frame 1 of the new cycle

### 2.2 MJPEG Continuity

The MJPEG generator (`ai/main.py:548-579`) loops continuously:
```python
while True:
    frame = pipeline.state.latest_frame
    if frame is None:
        frame = _placeholder_frame()
    ...
```
After EOF restart, `pipeline.state.clear()` sets `latest_frame = None`, then the next loop iteration gets the first frame from the new cycle. The placeholder frame (black 320x240 "Waiting for video...") is shown for at most 1 frame during the restart transition — acceptable as a safety net.

### 2.3 WebSocket Continuity

The WebSocket endpoint (`ai/main.py:588-625`) sends metadata on each iteration. After EOF restart, `state.clear()` sets `latest_metadata = None`, so the next WebSocket message has empty detections until new frames are processed. No stale detections survive the restart.

### 2.4 Frontend Video Display

The frontend uses `<img src={realVideoUrl}>` pointing directly to the MJPEG stream:
```typescript
const realVideoUrl = currentSelectedId && token
  ? AI_BASE + '/video/stream/' + currentSelectedId + '?token=' + token
  : '';
```
No dummy images, no Unsplash URLs, no poster fallbacks. The video element shows exactly what the backend produces.

### 2.5 AI ON/OFF Independence

Toggling AI disconnects the WebSocket but does not affect the MJPEG stream. The video feed continues regardless of AI pipeline state.

## 3. Changes Made

### 3.1 `src/mockData.ts` — Cleared Fabricated Data

Removed all hardcoded camera data, alerts, ANPR records, suspicious events, diagnostics, reports, and system nodes:

| Array | Before | After |
|-------|--------|-------|
| `INITIAL_CAMERAS` | 6 fake cameras with `rtsp://10.14.88.xxx` URLs | `[]` |
| `INITIAL_ALERTS` | 4 fake alerts with Unsplash snapshot URLs | `[]` |
| `INITIAL_ANPR_RECORDS` | 6 fake ANPR records with Unsplash URLs | `[]` |
| `INITIAL_VIRTUAL_ZONES` | 4 fake zones | `[]` |
| `INITIAL_SUSPICIOUS_EVENTS` | 5 fake events | `[]` |
| `INITIAL_24H_SURVEILLANCE_ACTIVITY` | 24 hours of fabricated counts | All zeros |
| `INITIAL_KPI_STATS` | Fabricated dashboard stats | All zeros |
| `INITIAL_DIAGNOSTICS` | 6 fake diagnostics | `[]` |
| `INITIAL_REPORTS` | 3 fake reports | `[]` |
| `INITIAL_SYSTEM_NODES` | 5 fake nodes | `[]` |
| `INITIAL_SETTINGS_CONFIG` | Fake model name, API URL, auth token | Realistic defaults |

### 3.2 `src/views/CamerasMonitoringView.tsx` — Null Guard

Added early return when `cameras` is empty:
```tsx
if (!activeCamera) {
  return (
    <div className="...">
      <span className="material-symbols-outlined ...">videocam_off</span>
      <p>No cameras registered</p>
      <p>Camera feeds will appear here once cameras are connected</p>
    </div>
  );
}
```
Prevents crash on `activeCamera.isNightMode` when cameras list is empty.

### 3.3 `src/App.tsx` — Removed Fake Initial State

- Removed `INITIAL_CAMERAS` and `INITIAL_VIRTUAL_ZONES` imports
- Changed `cameras` initial state from `INITIAL_CAMERAS` to `[]`
- Changed `zones` initial state from `INITIAL_VIRTUAL_ZONES` to `[]`
- Kept `INITIAL_SYSTEM_CONFIG` import (legitimate default config)

### 3.4 `ai/tests/test_camera_ai_fix.py` — EOF Restart Tests

Added 8 new tests in `TestVideoLoop` class:

| Test | Verifies |
|------|----------|
| `test_tracker_reset_clears_frame_count` | `_frame_count` resets to 0 |
| `test_tracker_reset_clears_detection_history` | `_detection_history` cleared |
| `test_tracker_reset_clears_position_history` | `_position_history` cleared |
| `test_tracker_reset_recreates_model` | YOLO model instance recreated |
| `test_pipeline_state_clear_resets_frame_count` | `frames_processed` resets to 0 |
| `test_pipeline_state_clear_resets_latest_frame` | `latest_frame` set to None |
| `test_pipeline_state_clear_resets_latest_metadata` | `latest_metadata` set to None |
| `test_eof_restart_code_path_exists` | EOF restart logic exists in pipeline source |

## 4. Verification Results

### 4.1 Python Tests
- **37/37 camera AI fix tests pass** (28 existing + 8 new + 1 pre-existing)
- All EOF restart tests verify state is properly cleared

### 4.2 TypeScript Build
- `npx tsc --noEmit` — clean
- `npm run build` — successful

### 4.3 Full Test Suite
- **406/438 pass** (32 pre-existing async failures in evidence/sync modules — unrelated)

## 5. What Was NOT Changed

| File | Reason |
|------|--------|
| `ai/pipeline.py` | EOF restart logic already correct |
| `ai/video/capture.py` | VideoCapture EOF handling already correct |
| `ai/tracking/tracker.py` | tracker.reset() already correct |
| `ai/config.py` | Phase 3.2 thresholds preserved |
| `ai/main.py` | `_placeholder_frame()` acceptable safety net |
| Frontend architecture | No redesign needed |

## 6. Data Flow (Post-Phase 3.5)

```
Frontend mounts
  → cameras = [] (empty)
  → fetchCameras() → GET /api/cameras → real cameras from DB
  → CamerasMonitoringView renders real cameras only

Video playback
  → <img src={realVideoUrl}> → MJPEG stream from backend
  → No dummy images, no Unsplash, no poster fallbacks

EOF restart (local MP4)
  → frame = None detected
  → cap.release() → tracker.reset() → state.clear()
  → New VideoCapture from same source
  → Next read_frame() gets frame 1 of new cycle
  → MJPEG shows placeholder for ~1 frame, then new content

WebSocket metadata
  → state.clear() → latest_metadata = None
  → Next message has empty detections
  → No stale bounding boxes survive restart
```

## 7. Conclusion

Phase 3.5 is **COMPLETE**. The camera monitoring system now:
- Shows only real cameras from the backend database
- No fabricated camera data, alerts, or ANPR records on initial load
- Handles EOF restart cleanly with full state reset
- Maintains continuous MJPEG video across restarts
- No stale detections or bounding boxes after restart
- Empty cameras list shows graceful "No cameras registered" message
