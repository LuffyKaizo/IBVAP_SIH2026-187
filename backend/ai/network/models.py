"""Network health data models for Section 13."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class NetworkState(str, Enum):
    """Network connectivity state between Edge AI and Central IBVAP."""
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    RECOVERING = "RECOVERING"


@dataclass
class HealthCheckResult:
    """Result of a single central health check."""
    reachable: bool
    latency_ms: float
    timestamp: str
    error: Optional[str] = None


@dataclass
class HealthMetrics:
    """Current network health metrics."""
    state: str
    central_reachable: bool
    latency_ms: float
    average_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    consecutive_failures: int
    consecutive_successes: int
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    offline_since: Optional[str] = None
    recovery_started_at: Optional[str] = None
    checks_performed: int = 0
