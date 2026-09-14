# Context Intelligence & Risk Scoring

Border-context-aware intelligence layer on top of the existing IBVAP AI pipeline.

## Architecture

```
Video → YOLO → ByteTrack → ContextEngine → EventEngine + BehaviorEngine → RiskEngine → set_events() → Evidence → SHA-256 → Blockchain
```

ContextEngine and BehaviorEngine run **in parallel**. Both feed into RiskEngine, which produces the final severity.

---

## ContextEngine

**Module:** `backend/ai/context/engine.py`

Analyzes per-track temporal behavior to produce contextual signals. Rule-based, no ML, no network calls, no DB queries.

### Features

| Feature | Condition | Config Key |
|---|---|---|
| Dwell Time | Time in frames (seconds) since first seen | `CONTEXT_DWELL_THRESHOLD_SEC=10.0` |
| Loitering | Dwell > threshold AND center stays within radius | `CONTEXT_LOITERING_THRESHOLD_SEC=30.0` |
| Fence Proximity | Center within distance of zone polygon edges | `CONTEXT_FENCE_PROXIMITY_DISTANCE=0.10` |
| Direction | Frame displacement normalized to camera frame | `CONTEXT_DIRECTION_MIN_FRAMES=3` |
| Repeated Entry | Same track_id seen > N times in window | `CONTEXT_REPEATED_ENTRY_COUNT=3` |

### Outputs

- `list[TrackContext]` — per-track context (dwell_seconds, loitering, fence_proximity, direction, repeated_entry)
- `list[dict]` — context events (loitering, fence_proximity) merged into main event pipeline

---

## RiskEngine

**Module:** `backend/ai/risk/engine.py`

Deterministic score 0–100. No randomness.

### Scoring

| Factor | Source | Weight |
|---|---|---|
| Person detected | class_name | 30 |
| Vehicle detected | class_name | 40 |
| Zone is critical | zone.severity | 25 |
| Zone is high | zone.severity | 15 |
| Loitering | context | 20 |
| Dwell > 10s | context | 15 |
| Near fence | context | 15 |
| Repeated entry | context | 20 |
| Night time | hour < 6 or > 21 | 10 |
| Low confidence | confidence < 0.5 | 5 |

### Severity Thresholds

| Level | Score Range |
|---|---|
| LOW | < 25 |
| MEDIUM | 25–49 |
| HIGH | 50–74 |
| CRITICAL | ≥ 75 |

Config: `RISK_WEIGHT_*` and `RISK_THRESHOLD_*` in `backend/ai/config.py`.

---

## Deduplication & Escalation

**In:** `PipelineState.set_events()` (backend/ai/pipeline.py)

### Logic per event per track

1. **CREATE** — first occurrence (within 300s window): new alert, evidence captured
2. **ESCALATE** — same dedup key but higher severity: updates severity+metadata, captures evidence
3. **UPDATE** — same dedup key, same or lower severity: metadata only, no duplicate alert

### Dedup key

```
f"{camera_id}:{track_id}:{event_type}"
```

Active window: `ALERT_ACTIVE_WINDOW_SEC=300` (5 minutes).

---

## Event Metadata Enrichment

Every `SecurityEvent` emitted by `set_events()` includes:

```
riskScore, riskSeverity, riskFactors, dwellSeconds, loitering, fenceProximity, direction, repeatedEntry
```

This metadata flows to:
- Frontend `AiAlert` / `BorderAlert` types (optional fields)
- Evidence blob (provenance)
- Blockchain ledger (immutable record)

---

## Frontend Display

### Event Intelligence View (`EventIntelligenceView.tsx`)

Risk Assessment panel shown in alert dossier when `riskScore > 0`:
- Severity badge (color-coded: CRITICAL=red, HIGH=amber, MEDIUM=gray)
- Factor breakdown with point values
- Context tags: direction, dwell time, loitering, fence proximity, repeated entry

### Bounding Box Overlay (`AIBoundingBoxOverlay.tsx`)

Per-track context sublabel above bbox:
- Loitering (orange), Near Fence (red), direction label, dwell duration

---

## Configuration

All constants in `backend/ai/config.py`:

```python
# Context
CONTEXT_DWELL_THRESHOLD_SEC = 10.0
CONTEXT_LOITERING_THRESHOLD_SEC = 30.0
CONTEXT_LOITERING_RADIUS = 0.05
CONTEXT_FENCE_PROXIMITY_DISTANCE = 0.10
CONTEXT_REPEATED_ENTRY_COUNT = 3
CONTEXT_REPEATED_ENTRY_WINDOW_SEC = 300.0
CONTEXT_DIRECTION_MIN_FRAMES = 3

# Risk
RISK_WEIGHT_PERSON = 30
RISK_WEIGHT_VEHICLE = 40
RISK_WEIGHT_ZONE_CRITICAL = 25
RISK_WEIGHT_ZONE_HIGH = 15
RISK_WEIGHT_LOITERING = 20
RISK_WEIGHT_DWELL = 15
RISK_WEIGHT_FENCE = 15
RISK_WEIGHT_REPEATED_ENTRY = 20
RISK_WEIGHT_NIGHT = 10
RISK_WEIGHT_LOW_CONFIDENCE = 5

RISK_THRESHOLD_MEDIUM = 25
RISK_THRESHOLD_HIGH = 50
RISK_THRESHOLD_CRITICAL = 75

# Dedup
ALERT_ACTIVE_WINDOW_SEC = 300
```

Override via environment variables before starting the AI server.

---

## Tests

26 deterministic unit tests in `backend/ai/tests/test_context_risk.py`:

- TrackContext dataclass, direction computation, point-to-polygon distance
- Per-track state management, temporal analysis (dwell, loitering, repeated entry)
- Fence proximity, stale track cleanup
- RiskEngine scoring, severity thresholds, event-to-risk mapping
- Combined context + risk pipeline integration

All 26 pass. Zero external dependencies.
