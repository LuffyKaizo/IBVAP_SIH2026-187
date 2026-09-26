"""Multi-object tracker using Ultralytics built-in ByteTrack.

This module wraps Ultralytics' built-in tracking capability.
The model.track() method uses ByteTrack by default.
"""

import time
import numpy as np
from typing import Optional
from dataclasses import dataclass, field

from ai.config import settings


# Surveillance-relevant COCO class IDs (YOLOv8 default mapping)
SURVEILLANCE_CLASS_IDS = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


@dataclass
class TrackedObject:
    """A single tracked object with stable ID."""
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (pixel coords)


@dataclass
class TrackingResult:
    """Result from tracking a single frame."""
    tracked_objects: list[TrackedObject] = field(default_factory=list)
    detection_time_ms: float = 0.0
    tracking_time_ms: float = 0.0
    total_time_ms: float = 0.0
    frame_width: int = 0
    frame_height: int = 0
    active_tracks: int = 0
    frame_index: int = 0


class ObjectTracker:
    """Multi-object tracker using Ultralytics built-in ByteTrack.

    Usage:
        tracker = ObjectTracker()
        tracker.load_model("yolov8n.pt")
        result = tracker.track(frame)
        for obj in result.tracked_objects:
            print(f"ID {obj.track_id}: {obj.class_name} {obj.confidence:.0%}")
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        confidence: Optional[float] = None,
        iou: Optional[float] = None,
        img_size: Optional[int] = None,
        device: Optional[str] = None,
        tracker_type: Optional[str] = None,
    ):
        self.model_path = model_path or settings.MODEL_PATH
        self.confidence = confidence or settings.MIN_TRACKING_CONFIDENCE
        self.iou = iou or settings.IOU_THRESHOLD
        self.img_size = img_size or settings.IMAGE_SIZE
        self.device = device or settings.get_device()
        self.tracker_type = tracker_type or settings.TRACKER_TYPE
        self._model = None
        self._class_names: dict[int, str] = {}
        self._frame_count = 0
        # Temporal confirmation: observation count per tracked object (class_track_id)
        self._detection_history: dict[str, int] = {}  # key -> consecutive count
        self._confirm_frames = settings.TEMPORAL_CONFIRM_FRAMES
        # Movement tracking: track center position history per tracked object
        # key -> list of (frame_idx, center_x, center_y)
        self._position_history: dict[str, list[tuple[int, float, float]]] = {}
        # Static detection filter: total frames a detection has been observed
        # key -> total_frames_seen
        self._total_frames_seen: dict[str, int] = {}
        self._STATIC_TOTAL_FRAMES = 10  # suppress after this many total observations (conservative)
        self._STATIC_MOVEMENT_THRESHOLD = 0.05  # min center movement (normalized) to count as "moved"

    def load_model(self) -> bool:
        """Load the YOLO model for tracking."""
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_path)
            self._class_names = self._model.names
            self._frame_count = 0
            return True
        except Exception as e:
            print(f"[IBVAP-TRACK] Failed to load model: {e}")
            self._model = None
            return False

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def track(self, frame: np.ndarray) -> TrackingResult:
        """Run detection + ByteTrack on a single frame.

        Returns TrackingResult with tracked objects and stable IDs.
        Only returns surveillance-relevant classes (person, car, truck, etc).
        Applies spatial-temporal confirmation + static detection suppression.
        """
        if not self.is_loaded:
            return TrackingResult(frame_index=self._frame_count)

        h, w = frame.shape[:2]
        total_start = time.time()

        # Wide frames (4K CCTV): infer at a larger size so distant/small
        # objects retain enough pixels to clear the confidence gate.
        imgsz = self.img_size if w <= settings.LARGE_FRAME_WIDTH else settings.IMAGE_SIZE_LARGE

        # Run YOLO with tracking
        det_start = time.time()
        results = self._model.track(
            frame,
            conf=self.confidence,
            iou=self.iou,
            imgsz=imgsz,
            device=self.device,
            tracker=self.tracker_type,
            persist=True,  # maintain track IDs across frames
            verbose=False,
        )
        det_time = (time.time() - det_start) * 1000
        track_time = 0.0  # tracking happens inside model.track()

        # Collect candidate detections before temporal filter
        candidates = []
        if results and len(results) > 0:
            r = results[0]
            if r.boxes is not None and r.boxes.id is not None:
                ids = r.boxes.id.cpu().numpy()
                classes = r.boxes.cls.cpu().numpy()
                confs = r.boxes.conf.cpu().numpy()
                bboxes = r.boxes.xyxy.cpu().numpy()

                for i in range(len(ids)):
                    cls_id = int(classes[i])

                    # Filter: only surveillance-relevant classes
                    if cls_id not in SURVEILLANCE_CLASS_IDS:
                        continue

                    cls_name = SURVEILLANCE_CLASS_IDS[cls_id]

                    # Validate bounding box
                    x1, y1, x2, y2 = (
                        round(float(bboxes[i][0]), 1),
                        round(float(bboxes[i][1]), 1),
                        round(float(bboxes[i][2]), 1),
                        round(float(bboxes[i][3]), 1),
                    )
                    if x1 >= x2 or y1 >= y2:
                        continue
                    if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
                        # Clip to frame bounds
                        x1 = max(0, x1)
                        y1 = max(0, y1)
                        x2 = min(w, x2)
                        y2 = min(h, y2)

                    conf = round(float(confs[i]), 4)
                    if conf < self.confidence:
                        continue

                    # Filter: minimum bounding box area (frame-relative).
                    # NOT applied to person: distant people legitimately occupy
                    # well under MIN_BBOX_AREA_PCT of the frame (verified with
                    # real footage: high-conf 0.47-0.81 standing-person boxes of
                    # 15x28..19x38 px measured 0.11-0.20% and were all dropped).
                    # Confidence + aspect + temporal confirmation still gate
                    # person detections, so the area floor only remains for
                    # vehicles and other classes where it catches noise.
                    bbox_area_pct = (x2 - x1) * (y2 - y1) / (w * h) * 100
                    if cls_name != "person" and bbox_area_pct < settings.MIN_BBOX_AREA_PCT:
                        continue

                    # Filter: aspect ratio for person class (tree trunks are tall/narrow)
                    if cls_name == "person":
                        bbox_w = x2 - x1
                        bbox_h = y2 - y1
                        if bbox_h > 0:
                            aspect_ratio = bbox_w / bbox_h
                            if aspect_ratio > settings.PERSON_MAX_ASPECT_RATIO:
                                continue  # too wide — unlikely person
                            if aspect_ratio < settings.PERSON_MIN_ASPECT_RATIO:
                                continue  # too narrow — likely tree trunk

                    candidates.append(TrackedObject(
                        track_id=int(ids[i]),
                        class_id=cls_id,
                        class_name=cls_name,
                        confidence=conf,
                        bbox=(x1, y1, x2, y2),
                    ))

        # Temporal confirmation + static detection suppression
        tracked_objects = []
        current_keys: set[str] = set()
        for obj in candidates:
            # Confirmation key: stable per tracked object. Keying on the
            # ByteTrack id (instead of a quantized spatial grid cell) keeps
            # the observation count accumulating while a person moves, so a
            # walking target is confirmed once and stays visible instead of
            # flickering every time its center crosses a 5% cell boundary.
            # Movement position (center) is still tracked for the static filter.
            cx = (obj.bbox[0] + obj.bbox[2]) / 2 / w  # normalized center x
            cy = (obj.bbox[1] + obj.bbox[3]) / 2 / h  # normalized center y
            key = f"{obj.class_name}_{obj.track_id}"
            current_keys.add(key)

            # Temporal confirmation: require N frames within a sliding window
            # Use total_frames_seen which persists across gaps
            self._total_frames_seen[key] = self._total_frames_seen.get(key, 0) + 1
            total_seen = self._total_frames_seen[key]

            # Also track consecutive frames for quick initial confirmation
            count = self._detection_history.get(key, 0) + 1
            self._detection_history[key] = count

            # Require at least N frames seen (not necessarily consecutive)
            if total_seen < self._confirm_frames:
                continue  # not enough observations yet

            # Static detection filter: track position history across entire video
            if key not in self._position_history:
                self._position_history[key] = []
            pos_hist = self._position_history[key]
            pos_hist.append((self._frame_count, cx, cy))

            # Keep only last 60 frames of position history
            if len(pos_hist) > 60:
                self._position_history[key] = pos_hist[-60:]
                pos_hist = self._position_history[key]

            # Static detection suppression: reject detections that never move
            # across their lifetime (trees, poles). Disabled by default —
            # real surveillance targets (standing people, queued vehicles)
            # are legitimately stationary and must remain visible.
            if settings.STATIC_SUPPRESSION_ENABLED and total_seen >= self._STATIC_TOTAL_FRAMES and len(pos_hist) >= 2:
                # Compare current position to earliest position in history
                earliest_frame, earliest_x, earliest_y = pos_hist[0]
                total_movement = abs(cx - earliest_x) + abs(cy - earliest_y)
                if total_movement < self._STATIC_MOVEMENT_THRESHOLD:
                    continue  # static detection — likely false positive (tree, pole)

            tracked_objects.append(obj)

        # Decay keys not seen this frame (temporal confirmation only)
        stale_keys = [k for k in self._detection_history if k not in current_keys]
        for k in stale_keys:
            del self._detection_history[k]
        # NOTE: position_history is NOT cleared on disappearance —
        # it persists so static detection filter can detect objects that
        # reappear at the same location across gaps (tree trunks, poles).
        # Clean up entries whose most recent observation is old (>200 frames)
        # — keyed on the LAST frame so long-lived tracks are not evicted
        # while they are still being observed.
        cutoff_frame = self._frame_count - 200
        stale_pos = [k for k in self._position_history
                     if self._position_history[k] and self._position_history[k][-1][0] < cutoff_frame]
        for k in stale_pos:
            del self._position_history[k]
            self._total_frames_seen.pop(k, None)
        # Bound memory of id-keyed observation counts (track ids churn forever)
        if len(self._total_frames_seen) > 4096:
            for old_key in list(self._total_frames_seen.keys())[:1024]:
                del self._total_frames_seen[old_key]

        total_time = (time.time() - total_start) * 1000
        self._frame_count += 1

        return TrackingResult(
            tracked_objects=tracked_objects,
            detection_time_ms=round(det_time, 2),
            tracking_time_ms=round(track_time, 2),
            total_time_ms=round(total_time, 2),
            frame_width=w,
            frame_height=h,
            active_tracks=len(tracked_objects),
            frame_index=self._frame_count,
        )

    def reset(self):
        """Reset tracking state in place — keeps the loaded YOLO model (and
        its CUDA context) alive so local-video loop restarts are near-instant
        and never reload weights every cycle. Clears all Python-side history
        plus ultralytics' persistent ByteTrack state (when the installed
        version exposes a tracker reset)."""
        self._frame_count = 0
        self._detection_history.clear()
        self._position_history.clear()
        self._total_frames_seen.clear()
        if self._model is not None:
            try:
                predictor = getattr(self._model, "predictor", None)
                trackers = getattr(predictor, "trackers", None) if predictor is not None else None
                if trackers:
                    for t in trackers:
                        reset_fn = getattr(t, "reset", None)
                        if callable(reset_fn):
                            reset_fn()
            except Exception:
                pass

    @property
    def frame_count(self) -> int:
        return self._frame_count
