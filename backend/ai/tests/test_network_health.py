"""Section 13 Network Health Tests.

28 tests covering:
1-13: State machine transitions
14-17: Latency tracking / metrics
18-21: Sync integration
22-25: API / RBAC
26-28: Resilience / independence
"""

import asyncio
import collections
import os
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from ai.network.health import NetworkHealthManager
from ai.network.models import NetworkState, HealthMetrics
from ai.sync.client import CentralSyncClient, SyncResult


# ──────────────────────────────────────────────────────────────
# Mocks
# ──────────────────────────────────────────────────────────────

class MockCentralClient:
    def __init__(self, available=True):
        self._available = available

    async def health_check(self):
        if not self._available:
            raise ConnectionError("connection refused")
        await asyncio.sleep(0.001)
        return True


class MockSyncManager:
    def __init__(self):
        self._connectivity = "OFFLINE"


class MockAuditRepo:
    def __init__(self):
        self.logs = []

    async def log(self, action, entity_type, entity_id, details=None, actor=None):
        self.logs.append({
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
            "actor": actor,
        })


def _make_manager(available=True, failure_threshold=3, recovery_threshold=2,
                  degraded_latency=1000, window_size=20):
    client = MockCentralClient(available=available)
    sync_mgr = MockSyncManager()
    audit = MockAuditRepo()

    mgr = NetworkHealthManager(
        central_client=client,
        sync_manager=sync_mgr,
        audit_repo=audit,
    )
    mgr._window_size = window_size
    mgr._latencies = collections.deque(maxlen=window_size)

    patcher = patch("ai.network.health.settings")
    mock_settings = patcher.start()
    mock_settings.NETWORK_HEALTH_ENABLED = True
    mock_settings.NETWORK_HEALTH_INTERVAL_SEC = 1
    mock_settings.NETWORK_HEALTH_TIMEOUT_SEC = 5
    mock_settings.NETWORK_DEGRADED_LATENCY_MS = degraded_latency
    mock_settings.NETWORK_FAILURE_THRESHOLD = failure_threshold
    mock_settings.NETWORK_RECOVERY_THRESHOLD = recovery_threshold
    mock_settings.NETWORK_HEALTH_WINDOW_SIZE = window_size
    mgr._patcher = patcher

    return mgr, client, sync_mgr, audit


def _run(coro):
    """Run a coroutine with a fresh event loop (Windows-safe)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _connect(mgr, recovery_threshold=2):
    """Helper: bring manager from OFFLINE to CONNECTED."""
    _run(mgr.check())  # → RECOVERING
    for _ in range(recovery_threshold):
        _run(mgr.check())


# ──────────────────────────────────────────────────────────────
# State Machine (1-13)
# ──────────────────────────────────────────────────────────────

class TestStateMachine(unittest.TestCase):

    def test_01_initial_state(self):
        mgr, *_ = _make_manager()
        self.assertEqual(mgr.state, NetworkState.OFFLINE)

    def test_02_first_success_goes_recovering(self):
        mgr, *_ = _make_manager(available=True)
        result = _run(mgr.check())
        self.assertTrue(result.reachable)
        self.assertEqual(mgr.state, NetworkState.RECOVERING)

    def test_03_recovery_threshold_connects(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr, 2)
        self.assertEqual(mgr.state, NetworkState.CONNECTED)

    def test_04_single_failure_stays_connected(self):
        mgr, *_ = _make_manager(available=True, failure_threshold=3, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.CONNECTED)
        self.assertEqual(mgr._consecutive_failures, 1)

    def test_05_three_failures_to_degraded(self):
        mgr, *_ = _make_manager(available=True, failure_threshold=3, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        for _ in range(3):
            _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.DEGRADED)

    def test_06_degraded_one_success_still_degraded(self):
        mgr, *_ = _make_manager(available=True, failure_threshold=3, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        for _ in range(3):
            _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.DEGRADED)
        mgr._client._available = True
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.DEGRADED)
        self.assertEqual(mgr._consecutive_successes, 1)

    def test_07_degraded_fourth_failure_goes_offline(self):
        mgr, *_ = _make_manager(available=True, failure_threshold=3, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        for _ in range(3):
            _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.DEGRADED)
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.OFFLINE)

    def test_08_offline_stays_offline(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.OFFLINE)

    def test_09_offline_success_goes_recovering(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        mgr._client._available = True
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.RECOVERING)

    def test_10_recovering_second_success_connects(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        mgr._client._available = True
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.RECOVERING)
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.CONNECTED)

    def test_11_recovery_needs_n_successes(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=3)
        _connect(mgr, 3)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        mgr._client._available = True
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.RECOVERING)
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.RECOVERING)
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.CONNECTED)

    def test_12_recovering_failure_goes_offline(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        mgr._client._available = True
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.RECOVERING)
        mgr._client._available = False
        _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.OFFLINE)

    def test_13_success_resets_failure_count(self):
        mgr, *_ = _make_manager(available=True, failure_threshold=3, recovery_threshold=2)
        _connect(mgr)
        mgr._client._available = False
        _run(mgr.check())
        self.assertEqual(mgr._consecutive_failures, 1)
        mgr._client._available = True
        _run(mgr.check())
        self.assertEqual(mgr._consecutive_failures, 0)
        self.assertEqual(mgr.state, NetworkState.CONNECTED)


# ──────────────────────────────────────────────────────────────
# Latency / Metrics (14-17)
# ──────────────────────────────────────────────────────────────

class TestLatencyMetrics(unittest.TestCase):

    def test_14_latency_tracked_on_success(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr)
        _run(mgr.check())
        self.assertGreater(len(mgr._latencies), 0)

    def test_15_rolling_average_positive(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr)
        for _ in range(5):
            _run(mgr.check())
        metrics = mgr.get_metrics()
        self.assertGreater(metrics.average_latency_ms, 0)

    def test_16_window_bounded(self):
        mgr, *_ = _make_manager(available=True, window_size=5, recovery_threshold=2)
        _connect(mgr, 2)
        for _ in range(10):
            _run(mgr.check())
        self.assertLessEqual(len(mgr._latencies), 5)

    def test_17_high_latency_triggers_degraded(self):
        mgr, *_ = _make_manager(available=True, failure_threshold=3,
                               degraded_latency=1000, recovery_threshold=2)
        _connect(mgr, 2)
        self.assertEqual(mgr.state, NetworkState.CONNECTED)

        for _ in range(3):
            mgr._update_state(reachable=True, latency_ms=1500.0)

        self.assertEqual(mgr.state, NetworkState.DEGRADED)


# ──────────────────────────────────────────────────────────────
# Sync Integration (18-21)
# ──────────────────────────────────────────────────────────────

class TestSyncIntegration(unittest.TestCase):

    def test_18_connectivity_propagates_to_sync(self):
        mgr, _, sync_mgr, _ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr, 2)
        self.assertEqual(sync_mgr._connectivity, "CONNECTED")

    def test_19_offline_sets_sync_offline(self):
        mgr, _, sync_mgr, _ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr, 2)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.OFFLINE)
        self.assertEqual(sync_mgr._connectivity, "OFFLINE")

    def test_20_recovery_updates_sync_manager(self):
        mgr, _, sync_mgr, _ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr, 2)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        mgr._client._available = True
        _run(mgr.check())
        self.assertEqual(sync_mgr._connectivity, "RECOVERING")
        _run(mgr.check())
        self.assertEqual(sync_mgr._connectivity, "CONNECTED")

    def test_21_checks_performed_tracked(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr, 2)
        for _ in range(5):
            _run(mgr.check())
        metrics = mgr.get_metrics()
        self.assertEqual(metrics.checks_performed, 8)  # 2 connect + 5 extra


# ──────────────────────────────────────────────────────────────
# API / RBAC (22-25)
# ──────────────────────────────────────────────────────────────

class TestApiRbac(unittest.TestCase):

    def test_22_sync_read_all_roles(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        for role in [Role.ADMIN, Role.OPERATOR, Role.VIEWER]:
            self.assertIn(Permission.SYNC_READ, ROLE_PERMISSIONS[role])

    def test_23_sync_control_admin_operator_only(self):
        from ai.auth.models import Permission, ROLE_PERMISSIONS, Role
        self.assertIn(Permission.SYNC_CONTROL, ROLE_PERMISSIONS[Role.ADMIN])
        self.assertIn(Permission.SYNC_CONTROL, ROLE_PERMISSIONS[Role.OPERATOR])
        self.assertNotIn(Permission.SYNC_CONTROL, ROLE_PERMISSIONS[Role.VIEWER])

    def test_24_network_state_enum(self):
        from ai.network.models import NetworkState
        self.assertEqual(NetworkState.CONNECTED.value, "CONNECTED")
        self.assertEqual(NetworkState.DEGRADED.value, "DEGRADED")
        self.assertEqual(NetworkState.OFFLINE.value, "OFFLINE")
        self.assertEqual(NetworkState.RECOVERING.value, "RECOVERING")

    def test_25_health_check_result_fields(self):
        from ai.network.models import HealthCheckResult
        result = HealthCheckResult(reachable=True, latency_ms=42.5, timestamp="2026-09-06T12:00:00Z")
        self.assertTrue(result.reachable)
        self.assertEqual(result.latency_ms, 42.5)
        self.assertIsNone(result.error)


# ──────────────────────────────────────────────────────────────
# Resilience / Independence (26-28)
# ──────────────────────────────────────────────────────────────

class TestResilience(unittest.TestCase):

    def test_26_worker_start_stop(self):
        mgr, *_ = _make_manager(available=True)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(mgr.start())
            self.assertTrue(mgr._running)
            loop.run_until_complete(mgr.stop())
            self.assertFalse(mgr._running)
            self.assertIsNone(mgr._task)
        finally:
            loop.close()

    def test_27_ai_independence(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr, 2)
        self.assertEqual(mgr.state, NetworkState.CONNECTED)
        mgr._client._available = False
        for _ in range(10):
            _run(mgr.check())
        self.assertEqual(mgr.state, NetworkState.OFFLINE)
        metrics = mgr.get_metrics()
        self.assertFalse(metrics.central_reachable)
        self.assertIsNotNone(metrics)

    def test_28_no_secrets_in_metrics(self):
        mgr, *_ = _make_manager(available=True, recovery_threshold=2)
        _connect(mgr, 2)
        metrics = mgr.get_metrics()
        for value in [metrics.state, metrics.latency_ms, metrics.checks_performed]:
            s = str(value).lower()
            self.assertNotIn("password", s)
            self.assertNotIn("secret", s)
            self.assertNotIn("bearer", s)
            self.assertNotIn("database_url", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
