"""Temporal OCR stabilization for ANPR.

Maintains per-track OCR observation history and produces stable plate text
using a simple voting/consensus mechanism.

Preserves the original architecture:
- per-track observation history (bounded window)
- OCR throttling per track
- majority voting with confidence tie-breaking
- stale-track cleanup and deduplication

Additions:
- raw + normalized text preserved per observation (traceability)
- per-track stable record id (no churn per frame)
- conservative position-constrained correction of the *stabilized winner*
  (plate_format.contextual_correct) — the raw reading is never overwritten;
  correction is flagged so the UI can show it as inferred.
"""

import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime, timezone

from ai.config import settings
from ai.anpr.ocr_engine import OCREngine
from ai.anpr.plate_format import contextual_correct, format_status


@dataclass
class OCRObservation:
    """A single OCR reading for a vehicle track."""
    text: str                 # normalized reading used for consensus
    confidence: float
    frame_index: int
    raw_text: Optional[str] = None   # raw OCR text as returned by engine
    variant: str = "primary"         # which OCR pass produced it


@dataclass
class VehicleANPRState:
    """State for one tracked vehicle's ANPR processing."""
    track_id: int
    camera_id: str
    vehicle_class: str
    vehicle_bbox: dict
    plate_bbox: Optional[dict] = None
    observations: deque = field(default_factory=deque)
    last_ocr_frame: int = -1000
    confirmed_plate: Optional[str] = None
    confirmed_confidence: float = 0.0
    status: str = "DETECTED"  # DETECTED | RECOGNIZED | CONFIRMED | UNREADABLE
    record_id: str = field(default_factory=lambda: "ANPR-" + str(uuid.uuid4())[:8])
    # Traceability / correction bookkeeping
    raw_ocr_text: Optional[str] = None
    corrected: bool = False
    format_status: Optional[str] = None
    correction_note: Optional[str] = None
    observation_count: int = 0


class TemporalStabilizer:
    """Maintains per-track OCR observations and produces stable plate text.

    Uses a simple voting mechanism:
    - Keep a bounded window of recent OCR observations per track
    - The most frequently observed text wins (with confidence as tiebreaker)
    - Repeated observations increase confidence
    """

    def __init__(self):
        self._states: Dict[str, VehicleANPRState] = {}
        self._window = settings.ANPR_TEMPORAL_WINDOW
        self._min_confidence = settings.ANPR_MIN_OCR_CONFIDENCE

    def _key(self, camera_id: str, track_id: int) -> str:
        return "%s:%d" % (camera_id, track_id)

    def should_ocr(self, camera_id: str, track_id: int, frame_index: int) -> bool:
        """Determine if OCR should be attempted for this track on this frame.

        Throttles OCR to once every N frames per track.
        """
        key = self._key(camera_id, track_id)
        state = self._states.get(key)
        if state is None:
            return True
        return (frame_index - state.last_ocr_frame) >= settings.ANPR_OCR_INTERVAL_FRAMES

    def add_observation(self, camera_id: str, track_id: int, vehicle_class: str,
                        vehicle_bbox: dict, plate_text: Optional[str],
                        ocr_confidence: float, plate_confidence: float,
                        frame_index: int, candidates: Optional[list] = None,
                        plate_bbox: Optional[dict] = None) -> dict:
        """Add an OCR observation and return the current ANPR result.

        `candidates` (optional) is the multi-candidate output of the OCR
        engine (list of {raw, normalized, confidence, variant}). When given,
        the best candidate becomes the frame observation and all candidates
        are kept for traceability. When None, plate_text/ocr_confidence are
        used as a single candidate (backwards compatible).

        Returns a dict with ANPR result fields (always JSON-serializable).
        """
        key = self._key(camera_id, track_id)
        now = datetime.now(timezone.utc).isoformat()

        if key not in self._states:
            self._states[key] = VehicleANPRState(
                track_id=track_id,
                camera_id=camera_id,
                vehicle_class=vehicle_class,
                vehicle_bbox=vehicle_bbox,
            )

        state = self._states[key]
        state.last_ocr_frame = frame_index
        state.vehicle_bbox = vehicle_bbox
        if plate_bbox is not None:
            state.plate_bbox = plate_bbox

        # Select this frame's reading.
        if candidates:
            best = candidates[0]  # already confidence-ranked
            best_text = best.get("normalized")
            best_conf = best.get("confidence", 0.0)
            raw_text = best.get("raw")
            variant = best.get("variant", "primary")
        else:
            best_text = plate_text
            best_conf = ocr_confidence
            raw_text = plate_text
            variant = "primary"

        # Normalize text and validate before accepting.
        normalized = OCREngine.normalize_plate_text(best_text) if best_text else None

        # Add observation if we have valid normalized text at min confidence.
        if normalized and best_conf >= self._min_confidence:
            state.observations.append(OCRObservation(
                text=normalized,
                confidence=best_conf,
                frame_index=frame_index,
                raw_text=raw_text,
                variant=variant,
            ))
            # Keep bounded
            while len(state.observations) > self._window:
                state.observations.popleft()

            state.status = "RECOGNIZED"
        elif normalized:
            # Valid text but low confidence — note it but don't add to consensus.
            state.status = "RECOGNIZED"
        else:
            state.status = "DETECTED" if not state.confirmed_plate else state.status

        # Run consensus
        self._update_consensus(state)

        return self._make_result(state, plate_confidence, now)

    def update_vehicle_state(self, camera_id: str, track_id: int,
                             vehicle_class: str, vehicle_bbox: dict):
        """Update vehicle bbox/class without OCR (for tracks that have no plate)."""
        key = self._key(camera_id, track_id)
        if key in self._states:
            self._states[key].vehicle_bbox = vehicle_bbox
            self._states[key].vehicle_class = vehicle_class

    def _update_consensus(self, state: VehicleANPRState):
        """Update the confirmed plate text using temporal consensus, then
        apply conservative format correction to the stabilized winner."""
        if len(state.observations) < 1:
            return

        # Count occurrences of each plate text
        text_counts: Dict[str, int] = {}
        text_conf_sum: Dict[str, float] = {}
        for obs in state.observations:
            text_counts[obs.text] = text_counts.get(obs.text, 0) + 1
            text_conf_sum[obs.text] = text_conf_sum.get(obs.text, 0) + obs.confidence

        if not text_counts:
            return

        # Find the most frequent text (count first, avg confidence second).
        best_text = max(text_counts, key=lambda t: (text_counts[t], text_conf_sum[t] / text_counts[t]))
        best_count = text_counts[best_text]
        best_avg_conf = text_conf_sum[best_text] / best_count

        # Require at least 2 observations or high single confidence for confirmation.
        if best_count >= 2 or best_avg_conf >= 0.85:
            state.confirmed_plate = best_text
            state.confirmed_confidence = best_avg_conf
            state.status = "CONFIRMED"
        elif best_count == 1 and best_avg_conf >= self._min_confidence:
            state.confirmed_plate = best_text
            state.confirmed_confidence = best_avg_conf
            state.status = "RECOGNIZED"

        # Record latest consensus reading for traceability, even before confirm.
        if state.confirmed_plate is not None:
            state.observation_count = len(state.observations)
            state.raw_ocr_text = state.confirmed_plate

        # Conservative correction of the stabilized winner only.
        if (state.confirmed_plate is not None
                and settings.ANPR_CONTEXTUAL_CORRECTION
                and state.confirmed_confidence > 0):
            corr = contextual_correct(
                state.confirmed_plate,
                confidence=state.confirmed_confidence,
                min_confidence=settings.ANPR_CONTEXTUAL_MIN_CONFIDENCE,
            )
            if corr.get("changed") and corr.get("corrected"):
                state.confirmed_plate = corr["corrected"]
                state.corrected = True
                state.format_status = corr.get("corrected_status")
                state.correction_note = corr.get("reason")
                # Keep raw reading distinct from the corrected plate.
                state.raw_ocr_text = corr.get("original") or state.raw_ocr_text
            else:
                state.corrected = False
                state.format_status = format_status(state.confirmed_plate)
                state.correction_note = None

    def _make_result(self, state: VehicleANPRState,
                     plate_confidence: float, timestamp: str) -> dict:
        """Create a JSON-serializable ANPR result dict (additive fields)."""
        return {
            "id": state.record_id,
            "trackId": state.track_id,
            "cameraId": state.camera_id,
            "vehicleClass": state.vehicle_class,
            "plateText": state.confirmed_plate,
            "plateConfidence": round(plate_confidence * 100, 1),
            "ocrConfidence": round(state.confirmed_confidence * 100, 1) if state.confirmed_confidence > 0 else None,
            "vehicleBbox": state.vehicle_bbox,
            "plateBbox": state.plate_bbox,
            "status": state.status,
            "timestamp": timestamp,
            "source": "AI",
            # --- traceability / correction fields (additive) ---
            "rawOcrText": state.raw_ocr_text,
            "observationCount": state.observation_count,
            "corrected": state.corrected,
            "formatStatus": state.format_status,
            "correctionNote": state.correction_note,
        }

    def get_active_results(self) -> List[dict]:
        """Get current ANPR results for all active vehicle tracks."""
        results = []
        for key, state in self._states.items():
            now = datetime.now(timezone.utc).isoformat()
            results.append(self._make_result(state, 0.0, now))
        return results

    def remove_track(self, camera_id: str, track_id: int):
        """Remove state for an expired track."""
        key = self._key(camera_id, track_id)
        if key in self._states:
            del self._states[key]

    def cleanup_stale(self, active_track_ids: set, camera_id: str):
        """Remove state for tracks no longer active."""
        to_remove = []
        for key in self._states:
            parts = key.split(":")
            if len(parts) == 2 and parts[0] == camera_id:
                tid = int(parts[1])
                if tid not in active_track_ids:
                    to_remove.append(key)
        for key in to_remove:
            del self._states[key]

    def resolve_all(self):
        """Clear all state — called on pipeline restart."""
        self._states.clear()
