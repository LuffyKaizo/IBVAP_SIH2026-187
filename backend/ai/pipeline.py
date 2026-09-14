"""IBVAP Processing Pipeline."""

import asyncio
import time
import threading
import cv2
import numpy as np
from typing import Optional
from datetime import datetime, timezone

from ai.config import settings
from ai.video.capture import VideoCapture
from ai.tracking.tracker import ObjectTracker, TrackingResult
from ai.events.behavior import BehaviorEngine
from ai.anpr.plate_detector import PlateDetector
from ai.anpr.ocr_engine import OCREngine
from ai.anpr.temporal import TemporalStabilizer
from ai.face.face_detector import FaceDetector, associate_faces_with_persons
from ai.context.engine import ContextEngine
from ai.risk.engine import RiskEngine


class PipelineState:
    def __init__(self, camera_id="CAM-01", camera_name=""):
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_metadata = None
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.video_connected = False
        self.ai_processing = False
        self.processing_fps = 0.0
        self.source_fps = 0.0
        self.resolution = ""
        self.frames_processed = 0
        self.total_detections = 0
        self._fps_samples = []
        self._metadata_timestamp = 0.0
        self._capture = None  # set by ProcessingPipeline for camera health reporting
        # Optional persistence repositories (set by CameraPipeline)
        self._event_repo = None
        self._alert_repo = None
        self._anpr_repo = None
        # Optional evidence capture service (set by CameraPipeline)
        self._evidence_capture = None
        # Optional sync manager (set by CameraPipeline)
        self._sync_manager = None
        # Persistence lifecycle tracking (bounded, runtime-only)
        # Maps event_id -> last_persisted_status (e.g. "DETECTED", "ACTIVE", "RESOLVED")
        self._persisted_events: dict = {}
        # Set of alert IDs that have been persisted (alerts are insert-once)
        self._persisted_alerts: set = set()
        # Set of ANPR record IDs that have been persisted
        self._persisted_anpr: set = set()
        # Context engine state
        self._context_contexts: list = []
        # Alert dedup + escalation: key -> (alert_dict, first_seen_timestamp)
        self._active_alerts: dict = {}
        self._alert_first_seen: dict = {}
        # Severity order for escalation comparison
        self._SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    def update(self, frame, tracking, camera_id, faces=None):
        h, w = frame.shape[:2]  # numpy shape is (height, width, channels)
        detections = []
        for obj in tracking.tracked_objects:
            x1, y1, x2, y2 = obj.bbox
            # Ground-point for zone intrusion (bottom-center)
            ground_x = (x1 + x2) / 2 / w
            ground_y = y2 / h
            detections.append({
                "track_id": obj.track_id,
                "class_id": obj.class_id,
                "class_name": obj.class_name,
                "confidence": obj.confidence,
                "bbox": {
                    "x1": round(x1 / w, 4),
                    "y1": round(y1 / h, 4),
                    "x2": round(x2 / w, 4),
                    "y2": round(y2 / h, 4),
                },
                "ground_point": {
                    "x": round(ground_x, 4),
                    "y": round(ground_y, 4),
                },
            })
        now = time.time()
        metadata = {
            "camera_id": camera_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "real",
            "frame_width": w,
            "frame_height": h,
            "detections": detections,
            "active_tracks": tracking.active_tracks,
            "inference_time_ms": tracking.total_time_ms,
            "frame_index": tracking.frame_index,
            "events": [],
            "faces": faces or [],
        }
        cap = self._capture
        if cap is not None:
            cs = cap.get_status()
            metadata["camera"] = {
                "connected": cs.connected,
                "sourceType": cs.source_type,
                "source": cs.source,
                "status": cs.status,
                "fps": cs.fps,
                "measuredSourceFps": cs.measured_source_fps,
                "processingFps": round(self.processing_fps, 1),
                "frameWidth": cs.width,
                "frameHeight": cs.height,
                "lastFrameTimestamp": cs.last_frame_timestamp,
                "reconnectCount": cs.reconnect_count,
                "lastError": cs.last_error,
            }
        with self.lock:
            self.latest_frame = frame.copy()
            self.latest_metadata = metadata
            self._metadata_timestamp = now
            self.frames_processed += 1
            self.total_detections += tracking.active_tracks
            self._fps_samples.append(now)
            cutoff = now - 2.0
            self._fps_samples = [t for t in self._fps_samples if t > cutoff]
            self.processing_fps = len(self._fps_samples) / 2.0

    @staticmethod
    def _event_to_alert(event, camera_name=""):
        """Convert a security event dict to a BorderAlert-compatible dict."""
        etype = event.get("event_type", "")
        track_id = event.get("track_id", -1)
        zone_id = event.get("zone_id", "")
        zone_name = event.get("zone_name", "")
        reasons = event.get("reasons", [])

        # Map AI event types to BorderAlert event types
        alert_type_map = {
            "PERSON_INTRUSION": "BORDER_INTRUSION",
            "VEHICLE_INTRUSION": "RESTRICTED_ZONE_VEHICLE",
            "LOITERING": "LOITERING",
            "NIGHT_MOVEMENT": "NIGHT_MOVEMENT",
            "SUSPICIOUS_ACTIVITY": "SUSPICIOUS_ACTIVITY",
        }
        alert_event_type = alert_type_map.get(etype, etype)

        # Map severity
        severity = event.get("severity", "MEDIUM")

        # Generate title
        titles = {
            "PERSON_INTRUSION": "Border Perimeter Intrusion Breach",
            "VEHICLE_INTRUSION": "Unidentified Vehicle in Restricted Zone",
            "LOITERING": "Perimeter Loitering Detected",
            "NIGHT_MOVEMENT": "Unauthorized Night-Time Movement",
            "SUSPICIOUS_ACTIVITY": "Suspicious Activity Detected",
        }
        title = titles.get(etype, "Security Event")

        # Generate reason
        if etype == "SUSPICIOUS_ACTIVITY" and reasons:
            reason = "Suspicious: " + " + ".join(reasons)
        else:
            reason = event.get("reason", event.get("event_type", ""))

        # Build evidence checklist
        evidence = []
        if event.get("confidence", 0) > 0:
            evidence.append(f"Detection confidence: {event['confidence']*100:.0f}%")
        if track_id >= 0:
            evidence.append(f"ByteTrack assigned persistent Track ID #{track_id}")
        if zone_name:
            evidence.append(f"Restricted zone: {zone_name}")
        if reasons:
            for r in reasons:
                evidence.append(f"Rule triggered: {r}")
        if not evidence:
            evidence.append("AI event engine trigger")

        # Generate camera name — use the provided camera_name if available,
        # otherwise fall back to the camera_id from the event.
        resolved_name = camera_name or event.get("camera_id", "")

        return {
            "id": "ALT-AI-" + event.get("event_id", "0000"),
            "timestamp": event.get("timestamp", ""),
            "cameraId": event.get("camera_id", ""),
            "cameraName": resolved_name,
            "eventType": alert_event_type,
            "title": title,
            "severity": severity,
            "trackId": f"#{track_id}" if track_id >= 0 else "#?",
            "confidence": round(event.get("confidence", 0) * 100),
            "zone": zone_name or "Default Zone",
            "reason": reason,
            "evidenceChecklist": evidence,
            "status": event.get("status", "ACTIVE"),
            "source": "AI",
            # Risk + context metadata (enriched by pipeline)
            "riskScore": event.get("risk_score", 0),
            "riskSeverity": event.get("risk_severity", severity),
            "riskFactors": event.get("risk_factors", []),
            "dwellSeconds": event.get("dwell_seconds", 0),
            "loitering": event.get("loitering", False),
            "fenceProximity": event.get("fence_proximity", False),
            "direction": event.get("direction", ""),
            "repeatedEntry": event.get("repeated_entry", False),
        }

    def set_events(self, events):
        """Attach security events and AI-generated alerts to the latest metadata.
        Persists only on status transitions (DETECTED→ACTIVE→RESOLVED).
        Captures evidence snapshot on DETECTED transition.
        Deduplicates and escalates alerts for the same logical incident.
        Uses thread-safe scheduling for database operations.
        """
        with self.lock:
            if self.latest_metadata is not None:
                serialized_events = []
                alerts = []
                for e in events:
                    if isinstance(e, dict):
                        event_dict = e
                    else:
                        event_dict = {
                            "event_id": e.event_id,
                            "event_type": e.event_type,
                            "severity": e.severity,
                            "camera_id": e.camera_id,
                            "zone_id": e.zone_id,
                            "zone_name": e.zone_name,
                            "track_id": e.track_id,
                            "object_class": e.object_class,
                            "timestamp": e.timestamp,
                            "confidence": e.confidence,
                            "bbox": e.bbox,
                            "status": e.status,
                        }
                    serialized_events.append(event_dict)
                    alert = self._event_to_alert(event_dict, self.camera_name)

                    # Dedup + escalation logic
                    action, existing = self._should_create_or_escalate(event_dict, alert)

                    if action == "CREATE":
                        alerts.append(alert)
                        self._record_alert(event_dict, alert)
                        prev_status = self._persisted_events.get(event_dict.get("event_id"))
                        event_future = self._persist_event_lifecycle(event_dict, alert)
                        if (self._evidence_capture
                                and event_dict.get("status") == "DETECTED"
                                and prev_status is None):
                            frame = self.latest_frame
                            if frame is not None:
                                self._schedule_persist(
                                    self._capture_after_event(event_future, event_dict, frame)
                                )
                    elif action == "ESCALATE":
                        # Escalate existing alert severity + metadata
                        alert["id"] = existing["id"]
                        alert["status"] = existing.get("status", "ACTIVE")
                        alerts.append(alert)
                        self._record_alert(event_dict, alert)
                        # Allow evidence capture on meaningful escalation
                        if (self._evidence_capture
                                and event_dict.get("status") == "DETECTED"):
                            frame = self.latest_frame
                            if frame is not None:
                                event_future = self._persist_event_lifecycle(event_dict, alert)
                                self._schedule_persist(
                                    self._capture_after_event(event_future, event_dict, frame)
                                )
                    else:  # UPDATE — metadata only
                        alert["id"] = existing["id"]
                        alert["status"] = existing.get("status", "ACTIVE")
                        alerts.append(alert)
                        self._record_alert(event_dict, alert)

                self.latest_metadata["events"] = serialized_events
                self.latest_metadata["alerts"] = alerts

    def set_anpr_results(self, results):
        """Attach ANPR results to the latest metadata.
        Persists confirmed ANPR results (insert-once per record_id).
        """
        with self.lock:
            if self.latest_metadata is not None:
                self.latest_metadata["anpr"] = results
                if self._anpr_repo and results:
                    for r in results:
                        if isinstance(r, dict) and r.get("status") in ("CONFIRMED", "RECOGNIZED"):
                            record_id = r.get("id", "")
                            if record_id and record_id not in self._persisted_anpr:
                                self._persisted_anpr.add(record_id)
                                self._schedule_persist(self._do_persist_anpr(r))

    def set_context(self, contexts):
        """Store per-track context for overlay and risk scoring."""
        self._context_contexts = contexts
        if self.latest_metadata is not None:
            self.latest_metadata["track_context"] = [
                {
                    "track_id": c.track_id,
                    "object_class": c.object_class,
                    "dwell_seconds": round(c.dwell_seconds, 1),
                    "loitering": c.loitering,
                    "fence_proximity": c.fence_proximity,
                    "distance_to_fence": round(c.distance_to_fence, 3),
                    "direction": c.direction,
                    "repeated_entry": c.repeated_entry,
                    "entry_count": c.entry_count,
                }
                for c in contexts
            ]

    def _find_track_context(self, track_id, contexts=None):
        """Find TrackContext for a given track_id."""
        if contexts is None:
            contexts = self._context_contexts
        for c in contexts:
            if c.track_id == track_id:
                return c
        return None

    def _make_dedup_key(self, event_dict):
        """Generate dedup key for alert deduplication/escalation."""
        return "%s:%s:%s" % (
            event_dict.get("camera_id", ""),
            event_dict.get("track_id", -1),
            event_dict.get("event_type", ""),
        )

    def _should_create_or_escalate(self, event_dict, alert_dict):
        """Determine whether to create a new alert or escalate existing.

        Returns (action, existing_alert) where action is 'CREATE', 'ESCALATE', or 'UPDATE'.
        """
        import time as _time
        now = _time.time()
        dedup_key = self._make_dedup_key(event_dict)

        if dedup_key in self._active_alerts:
            existing, first_seen = self._active_alerts[dedup_key], self._alert_first_seen[dedup_key]
            # Check if within active window
            if now - first_seen <= settings.ALERT_ACTIVE_WINDOW_SEC:
                new_severity = alert_dict.get("severity", "MEDIUM")
                old_severity = existing.get("severity", "MEDIUM")
                new_order = self._SEVERITY_ORDER.get(new_severity, 1)
                old_order = self._SEVERITY_ORDER.get(old_severity, 1)
                if new_order > old_order:
                    return "ESCALATE", existing
                return "UPDATE", existing
            else:
                # Window expired — new incident
                return "CREATE", None
        return "CREATE", None

    def _record_alert(self, event_dict, alert_dict):
        """Record alert in dedup tracking."""
        dedup_key = self._make_dedup_key(event_dict)
        self._active_alerts[dedup_key] = alert_dict
        self._alert_first_seen[dedup_key] = __import__("time").time()

    def _persist_event_lifecycle(self, event_dict, alert_dict):
        """Persist event based on lifecycle state transitions.

        Lifecycle: DETECTED -> ACTIVE -> RESOLVED

        Only writes to DB on status changes, preventing duplicate INSERTs.
        Uses schedule_async() for thread-safe scheduling from camera worker threads.
        Returns the scheduling Future (or None if skipped).
        """
        event_id = event_dict.get("event_id", "")
        if not event_id or not self._event_repo:
            return None

        current_status = event_dict.get("status", "DETECTED")
        last_status = self._persisted_events.get(event_id)
        if last_status == current_status:
            return None  # No transition — skip DB write

        # Track the transition
        self._persisted_events[event_id] = current_status

        # Clean up resolved events from tracking (bounded memory)
        if current_status == "RESOLVED":
            # Keep in tracking briefly in case of re-entry, will be cleaned on next cycle
            pass

        # Schedule the persistence and return the future
        return self._schedule_persist(
            self._do_persist_event_lifecycle(event_dict, alert_dict, last_status, current_status)
        )

    async def _do_persist_event_lifecycle(self, event_dict, alert_dict, last_status, new_status):
        """Execute the actual database persistence for event lifecycle."""
        event_id = event_dict.get("event_id", "")
        if not event_id:
            return

        # 1. INSERT on DETECTED (first time we see this event)
        if new_status == "DETECTED" and self._event_repo:
            from ai.events.engine import SecurityEvent
            se = SecurityEvent(
                event_id=event_id,
                event_type=event_dict.get("event_type", ""),
                severity=event_dict.get("severity", "MEDIUM"),
                camera_id=event_dict.get("camera_id", self.camera_id),
                zone_id=event_dict.get("zone_id", ""),
                zone_name=event_dict.get("zone_name", ""),
                track_id=event_dict.get("track_id", -1),
                object_class=event_dict.get("object_class", "unknown"),
                timestamp=event_dict.get("timestamp", ""),
                confidence=event_dict.get("confidence", 0),
                bbox=event_dict.get("bbox", {}),
                status="DETECTED",
            )
            await self._event_repo.create(se)
            # Enqueue for sync
            if self._sync_manager:
                await self._sync_manager.enqueue_event(event_id, event_dict)

        # 2. INSERT alert on DETECTED (once per event)
        if new_status == "DETECTED" and self._alert_repo and alert_dict.get("id"):
            if alert_dict["id"] not in self._persisted_alerts:
                self._persisted_alerts.add(alert_dict["id"])
                await self._alert_repo.create(alert_dict)

        # 3. UPDATE status on ACTIVE (if transition from DETECTED)
        if new_status == "ACTIVE" and last_status == "DETECTED" and self._event_repo:
            await self._event_repo.update_status(event_id, "ACTIVE")

        # 4. UPDATE status on RESOLVED
        if new_status == "RESOLVED" and self._event_repo:
            await self._event_repo.update_status(event_id, "RESOLVED")
            # Clean up tracking for resolved events
            self._persisted_events.pop(event_id, None)

    def _do_persist_anpr(self, result):
        """Persist ANPR result (insert-once)."""
        async def _persist():
            if self._anpr_repo:
                await self._anpr_repo.create(result)
        self._schedule_persist(_persist())

    async def _capture_and_enqueue_sync(self, event_dict, frame):
        """Capture evidence and enqueue for sync (non-blocking)."""
        try:
            result = await self._evidence_capture.capture_snapshot(
                event_dict, frame, actor="SYSTEM"
            )
            if result and self._sync_manager:
                await self._sync_manager.enqueue_evidence(result.get("id", ""), result)
            return result
        except Exception:
            return None

    async def _capture_after_event(self, event_future, event_dict, frame):
        """Wait for event persistence to commit, then capture evidence.

        Prevents FK violation by ensuring the security_events row exists
        before inserting the evidence row referencing it.
        """
        if event_future is not None:
            try:
                await asyncio.wrap_future(event_future)
            except Exception:
                pass
        return await self._capture_and_enqueue_sync(event_dict, frame)

    def _schedule_persist(self, coro):
        """Thread-safe scheduling of async persistence task. Returns the Future."""
        from ai.db.session import schedule_async
        return schedule_async(coro)

    def clear(self):
        """Clear all state - called on pipeline restart / video restart."""
        with self.lock:
            self.latest_frame = None
            self.latest_metadata = None
            self._metadata_timestamp = 0.0
            self.frames_processed = 0
            self.total_detections = 0
            self._fps_samples = []
            self.processing_fps = 0.0
            self._persisted_events.clear()
            self._persisted_alerts.clear()
            self._persisted_anpr.clear()
            self._context_contexts.clear()
            self._active_alerts.clear()
            self._alert_first_seen.clear()

    def get_latest_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def get_latest_metadata(self):
        with self.lock:
            return self.latest_metadata.copy() if self.latest_metadata is not None else None

    def get_status(self):
        with self.lock:
            status = {
                "camera_id": self.camera_id,
                "video_connected": self.video_connected,
                "ai_processing": self.ai_processing,
                "processing_fps": round(self.processing_fps, 1),
                "source_fps": self.source_fps,
                "resolution": self.resolution,
                "frames_processed": self.frames_processed,
                "total_detections": self.total_detections,
            }
        cap = self._capture
        if cap is not None:
            cs = cap.get_status()
            status["camera"] = {
                "connected": cs.connected,
                "sourceType": cs.source_type,
                "source": cs.source,
                "status": cs.status,
                "fps": cs.fps,
                "measuredSourceFps": cs.measured_source_fps,
                "frameWidth": cs.width,
                "frameHeight": cs.height,
                "lastFrameTimestamp": cs.last_frame_timestamp,
                "reconnectCount": cs.reconnect_count,
                "lastError": cs.last_error,
            }
        return status


class ProcessingPipeline:
    def __init__(self, camera_id="CAM-01", camera_name=""):
        self.camera_id = camera_id
        self.state = PipelineState(camera_id=camera_id, camera_name=camera_name)
        self._thread = None
        self._stop_event = threading.Event()
        self._tracker = None
        self._video_source = None
        self._video_source_type = None
        self._zones = []  # configured zones
        self._event_engine = None  # will be set by main.py
        self._behavior_engine = None  # behavior analytics
        self._context_engine = None  # context intelligence
        self._risk_engine = RiskEngine()  # risk scoring
        self._plate_detector = None
        self._ocr_engine = None
        self._temporal = None
        self._face_detector = None
        self._face_frame_counter = 0
        self._capture = None  # live VideoCapture handle (camera-status reporting)

    def configure(self, video_source=None, video_source_type=None, model_path=None):
        self._video_source = video_source or settings.VIDEO_SOURCE
        self._video_source_type = video_source_type or settings.VIDEO_SOURCE_TYPE
        self._tracker = ObjectTracker(model_path=model_path)

    def set_event_engine(self, engine):
        """Set the event engine for zone intrusion detection."""
        self._event_engine = engine

    def set_behavior_engine(self, engine):
        self._behavior_engine = engine

    def set_context_engine(self, engine):
        self._context_engine = engine

    def set_risk_engine(self, engine):
        self._risk_engine = engine

    def set_anpr(self, plate_detector, ocr_engine, temporal):
        self._plate_detector = plate_detector
        self._ocr_engine = ocr_engine
        self._temporal = temporal

    def set_face_detector(self, face_detector):
        """Set the face detector (detection only — no recognition)."""
        self._face_detector = face_detector

    def set_zones(self, zones):
        """Set zones for intrusion detection."""
        self._zones = zones

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        if not self._tracker:
            self.configure()
        self._stop_event.clear()
        self.state.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop_event.set()
        if self._capture is not None:
            self._capture.stop()  # unblock backoff sleeps promptly
        if self._thread:
            self._thread.join(timeout=5.0)
        self.state.ai_processing = False
        self.state.video_connected = False

    def _run_loop(self):
        print("[IBVAP-PIPELINE] Starting for %s" % self.camera_id)
        if not self._tracker.load_model():
            print("[IBVAP-PIPELINE] Model load failed")
            return
        cap = VideoCapture(source=self._video_source, source_type=self._video_source_type)
        self._capture = cap
        self.state._capture = cap
        if not cap.open():
            print("[IBVAP-PIPELINE] Video open failed")
            self.state.video_connected = False
            self._capture = None
            self.state._capture = None
            return
        w, h = cap.get_resolution()
        fps = cap.get_fps()
        self.state.video_connected = True
        self.state.source_fps = fps
        self.state.resolution = "%dx%d" % (w, h)
        self.state.ai_processing = True
        print("[IBVAP-PIPELINE] Connected: %s @ %.1f fps" % (self.state.resolution, fps))
        target_interval = 1.0 / settings.INFERENCE_FPS
        try:
            while not self._stop_event.is_set():
                loop_start = time.time()
                frame = cap.read_frame()
                if frame is None:
                    if cap.is_network_source:
                        # Network streams: controlled reconnect with backoff.
                        # Pipeline state is kept so the operator sees
                        # RECONNECTING instead of a hard reset.
                        self.state.video_connected = False
                        if self._stop_event.is_set() or not cap.reconnect():
                            if self._stop_event.is_set():
                                break
                            # reconnect failed -> next loop iteration retries
                            continue
                        self.state.video_connected = True
                        continue
                    # Local video reached EOF — restart cleanly
                    print("[IBVAP-PIPELINE] Video EOF, restarting...")
                    cap.release()
                    self._tracker.reset()
                    self.state.clear()
                    if self._event_engine:
                        self._event_engine.resolve_all()
                    if self._behavior_engine:
                        self._behavior_engine.resolve_all()
                    if self._context_engine:
                        self._context_engine._track_states.clear()
                    if self._temporal:
                        self._temporal.resolve_all()
                    cap = VideoCapture(source=self._video_source, source_type=self._video_source_type)
                    self._capture = cap
                    self.state._capture = cap
                    if not cap.open():
                        break
                    continue
                tracking = self._tracker.track(frame)

                # Run context engine (sits between tracking and events)
                context_contexts = []
                context_events = []
                if self._context_engine and self._zones:
                    context_contexts, context_events = self._context_engine.process_frame(
                        tracking, self.camera_id, self._zones
                    )

                # Run event engine if configured
                events = list(context_events)  # start with context events
                if self._event_engine and self._zones:
                    events.extend(self._event_engine.process_frame(
                        tracking, self.camera_id, self._zones
                    ))
                # Run behavior analytics
                behavior_events = []
                if self._behavior_engine:
                    behavior_events = self._behavior_engine.process_frame(
                        tracking, self.camera_id
                    )
                    # Convert SecurityEvent objects to dicts for evaluate_suspicious
                    combined = []
                    for e in events + behavior_events:
                        if isinstance(e, dict):
                            combined.append(e)
                        else:
                            combined.append({
                                "event_id": e.event_id, "event_type": e.event_type,
                                "severity": e.severity, "camera_id": e.camera_id,
                                "zone_id": e.zone_id, "track_id": e.track_id,
                                "object_class": e.object_class, "timestamp": e.timestamp,
                                "confidence": e.confidence, "bbox": e.bbox,
                                "status": e.status, "zone_name": e.zone_name,
                            })
                    sus_events = self._behavior_engine.evaluate_suspicious(
                        combined, self.camera_id
                    )
                    behavior_events.extend(sus_events)
                events.extend(behavior_events)

                # Risk enrichment: score each event and enrich with context
                from ai.events.behavior import is_night_time
                is_night = is_night_time(datetime.now(timezone.utc).hour)
                for idx, ev in enumerate(events):
                    if isinstance(ev, dict):
                        ev_dict = ev
                    else:
                        ev_dict = {
                            "event_id": ev.event_id, "event_type": ev.event_type,
                            "severity": ev.severity, "camera_id": ev.camera_id,
                            "zone_id": ev.zone_id, "track_id": ev.track_id,
                            "object_class": ev.object_class, "timestamp": ev.timestamp,
                            "confidence": ev.confidence, "bbox": ev.bbox,
                            "status": ev.status, "zone_name": ev.zone_name,
                        }
                        events[idx] = ev_dict
                    # Find matching track context
                    track_ctx = self.state._find_track_context(ev_dict.get("track_id", -1), context_contexts)
                    risk = self._risk_engine.assess(ev_dict, track_context=track_ctx, is_night=is_night)
                    ev_dict["risk_score"] = risk.risk_score
                    ev_dict["risk_severity"] = risk.severity
                    ev_dict["risk_factors"] = risk.risk_factors
                    # Add context metadata
                    if track_ctx:
                        ev_dict["dwell_seconds"] = track_ctx.dwell_seconds
                        ev_dict["loitering"] = track_ctx.loitering
                        ev_dict["fence_proximity"] = track_ctx.fence_proximity
                        ev_dict["direction"] = track_ctx.direction
                        ev_dict["repeated_entry"] = track_ctx.repeated_entry
                    # Escalate severity if risk is higher
                    from ai.risk.engine import RiskEngine as RE
                    base_sev = ev_dict.get("severity", "MEDIUM")
                    risk_sev = risk.severity
                    ev_dict["severity"] = RE.effective_severity(base_sev, risk_sev)

                # Run ANPR if configured
                anpr_results = []
                if self._plate_detector and self._ocr_engine and self._temporal and settings.ANPR_ENABLED:
                    anpr_results = self._run_anpr(tracking, frame)
                    # Cleanup stale tracks
                    active_ids = {obj.track_id for obj in tracking.tracked_objects
                                  if obj.class_name in settings.ANPR_VEHICLE_CLASSES}
                    self._temporal.cleanup_stale(active_ids, self.camera_id)

                # Run face DETECTION (interval-controlled, person crops first)
                faces_payload = []
                if (self._face_detector is not None
                        and settings.FACE_DETECTION_ENABLED
                        and self._face_detector.is_available):
                    self._face_frame_counter += 1
                    if self._face_frame_counter % max(1, settings.FACE_DETECTION_INTERVAL) == 0:
                        faces_payload = self._run_face_detection(tracking, frame)
                # Always refresh faces in metadata so stale boxes never linger:
                # when not run this frame (or none found), [] replaces old boxes.

                # Pass raw frame to MJPEG stream; CSS overlay handles bounding boxes
                self.state.update(frame, tracking, self.camera_id, faces=faces_payload)
                self.state.set_context(context_contexts)
                if events:
                    self.state.set_events(events)
                # Attach ANPR results to metadata for WebSocket transport
                if anpr_results:
                    self.state.set_anpr_results(anpr_results)
                elapsed = time.time() - loop_start
                if elapsed < target_interval:
                    time.sleep(target_interval - elapsed)
        except Exception as e:
            print("[IBVAP-PIPELINE] Error: %s" % e)
        finally:
            cap.release()
            self.state.ai_processing = False
            self.state.video_connected = False
            if self._temporal:
                self._temporal.resolve_all()
            self.state.clear()
            print("[IBVAP-PIPELINE] Stopped for %s" % self.camera_id)


    def _run_face_detection(self, tracking, frame):
        """Detect faces and associate them with person tracks.

        Strategy: run the detector on tracked PERSON crops first (cheap,
        avoids scanning irrelevant regions). If no persons are tracked but
        faces may still be visible (detector only), fall back to one
        full-frame pass so faces are not missed — documented trade-off,
        still interval-throttled.
        """
        from datetime import datetime, timezone
        fh, fw = frame.shape[:2]
        faces = []
        raw_dets = []

        person_tracks = [o for o in tracking.tracked_objects
                         if o.class_name == "person"]
        offsets = []
        if person_tracks:
            for p in person_tracks:
                x1, y1, x2, y2 = [int(v) for v in p.bbox]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(fw, x2), min(fh, y2)
                if x2 - x1 < 24 or y2 - y1 < 24:
                    continue  # person crop too small to contain a face
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                offsets.append((x1, y1))
                for f in self._face_detector.detect(crop):
                    raw_dets.append((f, x1, y1))
        else:
            # No tracked persons; single full-frame pass (documented).
            for f in self._face_detector.detect(frame):
                raw_dets.append((f, 0, 0))

        if not raw_dets:
            return []

        # Convert crop-local pixel coords to full-frame pixel coords.
        for f, ox, oy in raw_dets:
            x1, y1, x2, y2 = f.bbox
            f.bbox = (x1 + ox, y1 + oy, x2 + ox, y2 + oy)
            if f.landmarks:
                f.landmarks = [(lx + ox, ly + oy) for (lx, ly) in f.landmarks]
            faces.append(f)

        # Associate with person tracks (person class only; never forced).
        now = datetime.now(timezone.utc).isoformat()
        payload = associate_faces_with_persons(
            faces, tracking.tracked_objects, fw, fh,
            min_overlap=settings.FACE_PERSON_OVERLAP_THRESHOLD)
        for d in payload:
            d["timestamp"] = now
        return payload

    def _run_anpr(self, tracking, frame):
        """Run ANPR on tracked vehicles."""
        results = []
        fh, fw = frame.shape[:2]
        for obj in tracking.tracked_objects:
            if obj.class_name not in settings.ANPR_VEHICLE_CLASSES:
                continue
            tid = obj.track_id
            # Check throttling
            if not self._temporal.should_ocr(self.camera_id, tid, tracking.frame_index):
                # Still update vehicle state
                x1, y1, x2, y2 = obj.bbox
                self._temporal.update_vehicle_state(
                    self.camera_id, tid, obj.class_name,
                    {"x1": round(x1/fw, 4), "y1": round(y1/fh, 4),
                     "x2": round(x2/fw, 4), "y2": round(y2/fh, 4)})
                continue
            # Extract vehicle ROI
            x1, y1, x2, y2 = [int(v) for v in obj.bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(fw, x2), min(fh, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            vehicle_roi = frame[y1:y2, x1:x2]
            if vehicle_roi.size == 0:
                continue
            # Detect plate
            plate_cands = self._plate_detector.detect_plates(vehicle_roi)
            plate_text = None
            ocr_conf = 0.0
            plate_conf = 0.0
            ocr_candidates = []
            plate_bbox = None
            if plate_cands:
                best = plate_cands[0]
                plate_conf = best.confidence
                if plate_conf >= settings.ANPR_MIN_PLATE_CONFIDENCE:
                    crop = self._plate_detector.extract_plate_crop(vehicle_roi, best)
                    if crop is not None:
                        processed = self._plate_detector.preprocess_for_ocr(crop)
                        # Multi-candidate OCR preserves every reading so the
                        # temporal stabilizer can prefer cross-frame consensus.
                        ocr_candidates = self._ocr_engine.read_text_multi(processed)
                        if ocr_candidates:
                            best_c = ocr_candidates[0]
                            plate_text = best_c.get("normalized")
                            ocr_conf = best_c.get("confidence", 0.0)
                        else:
                            plate_text, ocr_conf = self._ocr_engine.read_text(processed)
                        x1c, y1c, x2c, y2c = best.bbox
                        plate_bbox = {
                            "x1": round((x1 + x1c) / fw, 4),
                            "y1": round((y1 + y1c) / fh, 4),
                            "x2": round((x1 + x2c) / fw, 4),
                            "y2": round((y1 + y2c) / fh, 4),
                        }
            # Temporal stabilization
            result = self._temporal.add_observation(
                self.camera_id, tid, obj.class_name,
                {"x1": round(x1/fw, 4), "y1": round(y1/fh, 4),
                 "x2": round(x2/fw, 4), "y2": round(y2/fh, 4)},
                plate_text, ocr_conf, plate_conf, tracking.frame_index,
                candidates=ocr_candidates or None,
                plate_bbox=plate_bbox)
            results.append(result)
        return results

    def _draw_detections(self, frame, tracking):
        vis = frame.copy()
        for obj in tracking.tracked_objects:
            x1, y1, x2, y2 = [int(v) for v in obj.bbox]
            color = (0, 0, 255) if obj.class_name == 'person' else (0, 200, 160)
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            label = 'ID:%d %s %.0f%%' % (obj.track_id, obj.class_name.upper(), obj.confidence * 100)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(vis, (x1, y1 - th - 6), (x1 + tw + 2, y1), color, -1)
            cv2.putText(vis, label, (x1 + 1, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        status = '%s | %d tracks | %.1f fps' % (
            self.camera_id, tracking.active_tracks, self.state.processing_fps)
        cv2.putText(vis, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
        return vis
