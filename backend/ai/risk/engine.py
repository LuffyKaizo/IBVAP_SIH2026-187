"""RiskEngine — deterministic risk scoring using configurable weights.

Produces a 0-100 risk score and severity mapping from event type,
zone severity, contextual factors, and environmental conditions.
No ML models, no network calls.
"""

from dataclasses import dataclass, field
from typing import Optional

from ai.config import settings


SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass
class RiskAssessment:
    """Result of a risk assessment for a single event."""
    risk_score: int           # 0-100
    severity: str             # LOW | MEDIUM | HIGH | CRITICAL
    risk_factors: list[dict] = field(default_factory=list)  # [{"factor": ..., "points": ...}]


class RiskEngine:
    """Deterministic risk scoring engine."""

    def assess(self, event: dict, track_context=None, is_night: bool = False) -> RiskAssessment:
        """Score an event based on its type, context, and environment.

        Args:
            event: Event dict with at least event_type, severity, confidence
            track_context: Optional TrackContext from ContextEngine
            is_night: Whether current time is night hours

        Returns:
            RiskAssessment with clamped 0-100 score, severity, and factor breakdown
        """
        factors = []
        score = 0

        # 1. Base event type weight
        event_type = event.get("event_type", "")
        if event_type == "PERSON_INTRUSION":
            pts = settings.RISK_WEIGHT_PERSON_INTRUSION
            score += pts
            factors.append({"factor": "Person Intrusion", "points": pts})
        elif event_type == "VEHICLE_INTRUSION":
            pts = settings.RISK_WEIGHT_VEHICLE_INTRUSION
            score += pts
            factors.append({"factor": "Vehicle Intrusion", "points": pts})

        # 2. Zone severity
        zone_severity = "HIGH"
        if track_context:
            zone_severity = track_context.zone_severity
        else:
            zone_severity = event.get("severity", "HIGH")

        if zone_severity == "CRITICAL":
            pts = settings.RISK_WEIGHT_ZONE_SEVERITY_CRITICAL
            score += pts
            factors.append({"factor": "Restricted Zone (Critical)", "points": pts})
        elif zone_severity == "HIGH":
            pts = settings.RISK_WEIGHT_ZONE_SEVERITY_HIGH
            score += pts
            factors.append({"factor": "Restricted Zone (High)", "points": pts})

        # 3. Contextual factors (only if track_context available)
        if track_context:
            if track_context.loitering:
                pts = settings.RISK_WEIGHT_LOITERING
                score += pts
                factors.append({"factor": "Loitering", "points": pts})
            if track_context.dwell_seconds >= settings.CONTEXT_DWELL_THRESHOLD_SEC:
                pts = settings.RISK_WEIGHT_DWELL
                score += pts
                factors.append({"factor": f"Dwell ({track_context.dwell_seconds:.0f}s)", "points": pts})
            if track_context.fence_proximity:
                pts = settings.RISK_WEIGHT_FENCE_PROXIMITY
                score += pts
                factors.append({"factor": "Fence Proximity", "points": pts})
            if track_context.repeated_entry:
                pts = settings.RISK_WEIGHT_REPEATED_ENTRY
                score += pts
                factors.append({"factor": f"Repeated Entry ({track_context.entry_count}x)", "points": pts})

        # 4. Time of day
        if is_night:
            pts = settings.RISK_WEIGHT_NIGHT_ACTIVITY
            score += pts
            factors.append({"factor": "Night Activity", "points": pts})

        # 5. High confidence bonus
        conf = event.get("confidence", 0)
        if conf >= 0.85:
            pts = settings.RISK_WEIGHT_HIGH_CONFIDENCE
            score += pts
            factors.append({"factor": "High Confidence", "points": pts})

        # Clamp 0-100
        score = max(0, min(100, score))

        # Severity mapping
        if score >= settings.RISK_THRESHOLD_CRITICAL:
            severity = "CRITICAL"
        elif score >= settings.RISK_THRESHOLD_HIGH:
            severity = "HIGH"
        elif score >= settings.RISK_THRESHOLD_MEDIUM:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        return RiskAssessment(
            risk_score=score,
            severity=severity,
            risk_factors=factors,
        )

    @staticmethod
    def effective_severity(base_severity: str, risk_severity: str) -> str:
        """Return the higher of base and risk severity."""
        base_order = SEVERITY_ORDER.get(base_severity, 1)
        risk_order = SEVERITY_ORDER.get(risk_severity, 1)
        if risk_order > base_order:
            return risk_severity
        return base_severity
