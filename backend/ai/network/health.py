"""NetworkHealthManager — state machine for edge-to-central connectivity.

Tracks connectivity state (CONNECTED/DEGRADED/OFFLINE/RECOVERING) with
hysteresis to prevent flapping. Measures latency with a bounded rolling
window. Drives SyncManager's connectivity state.

Central connectivity failure does NOT stop Edge AI processing.
"""

import asyncio
import collections
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from ai.config import settings
from ai.network.models import NetworkState, HealthCheckResult, HealthMetrics
from ai.sync.client import CentralSyncClient

logger = logging.getLogger("ibvap.network")


class NetworkHealthManager:
    """Monitors network health between Edge AI and Central IBVAP server.

    Uses the existing CentralSyncClient for health checks. Maintains a
    state machine with hysteresis thresholds to prevent state flapping.
    Observes latency with a bounded rolling window.
    """

    def __init__(
        self,
        central_client: CentralSyncClient,
        sync_manager=None,
        audit_repo=None,
    ):
        self._client = central_client
        self._sync_manager = sync_manager
        self._audit_repo = audit_repo

        # State machine
        self._state = NetworkState.OFFLINE
        self._consecutive_failures = 0
        self._consecutive_successes = 0

        # Timestamps
        self._last_success_at: Optional[str] = None
        self._last_failure_at: Optional[str] = None
        self._offline_since: Optional[str] = None
        self._recovery_started_at: Optional[str] = None

        # Latency tracking (bounded rolling window)
        self._window_size = settings.NETWORK_HEALTH_WINDOW_SIZE
        self._latencies: collections.deque = collections.deque(maxlen=self._window_size)
        self._current_latency_ms: float = 0.0
        self._checks_performed: int = 0

        # Background worker
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def state(self) -> NetworkState:
        return self._state

    async def start(self):
        """Start the background health check loop."""
        if not settings.NETWORK_HEALTH_ENABLED:
            print("[NETWORK] Network health monitoring disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        print("[NETWORK] Health monitor started (interval=%ds, failure_threshold=%d, recovery_threshold=%d)" % (
            settings.NETWORK_HEALTH_INTERVAL_SEC,
            settings.NETWORK_FAILURE_THRESHOLD,
            settings.NETWORK_RECOVERY_THRESHOLD,
        ))

    async def stop(self):
        """Stop the background health check loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        print("[NETWORK] Health monitor stopped")

    async def _run_loop(self):
        """Background loop: perform periodic health checks."""
        while self._running:
            try:
                await self.check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[NETWORK] Health check iteration failed: %s", e)

            try:
                await asyncio.sleep(settings.NETWORK_HEALTH_INTERVAL_SEC)
            except asyncio.CancelledError:
                break

    async def check(self) -> HealthCheckResult:
        """Perform a single health check and update state machine.

        Returns the check result for immediate inspection.
        """
        start_time = time.time()
        reachable = False
        latency_ms = 0.0
        error = None

        try:
            # Use the existing CentralSyncClient health check with timing
            ok = await asyncio.wait_for(
                self._client.health_check(),
                timeout=settings.NETWORK_HEALTH_TIMEOUT_SEC,
            )
            reachable = ok
            latency_ms = (time.time() - start_time) * 1000

            if not ok:
                error = "health_check_returned_false"

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            error = "timeout"
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            error = type(e).__name__

        self._checks_performed += 1
        now = datetime.now(timezone.utc).isoformat()

        # Record result
        if reachable:
            self._last_success_at = now
            self._consecutive_successes += 1
            self._consecutive_failures = 0
        else:
            self._last_failure_at = now
            self._consecutive_failures += 1
            self._consecutive_successes = 0

        # Record latency (only on successful checks for accurate metrics)
        if reachable and latency_ms > 0:
            self._current_latency_ms = latency_ms
            self._latencies.append(latency_ms)

        # Update state machine
        old_state = self._state
        self._update_state(reachable, latency_ms)

        # Log meaningful state transitions
        if self._state != old_state:
            await self._log_transition(old_state, self._state, latency_ms)

        # Update SyncManager connectivity
        if self._sync_manager:
            self._sync_manager._connectivity = self._state.value

        return HealthCheckResult(
            reachable=reachable,
            latency_ms=round(latency_ms, 2),
            timestamp=now,
            error=error,
        )

    def _update_state(self, reachable: bool, latency_ms: float):
        """Update network state machine with hysteresis.

        State transitions:
            CONNECTED:
                success → stay CONNECTED
                failure (count < threshold) → stay CONNECTED
                failure (count >= threshold) → DEGRADED
            DEGRADED:
                success (count >= recovery_threshold) → CONNECTED
                failure → OFFLINE
            OFFLINE:
                success → RECOVERING
                failure → stay OFFLINE
            RECOVERING:
                success (count >= recovery_threshold) → CONNECTED
                failure → OFFLINE
        """
        if self._state == NetworkState.CONNECTED:
            if reachable:
                # Check if high latency should trigger DEGRADED
                if latency_ms > settings.NETWORK_DEGRADED_LATENCY_MS:
                    self._consecutive_failures += 1
                    self._consecutive_successes = 0
                    if self._consecutive_failures >= settings.NETWORK_FAILURE_THRESHOLD:
                        self._state = NetworkState.DEGRADED
                # else: stay CONNECTED
            else:
                if self._consecutive_failures >= settings.NETWORK_FAILURE_THRESHOLD:
                    self._state = NetworkState.DEGRADED

        elif self._state == NetworkState.DEGRADED:
            if reachable:
                if self._consecutive_successes >= settings.NETWORK_RECOVERY_THRESHOLD:
                    self._state = NetworkState.CONNECTED
                    self._consecutive_failures = 0
            else:
                # Failure in DEGRADED → OFFLINE
                self._state = NetworkState.OFFLINE
                self._offline_since = datetime.now(timezone.utc).isoformat()

        elif self._state == NetworkState.OFFLINE:
            if reachable:
                self._state = NetworkState.RECOVERING
                self._recovery_started_at = datetime.now(timezone.utc).isoformat()
                self._consecutive_successes = 1
            # else: stay OFFLINE

        elif self._state == NetworkState.RECOVERING:
            if reachable:
                if self._consecutive_successes >= settings.NETWORK_RECOVERY_THRESHOLD:
                    self._state = NetworkState.CONNECTED
                    self._consecutive_failures = 0
                    self._recovery_started_at = None
                    self._offline_since = None
            else:
                # Failure during recovery → back to OFFLINE
                self._state = NetworkState.OFFLINE
                self._offline_since = datetime.now(timezone.utc).isoformat()
                self._recovery_started_at = None

    async def _log_transition(self, old_state: NetworkState, new_state: NetworkState, latency_ms: float):
        """Log state transitions and audit significant changes."""
        msg = "[NETWORK] State: %s -> %s (latency=%.1fms)" % (
            old_state.value, new_state.value, latency_ms
        )
        print(msg)

        # Audit log significant transitions
        if self._audit_repo:
            try:
                await self._audit_repo.log(
                    action="network.state_changed",
                    entity_type="network",
                    entity_id="central_link",
                    details={
                        "from_state": old_state.value,
                        "to_state": new_state.value,
                        "latency_ms": round(latency_ms, 2),
                    },
                    actor="NETWORK_HEALTH",
                )
            except Exception:
                pass

    def get_metrics(self) -> HealthMetrics:
        """Return current network health metrics."""
        latencies = list(self._latencies)
        return HealthMetrics(
            state=self._state.value,
            central_reachable=self._state in (NetworkState.CONNECTED, NetworkState.RECOVERING),
            latency_ms=round(self._current_latency_ms, 2),
            average_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            min_latency_ms=round(min(latencies), 2) if latencies else 0.0,
            max_latency_ms=round(max(latencies), 2) if latencies else 0.0,
            consecutive_failures=self._consecutive_failures,
            consecutive_successes=self._consecutive_successes,
            last_success_at=self._last_success_at,
            last_failure_at=self._last_failure_at,
            offline_since=self._offline_since,
            recovery_started_at=self._recovery_started_at,
            checks_performed=self._checks_performed,
        )
