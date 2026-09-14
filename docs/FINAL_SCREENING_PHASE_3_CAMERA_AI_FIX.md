# Phase 3 — Camera AI Fix: Debug & Evidence-Based Calibration

**Date:** 2026-09-12
**Status:** IMPLEMENTED + TESTED + LIVE VERIFIED

---

## 1. Root Cause of Dummy Startup Image

**Cause:** When AI was OFF, `CamerasMonitoringView` used `activeCamera.videoPosterUrl` as the `<img>` source. All cameras had Unsplash placeholder URLs.

**Evidence:** `src/mockData.ts` lines 28, 59, 89, 105, 132, 147, 164 — all `videoPosterUrl` fields pointed to `images.unsplash.com`.

**Fix:** Cleared all `videoPosterUrl` fields to empty strings. Modified `CamerasMonitoringView` to always construct the real MJPEG stream URL from camera ID + auth token, regardless of AI on/off state.

**Files changed:** `src/mockData.ts`, `src/views/CamerasMonitoringView.tsx`

---

## 2. Root Cause of Red Placeholder Box

**Cause:** `INITIAL_CAMERAS` in `mockData.ts` contained hardcoded `detections` arrays with fake detections (e.g., `DET-101` with `MH12AB1234` plate number, `DET-105` with `isThreat: true`). These rendered via the AI OFF fallback path in `CamerasMonitoringView` lines 290-317.

**Evidence:** `src/mockData.ts` — CAM-01 had `DET-101` (vehicle, 91%), CAM-02 had `DET-102` (person, 88%), CAM-03 had `DET-103`/`DET-104`, CAM-04 had `DET-105`/`DET-106`, CAM-06 had `DET-107`.

**Fix:** Cleared all `detections: []` in every camera entry. The "Active Targets" sidebar now shows "No active targets" when AI is OFF.

**Files changed:** `src/mockData.ts`

---

## 3. Root Cause of Blue False Person Boxes

**Cause:** YOLOv8n pretrained on COCO produces many low-confidence false positives on surveillance footage. At `MIN_TRACKING_CONFIDENCE=0.25`, 98% of detections had bbox area < 1% of frame, with 48% being very tiny (< 0.3%). These tiny detections on trees, foliage, and background textures were classified as "person" with confidence 0.25-0.35.

**Evidence (diagnostic data from `surveillance_test.mp4`):**

| Threshold | Total Dets | Small (<1%) | Very Small (<0.3%) |
|-----------|-----------|-------------|---------------------|
| 0.25 (old) | 386 | 378 (98%) | 185 (48%) |
| 0.35 | 177 | 176 (99%) | 56 (32%) |
| 0.45 (new) | 84 | 84 (100%) | 11 (13%) |
| 0.50 | 56 | 56 (100%) | 3 (5%) |

At conf=0.25, YOLO produces person detections on tree bark textures, shadows, and background foliage — these are standard YOLOv8n false positive patterns on surveillance footage.

**Fix (evidence-based):**
1. Raised `MIN_TRACKING_CONFIDENCE` from 0.25 to 0.45 in `ai/config.py`
2. Added minimum bounding box area filter (0.3% of frame) in `ai/tracking/tracker.py`
3. Live pipeline test confirmed: 15 WebSocket messages yielded only 2 real person detections (conf=0.515), zero false positives

**Files changed:** `ai/config.py`, `ai/tracking/tracker.py`

---

## 4. YOLO Confidence Threshold Before/After

| Parameter | Before | After |
|-----------|--------|-------|
| `MIN_TRACKING_CONFIDENCE` | 0.25 | 0.45 |
| Min bbox area | None | 0.3% of frame |
| `CONFIDENCE_THRESHOLD` | 0.50 | 0.50 (unchanged) |

The `CONFIDENCE_THRESHOLD` setting exists in config but is NOT used by the tracker — only `MIN_TRACKING_CONFIDENCE` is used by `ObjectTracker.track()`.

---

## 5. Class Mapping Verification

**COCO class IDs used by YOLOv8n (verified from model.names):**

| ID | Class Name | In SURVEILLANCE_CLASS_IDS |
|----|-----------|--------------------------|
| 0 | person | Yes |
| 1 | bicycle | Yes |
| 2 | car | Yes |
| 3 | motorcycle | Yes |
| 5 | bus | Yes |
| 7 | truck | Yes |

All other COCO classes (airplane, train, boat, traffic light, etc.) are filtered out by the tracker. The backend sends `class_id` and `class_name` consistently; frontend renders the received `class_name`.

---

## 6. Coordinate Transformation Verification

**Chain:** YOLO pixel coordinates → `x/W, y/H` (normalize) → WebSocket JSON → `× 100` (CSS %) → `position: absolute`

**Mathematical verification (frame 1920×1080):**
- Pixel bbox: [1468.0, 571.9, 1528.7, 742.8]
- Normalized: [0.7646, 0.5295, 0.7962, 0.6878]
- CSS: left=76.46% top=52.95% width=3.16% height=15.83%
- Roundtrip error: **0.11 pixels** (from rounding only)

No coordinate bugs found. The `object-fit: cover` on the `<img>` tag matches the 16:9 video aspect ratio with the `aspect-video` container.

---

## 7. Tracker Lifecycle Verification

**ByteTrack behavior tested over 80 frames:**

- Tracks are immediately LOST when detection disappears (no extrapolation)
- Track IDs persist correctly across re-detections (e.g., person#2 reappears at F15, F23, F28)
- No phantom tracks created by ByteTrack
- Tracker reset on video EOF (pipeline calls `self._tracker.reset()`)
- 0.3% min bbox filter correctly removes 1-frame noise (e.g., person#15 at area=0.25%)

**Conclusion:** ByteTrack does NOT create visual bounding boxes when there is no current valid detector observation.

---

## 8. Stale-Box Handling

**Verified mechanisms:**

| Event | Behavior |
|-------|----------|
| Frame N has detection, N+1 does not | Box disappears immediately |
| Camera switch | `connect()` calls `setMetadata(null)`, clears old boxes |
| AI toggle off | `disconnect()` calls `setMetadata(null)` |
| WebSocket disconnect | `onclose` calls `setMetadata(null)` |
| Video EOF restart | Pipeline calls `self.state.clear()` and `self._tracker.reset()` |
| Reconnect | Old state cleared before new WebSocket connects |

---

## 9. Rendering Architecture

**Single authoritative path (no dual rendering):**

```
REAL VIDEO FRAME (MJPEG from backend)
        ↓
<img> tag (always shows real stream, AI on or off)
        ↓
CSS absolute-positioned overlays (AIBoundingBoxOverlay, AIFaceOverlay)
        ↓
Only rendered when isRealAi && detections.length > 0
```

- MJPEG stream serves raw frames (OpenCV `_draw_detections` removed from MJPEG path)
- All bounding boxes rendered by frontend CSS overlay only
- No duplicate rendering paths
- No OpenCV-annotated frames in the stream

---

## 10. Test Results

### Python Tests
- **265/265 passed** (246 existing + 19 new regression tests)
- New test file: `ai/tests/test_camera_ai_fix.py`
- Tests cover: confidence filtering, bbox size filter, class mapping, coordinate normalization, no placeholder detections, pipeline state clearing, detection metadata structure, source field verification

### TypeScript
- `npx tsc --noEmit`: **0 errors**
- `npx vite build`: **built in 9.75s**

### Live Pipeline Test
- AI backend restarted with conf=0.45
- 15 WebSocket messages: 2 real person detections, 0 false positives
- Confidence range: 0.515 (both detections)
- Bbox area: 0.57% (above 0.3% filter)

---

## 11. Remaining Limitations

1. **YOLOv8n is not border-domain trained.** The model is pretrained on COCO (everyday objects). Border surveillance detection accuracy will improve during the real-data training phase.

2. **Small distant objects.** All detections in `surveillance_test.mp4` have bbox area < 1% of frame. Very small objects (< 0.3% frame area) are filtered to reduce false positives. This may miss extremely distant persons/vehicles.

3. **Video loops.** When `surveillance_test.mp4` reaches EOF, the pipeline restarts cleanly (tracker reset, state clear). This is correct behavior for demo purposes.

4. **CAM-01 is the only pipeline.** Only one camera has a running AI pipeline. CAM-02 through CAM-06 show "No active targets" when AI is enabled, since no pipeline is processing them.

---

## 12. Files Changed

| File | Change |
|------|--------|
| `ai/config.py` | `MIN_TRACKING_CONFIDENCE`: 0.25 → 0.45 |
| `ai/tracking/tracker.py` | Added 0.3% min bbox area filter |
| `src/mockData.ts` | Cleared all mock detections, cleared all Unsplash poster URLs |
| `src/views/CamerasMonitoringView.tsx` | Always use real MJPEG URL; removed poster fallback |
| `src/hooks/useAiCameraStream.ts` | (Previously fixed) Stale auth token bug |
| `ai/tests/test_camera_ai_fix.py` | New: 19 regression tests |

---

## 13. What Was NOT Changed

- `src/views/LoginView.tsx` — not touched
- `src/views/CommandDashboardView.tsx` — not touched
- No model retraining
- No mock data added back
- No hardcoded bounding boxes
- No detections hidden for cosmetic reasons

---

## 14. Verification Status

| Item | Status |
|------|--------|
| Dummy startup image removed | IMPLEMENTED, TESTED |
| Red placeholder boxes removed | IMPLEMENTED, TESTED |
| Blue false person boxes addressed | IMPLEMENTED, TESTED (confidence threshold + size filter) |
| YOLO class mapping verified | IMPLEMENTED, TESTED |
| Coordinate transformation verified | IMPLEMENTED, TESTED (0.11px error) |
| Stale detection clearing verified | IMPLEMENTED, TESTED |
| ByteTrack lifecycle verified | IMPLEMENTED, TESTED |
| Real-frame rendering architecture | IMPLEMENTED, TESTED |
| Browser visual verification | **NOT YET VERIFIED** — requires manual browser check |
