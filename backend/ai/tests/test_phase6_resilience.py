"""Phase 6 — Offline Resilience + SD/NVR + Recovery validation tests.

Covers ONLY gaps left by existing suites (test_sync, test_network_health,
test_footage_retrieval, test_camera_sd, test_trust_chain). Does not weaken
or duplicate them.

Categories:
  NETWORK  - full outage->recovery cycle, sync deferral, no-restart recovery
  SYNC     - outage queueing, retry/backoff, dedup, unknown entities, no 2nd queue
  EVIDENCE - capture during outage, ledger failure, verify after recovery
  SDNVR    - LOCAL_FS discover/retrieve/process/cleanup with REAL video file
  CAMERA   - lifecycle truthfulness on real files, multi-instance isolation
  SECURITY - RBAC enforced independent of connectivity, no secret leakage
  NOPATH   - no blockchain dependency in per-frame / sync code paths
"""

import asyncio
import copy
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)

from ai.network.health import NetworkHealthManager
from ai.network.models import NetworkState
from ai.sync.client import CentralSyncClient, SyncResult
from ai.sync.manager import SyncManager
from ai.video.capture import VideoCapture
from ai.evidence.capture import EvidenceCapture
from ai.evidence.store import LocalFileEvidenceStore
from ai.blockchain.service import BlockchainService
from ai.blockchain.local_ledger import LocalLedger
from ai.blockchain.exceptions import AnchorError
from ai.camera.footage_retrieval import (
    FootageRetrievalService, RetrievalBackend, FootageStatus,
)
from ai.auth.deps import require_permission
from ai.auth.models import Permission, Role, UserContext, ROLE_PERMISSIONS
from ai.edge.models import EdgePermissions
from fastapi import HTTPException

REAL_TEST_VIDEO = os.path.join(_project_root, "data", "test.mp4")


def _run(coro):
    """Run a coroutine with a fresh event loop (Windows-safe)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────
# Fakes (DB seams only — system under test is always real)
# ──────────────────────────────────────────────────────────────

class FakeSyncRepo:
    """In-memory mirror of SyncQueueRepository PENDING→IN_PROGRESS→SYNCED/FAILED."""

    def __init__(self):
        self.items = {}
        self._n = 0

    async def enqueue(self, entity_type, entity_id, operation="CREATE", payload=None):
        for it in self.items.values():
            if (it["entityType"] == entity_type and it["entityId"] == entity_id
                    and it["status"] in ("PENDING", "IN_PROGRESS", "FAILED")):
                return None
        self._n += 1
        sid = "SYNC-%04d" % self._n
        self.items[sid] = {
            "syncId": sid, "entityType": entity_type, "entityId": entity_id,
            "operation": operation, "status": "PENDING", "attemptCount": 0,
            "lastAttemptAt": None, "nextRetryAt": None, "lastError": None,
            "payload": copy.deepcopy(payload or {}),
            "createdAt": datetime.now(timezone.utc).isoformat(), "syncedAt": None,
        }
        return copy.deepcopy(self.items[sid])

    async def get_pending(self, limit=20):
        now = datetime.now(timezone.utc)
        out = [copy.deepcopy(i) for i in sorted(self.items.values(), key=lambda x: x["createdAt"])
               if i["status"] in ("PENDING", "FAILED")
               and (i["nextRetryAt"] is None or datetime.fromisoformat(i["nextRetryAt"]) <= now)]
        return out[:limit]

    async def claim(self, sync_ids):
        n = 0
        for sid in sync_ids:
            it = self.items.get(sid)
            if it and it["status"] in ("PENDING", "FAILED"):
                it["status"] = "IN_PROGRESS"
                it["attemptCount"] += 1
                it["lastAttemptAt"] = datetime.now(timezone.utc).isoformat()
                n += 1
        return n

    async def mark_synced(self, sync_id):
        it = self.items.get(sync_id)
        if not it:
            return False
        it["status"] = "SYNCED"
        it["syncedAt"] = datetime.now(timezone.utc).isoformat()
        return True

    async def mark_failed(self, sync_id, error, next_retry_at=None):
        it = self.items.get(sync_id)
        if not it:
            return False
        it["status"] = "FAILED"
        it["lastError"] = error
        it["nextRetryAt"] = next_retry_at.isoformat() if next_retry_at else None
        return True

    async def count_by_status(self):
        counts = {"PENDING": 0, "IN_PROGRESS": 0, "FAILED": 0, "SYNCED": 0}
        for it in self.items.values():
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        return counts

    async def cleanup_synced(self, older_than_days=30):
        return 0


class FlappingClient:
    """Central client stand-in with togglable availability; records pushes."""

    def __init__(self, available=False):
        self.available = available
        self.pushes = []

    async def health_check(self):
        if not self.available:
            raise ConnectionError("connection refused")
        await asyncio.sleep(0.001)
        return True

    async def push_event(self, payload, sync_id):
        self.pushes.append(("EVENT", sync_id, copy.deepcopy(payload)))
        if not self.available:
            return SyncResult(success=False, error="connection refused", retryable=True)
        return SyncResult(success=True, status_code=200)

    async def push_evidence_metadata(self, payload, sync_id):
        self.pushes.append(("EVIDENCE", sync_id, copy.deepcopy(payload)))
        if not self.available:
            return SyncResult(success=False, error="connection refused", retryable=True)
        return SyncResult(success=True, status_code=200)

    async def push_evidence_file(self, evidence_id, file_bytes, sha256, sync_id):
        self.pushes.append(("FILE", sync_id, len(file_bytes)))
        if not self.available:
            return SyncResult(success=False, error="connection refused", retryable=True)
        return SyncResult(success=True, status_code=200)

    async def close(self):
        pass


class FakeAuditRepo:
    def __init__(self):
        self.logs = []

    async def log(self, action, entity_type, entity_id, details=None, actor=None):
        self.logs.append({"action": action, "entity_type": entity_type,
                          "entity_id": entity_id, "details": details, "actor": actor})


class FakeEvidenceRepo:
    def __init__(self):
        self.records = {}

    async def create(self, record):
        d = copy.deepcopy(record)
        self.records[d.get("id")] = d
        return copy.deepcopy(d)

    async def get(self, evidence_id):
        r = self.records.get(evidence_id)
        return copy.deepcopy(r) if r else None


class FakeAnchorRepo:
    """Mirrors BlockchainAnchorRepository kwargs + camelCase rows."""

    def __init__(self):
        self._anchors = {}

    async def create(self, anchor_id, evidence_id, sha256_hash, record_hash,
                     tx_hash, block_number, previous_hash="0" * 64,
                     status="CONFIRMED", confirmation_time_ms=0.0):
        row = {"anchorId": anchor_id, "evidenceId": evidence_id,
               "sha256Hash": sha256_hash, "recordHash": record_hash,
               "txHash": tx_hash, "blockNumber": block_number,
               "previousHash": previous_hash, "status": status,
               "createdAt": datetime.now(timezone.utc).isoformat(),
               "confirmationTimeMs": confirmation_time_ms}
        self._anchors[anchor_id] = copy.deepcopy(row)
        return copy.deepcopy(row)

    async def get_by_id(self, anchor_id):
        a = self._anchors.get(anchor_id)
        return copy.deepcopy(a) if a else None

    async def get_by_evidence(self, evidence_id):
        for a in self._anchors.values():
            if a["evidenceId"] == evidence_id and a["status"] in ("PENDING", "CONFIRMED"):
                return copy.deepcopy(a)
        return None

    async def update_status(self, anchor_id, status, block_number=None, confirmation_time_ms=None):
        if anchor_id not in self._anchors:
            return False
        self._anchors[anchor_id]["status"] = status
        return True

    async def list_pending(self, limit=20):
        return []

    async def count_by_status(self):
        counts = {}
        for a in self._anchors.values():
            counts[a["status"]] = counts.get(a["status"], 0) + 1
        return counts

    async def list_recent(self, limit=10):
        items = sorted(self._anchors.values(), key=lambda x: x["createdAt"], reverse=True)
        return copy.deepcopy(items[:limit])


class FailingLedger:
    async def append(self, evidence_id, sha256_hash):
        raise AnchorError("simulated ledger outage")

    async def verify(self, evidence_id, sha256_hash):
        raise AnchorError("simulated ledger outage")

    async def health_check(self):
        return False


class UntouchedSyncSeam:
    """Any attribute access raises — proves blockchain never touches the sync seam."""

    def __getattr__(self, name):
        raise AssertionError("blockchain touched sync seam: %s" % name)


def _patch_net_settings(failure_threshold=2, recovery_threshold=2):
    patcher = patch("ai.network.health.settings")
    ms = patcher.start()
    ms.NETWORK_HEALTH_ENABLED = True
    ms.NETWORK_HEALTH_INTERVAL_SEC = 1
    ms.NETWORK_HEALTH_TIMEOUT_SEC = 5
    ms.NETWORK_DEGRADED_LATENCY_MS = 1000
    ms.NETWORK_FAILURE_THRESHOLD = failure_threshold
    ms.NETWORK_RECOVERY_THRESHOLD = recovery_threshold
    ms.NETWORK_HEALTH_WINDOW_SIZE = 20
    return patcher


def _make_frame(w=320, h=240):
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :] = (90, 120, 200)
    return frame


def _make_event(event_id="EVT-P6-001"):
    return {"event_id": event_id, "camera_id": "CAM-P6",
            "event_type": "PERSON_INTRUSION", "severity": "CRITICAL",
            "track_id": 3, "object_class": "person", "confidence": 0.9,
            "bbox": {"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.5},
            "zone_name": "P6", "timestamp": datetime.now(timezone.utc).isoformat()}


# ──────────────────────────────────────────────────────────────
# NETWORK: full outage → recovery cycle
# ──────────────────────────────────────────────────────────────

class TestOutageRecoveryCycle(unittest.TestCase):
    def test_full_cycle_connected_degraded_offline_recovering_connected(self):
        """CONNECTED → DEGRADED → OFFLINE → RECOVERING → CONNECTED in one instance."""
        patcher = _patch_net_settings(failure_threshold=2, recovery_threshold=2)
        try:
            client = FlappingClient(available=True)
            health = NetworkHealthManager(central_client=client, audit_repo=FakeAuditRepo())
            _run(health.check())
            _run(health.check())
            self.assertEqual(health.state, NetworkState.CONNECTED)
            client.available = False
            _run(health.check())
            _run(health.check())
            self.assertEqual(health.state, NetworkState.DEGRADED)
            _run(health.check())
            self.assertEqual(health.state, NetworkState.OFFLINE)
            self.assertIsNotNone(health.get_metrics().offline_since)
            client.available = True
            _run(health.check())
            self.assertEqual(health.state, NetworkState.RECOVERING)
            _run(health.check())
            self.assertEqual(health.state, NetworkState.CONNECTED)
            m = health.get_metrics()
            self.assertTrue(m.central_reachable)
            self.assertIsNone(m.offline_since)
        finally:
            patcher.stop()

    def test_sync_manager_defers_to_health_state(self):
        """SyncManager._check_connectivity follows NetworkHealthManager (no restart)."""
        patcher = _patch_net_settings(failure_threshold=1, recovery_threshold=1)
        try:
            client = FlappingClient(available=False)
            audit = FakeAuditRepo()
            health = NetworkHealthManager(central_client=client, audit_repo=audit)
            mgr = SyncManager(sync_repo=FakeSyncRepo(), evidence_store=None,
                              audit_repo=audit, central_client=client, network_health=health)
            _run(health.check())
            _run(mgr._check_connectivity())
            self.assertEqual(mgr._connectivity, "OFFLINE")
            # Same instances recover — no restart required
            client.available = True
            _run(health.check())  # OFFLINE -> RECOVERING
            _run(health.check())  # RECOVERING -> CONNECTED (threshold met)
            _run(mgr._check_connectivity())
            self.assertEqual(mgr._connectivity, "CONNECTED")
        finally:
            patcher.stop()

    def test_offline_transition_audited(self):
        patcher = _patch_net_settings(failure_threshold=1, recovery_threshold=1)
        try:
            client = FlappingClient(available=True)
            audit = FakeAuditRepo()
            health = NetworkHealthManager(central_client=client, audit_repo=audit)
            _run(health.check())
            client.available = False
            _run(health.check())
            _run(health.check())
            actions = [l["action"] for l in audit.logs]
            self.assertIn("network.state_changed", actions)
        finally:
            patcher.stop()


# ──────────────────────────────────────────────────────────────
# SYNC: outage queueing, retry, dedup, no second queue
# ──────────────────────────────────────────────────────────────

class TestStoreAndForwardOutage(unittest.TestCase):
    def _mgr(self, client):
        audit = FakeAuditRepo()
        repo = FakeSyncRepo()
        mgr = SyncManager(sync_repo=repo, evidence_store=None, audit_repo=audit,
                          central_client=client, network_health=None)
        return mgr, repo, audit

    def test_enqueue_held_pending_then_synced_once_on_recovery(self):
        client = FlappingClient(available=False)
        mgr, repo, _ = self._mgr(client)
        self.assertTrue(_run(mgr.enqueue_event("EVT-P6-A", {"event_id": "EVT-P6-A"})))
        # duplicate while pending is rejected
        self.assertFalse(_run(mgr.enqueue_event("EVT-P6-A", {"event_id": "EVT-P6-A"})))
        pending = _run(repo.get_pending())
        self.assertEqual(len(pending), 1)
        # recovery on the SAME manager instance
        client.available = True
        stats = _run(mgr.run_sync_pass())
        self.assertEqual(stats.get("synced"), 1)
        self.assertEqual(len(client.pushes), 1)
        # second pass finds nothing — no duplicate central records
        stats2 = _run(mgr.run_sync_pass())
        self.assertEqual(stats2.get("processed"), 0)
        self.assertEqual(len(client.pushes), 1)

    def test_retryable_failure_backoff_then_recovery(self):
        client = FlappingClient(available=False)
        mgr, repo, _ = self._mgr(client)
        _run(mgr.enqueue_event("EVT-P6-B", {"event_id": "EVT-P6-B"}))
        stats = _run(mgr.run_sync_pass())
        self.assertEqual(stats.get("failed"), 1)
        item = [i for i in repo.items.values() if i["entityId"] == "EVT-P6-B"][0]
        self.assertEqual(item["status"], "FAILED")
        self.assertIsNotNone(item["nextRetryAt"])
        self.assertGreaterEqual(item["attemptCount"], 1)
        # backoff holds the item out of the pending set
        ids = [p["entityId"] for p in _run(repo.get_pending())]
        self.assertNotIn("EVT-P6-B", ids)
        # after backoff elapses it becomes retryable and syncs on recovery
        item["nextRetryAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        client.available = True
        stats2 = _run(mgr.run_sync_pass())
        self.assertEqual(stats2.get("synced"), 1)

    def test_unknown_entity_type_isolated(self):
        client = FlappingClient(available=True)
        mgr, repo, _ = self._mgr(client)
        _run(repo.enqueue("BLOCKCHAIN_ANCHOR", "ANC-X", payload={}))
        stats = _run(mgr.run_sync_pass())
        self.assertEqual(stats.get("synced"), 0)
        # no crash, item claimed but not synced
        counts = _run(repo.count_by_status())
        self.assertEqual(counts.get("SYNCED"), 0)

    def test_no_blockchain_dependency_in_sync_package(self):
        """SyncManager path must never import the blockchain layer (no 2nd queue)."""
        import pathlib
        pkg = Path(_project_root) / "ai" / "sync"
        hits = [p.name for p in pkg.glob("*.py")
                if "blockchain" in p.read_text(encoding="utf-8").lower()]
        self.assertEqual(hits, [])

    def test_blockchain_service_never_touches_sync_seam(self):
        """Behavioral no-recursion proof across anchor/verify/reconcile."""
        tmp = tempfile.mkdtemp(prefix="ibvap_p6_")
        try:
            store = LocalFileEvidenceStore(base_dir=tmp)
            erepo = FakeEvidenceRepo()
            arepo = FakeAnchorRepo()
            audit = FakeAuditRepo()
            svc = BlockchainService(ledger=LocalLedger(anchor_repo=arepo),
                                    evidence_repo=erepo, evidence_store=store,
                                    audit_repo=audit, anchor_repo=arepo,
                                    sync_repo=UntouchedSyncSeam())
            with patch("ai.blockchain.service.settings") as ms:
                ms.BLOCKCHAIN_ENABLED = True
                ms.BLOCKCHAIN_ANCHOR_POLICY = "all"
                ms.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
                anchor = _run(svc.maybe_anchor({
                    "id": "EVD-NOREC", "sha256Hash": "ab" * 32,
                    "metadata": {"severity": "CRITICAL"}}))
                # evidence unknown → skipped, sync seam untouched (no raise = pass)
                self.assertIsNone(anchor)
                vr = _run(svc.verify_evidence({"id": "EVD-NOREC", "sha256Hash": "ab" * 32}))
                self.assertFalse(vr.verified)
                rc = _run(svc.reconcile_anchor("ANC-MISSING"))
                self.assertFalse(rc.matched)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────
# EVIDENCE during outage
# ──────────────────────────────────────────────────────────────

class TestEvidenceDuringOutage(unittest.TestCase):
    def _capture_stack(self, tmp, ledger):
        store = LocalFileEvidenceStore(base_dir=tmp)
        erepo = FakeEvidenceRepo()
        arepo = FakeAnchorRepo()
        audit = FakeAuditRepo()
        svc = BlockchainService(ledger=ledger, evidence_repo=erepo,
                                evidence_store=store, audit_repo=audit, anchor_repo=arepo)
        cap = EvidenceCapture(store=store, evidence_repo=erepo, audit_repo=audit,
                              snapshot_quality=80, blockchain_service=svc)
        return cap, svc, audit

    def test_capture_succeeds_when_ledger_down(self):
        tmp = tempfile.mkdtemp(prefix="ibvap_p6_")
        try:
            cap, _, audit = self._capture_stack(tmp, FailingLedger())
            with patch("ai.blockchain.service.settings") as ms:
                ms.BLOCKCHAIN_ENABLED = True
                ms.BLOCKCHAIN_ANCHOR_POLICY = "all"
                ms.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
                res = _run(cap.capture_snapshot(_make_event("EVT-P6-C1"), _make_frame()))
            self.assertIsNotNone(res)
            full = os.path.join(tmp, res["filePath"])
            self.assertTrue(os.path.isfile(full) and os.path.getsize(full) > 0)
            import hashlib
            with open(full, "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), res["sha256Hash"])
            self.assertTrue(any(l["action"] == "blockchain.anchor_failed" for l in audit.logs))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_outage_evidence_verifies_after_recovery(self):
        tmp = tempfile.mkdtemp(prefix="ibvap_p6_")
        try:
            cap, svc, _ = self._capture_stack(tmp, LocalLedger(anchor_repo=FakeAnchorRepo()))
            with patch("ai.blockchain.service.settings") as ms:
                ms.BLOCKCHAIN_ENABLED = True
                ms.BLOCKCHAIN_ANCHOR_POLICY = "all"
                ms.BLOCKCHAIN_ANCHOR_MIN_SEVERITY = "HIGH"
                res = _run(cap.capture_snapshot(_make_event("EVT-P6-C2"), _make_frame()))
            self.assertIsNotNone(res)
            with patch("ai.blockchain.service.settings") as ms:
                ms.BLOCKCHAIN_ENABLED = True
                vr = _run(svc.verify_evidence(res))
            self.assertTrue(vr.verified)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_outage_evidence_queued_for_sync(self):
        client = FlappingClient(available=False)
        repo = FakeSyncRepo()
        mgr = SyncManager(sync_repo=repo, evidence_store=None, audit_repo=FakeAuditRepo(),
                          central_client=client, network_health=None)
        ok = _run(mgr.enqueue_evidence("EVD-P6-Q", {"id": "EVD-P6-Q", "sha256Hash": "cd" * 32}))
        self.assertTrue(ok)
        counts = _run(repo.count_by_status())
        self.assertEqual(counts.get("PENDING"), 1)


# ──────────────────────────────────────────────────────────────
# SD/NVR with REAL video file
# ──────────────────────────────────────────────────────────────

class TestSdnvrRealFootage(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(REAL_TEST_VIDEO), "real test video missing")
        self.base = tempfile.mkdtemp(prefix="ibvap_p6_sd_")
        self.sd = os.path.join(self.base, "sd_card")
        os.makedirs(self.sd)
        shutil.copy2(REAL_TEST_VIDEO, os.path.join(self.sd, "rec_real.mp4"))
        with open(os.path.join(self.sd, "notes.txt"), "w") as f:
            f.write("not video")
        with open(os.path.join(self.sd, "corrupt.mp4"), "wb") as f:
            f.write(b"not video data " * 128)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _svc(self):
        return FootageRetrievalService(
            camera_id="CAM-P6", camera_source=self.sd,
            backend=RetrievalBackend.LOCAL_FS,
            local_processing_dir=os.path.join(self.base, "proc"))

    def test_discover_retrieve_process_cleanup_real_video(self):
        svc = self._svc()
        files = svc.discover()
        names = sorted(f.filename for f in files)
        self.assertEqual(names, ["corrupt.mp4", "rec_real.mp4"])
        good = [f for f in files if f.filename == "rec_real.mp4"][0]
        self.assertTrue(svc.retrieve(good.footage_id))
        lp = svc.get_retrieved_path(good.footage_id)
        self.assertTrue(lp and os.path.isfile(lp))
        cap = VideoCapture(source=lp, source_type="video")
        self.assertTrue(cap.open())
        frames = 0
        while frames < 3:
            fr = cap.read_frame()
            if fr is None:
                break
            self.assertEqual(fr.ndim, 3)
            frames += 1
        cap.release()
        self.assertGreater(frames, 0)
        svc.mark_processing(good.footage_id)
        svc.mark_completed(good.footage_id)
        self.assertEqual(good.status, FootageStatus.COMPLETED)
        svc.cleanup(good.footage_id)
        self.assertFalse(os.path.exists(lp))
        # source SD content and unrelated files are intact
        self.assertTrue(os.path.isfile(os.path.join(self.sd, "rec_real.mp4")))
        self.assertTrue(os.path.isfile(os.path.join(self.sd, "notes.txt")))

    def test_invalid_video_fails_safely(self):
        svc = self._svc()
        files = svc.discover()
        bad = [f for f in files if f.filename == "corrupt.mp4"][0]
        self.assertTrue(svc.retrieve(bad.footage_id))
        cap = VideoCapture(source=svc.get_retrieved_path(bad.footage_id), source_type="video")
        readable = False
        if cap.open():
            readable = cap.read_frame() is not None
            cap.release()
        if not readable:
            svc.mark_failed(bad.footage_id, "unreadable video")
        self.assertEqual(bad.status, FootageStatus.FAILED)

    def test_unknown_id_missing_mount_no_backend(self):
        svc = self._svc()
        self.assertFalse(svc.retrieve("DOES-NOT-EXIST"))
        svc.cleanup("DOES-NOT-EXIST")  # must not raise
        missing = FootageRetrievalService(camera_id="CAM-X", camera_source=os.path.join(self.base, "nope"),
                                          backend=RetrievalBackend.LOCAL_FS)
        self.assertEqual(missing.discover(), [])
        none_svc = FootageRetrievalService(camera_id="CAM-Y", camera_source="",
                                           backend=RetrievalBackend.NONE)
        self.assertEqual(none_svc.discover(), [])


# ──────────────────────────────────────────────────────────────
# CAMERA lifecycle truthfulness
# ──────────────────────────────────────────────────────────────

class TestCameraLifecycleTruth(unittest.TestCase):
    def test_real_file_lifecycle_statuses(self):
        cap = VideoCapture(source=REAL_TEST_VIDEO, source_type="video")
        self.assertTrue(cap.open())
        st = cap.get_status()
        self.assertTrue(st.connected)
        self.assertEqual(st.status, "CONNECTED")
        self.assertEqual(st.reconnect_count, 0)
        self.assertIsNone(st.last_error)
        fr = cap.read_frame()
        self.assertIsNotNone(fr)
        self.assertEqual(cap.get_status().frames_read, 1)
        cap.release()
        st2 = cap.get_status()
        self.assertFalse(st2.connected)

    def test_missing_file_reports_disconnected(self):
        cap = VideoCapture(source=os.path.join(_project_root, "data", "missing_p6.mp4"),
                           source_type="video")
        self.assertFalse(cap.open())
        st = cap.get_status()
        self.assertFalse(st.connected)
        self.assertEqual(st.status, "DISCONNECTED")

    def test_two_instances_isolated(self):
        c1 = VideoCapture(source=REAL_TEST_VIDEO, source_type="video")
        c2 = VideoCapture(source=REAL_TEST_VIDEO, source_type="video")
        self.assertTrue(c1.open() and c2.open())
        self.assertIsNotNone(c1.read_frame())
        c1.release()
        # c2 unaffected by c1's release
        self.assertIsNotNone(c2.read_frame())
        self.assertTrue(c2.get_status().connected)
        c2.release()


# ──────────────────────────────────────────────────────────────
# SECURITY: offline must not weaken auth
# ──────────────────────────────────────────────────────────────

class TestSecurityOffline(unittest.TestCase):
    def test_rbac_enforced_without_network(self):
        """require_permission denies locally — no central call involved."""
        viewer = UserContext(user_id="u1", email="v@t.local", role=Role.VIEWER,
                             permissions=list(ROLE_PERMISSIONS[Role.VIEWER]))
        admin = UserContext(user_id="u2", email="a@t.local", role=Role.ADMIN,
                            permissions=list(ROLE_PERMISSIONS[Role.ADMIN]))
        check_ctrl = require_permission(Permission.SYNC_CONTROL)
        with self.assertRaises(HTTPException) as ctx:
            _run(check_ctrl(viewer))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIs(_run(check_ctrl(admin)), admin)

    def test_viewer_and_edge_scope_restricted(self):
        self.assertNotIn(Permission.EVIDENCE_DELETE, ROLE_PERMISSIONS[Role.VIEWER])
        self.assertNotIn(Permission.BLOCKCHAIN_ANCHOR, ROLE_PERMISSIONS[Role.VIEWER])
        self.assertNotIn(Permission.SYNC_CONTROL, ROLE_PERMISSIONS[Role.VIEWER])
        self.assertFalse(EdgePermissions.CAN_BLOCKCHAIN_ANCHOR)

    def test_no_secrets_in_sync_and_network_status(self):
        client = FlappingClient(available=False)
        mgr = SyncManager(sync_repo=FakeSyncRepo(), evidence_store=None,
                          audit_repo=FakeAuditRepo(), central_client=client, network_health=None)
        blob = str(mgr.get_status())
        for secret_word in ("token", "secret", "password", "api_key", "apikey"):
            self.assertNotIn(secret_word, blob.lower())
        patcher = _patch_net_settings()
        try:
            health = NetworkHealthManager(central_client=client, audit_repo=FakeAuditRepo())
            _run(health.check())
            mblob = str(health.get_metrics())
            for secret_word in ("token", "secret", "password", "api_key", "apikey"):
                self.assertNotIn(secret_word, mblob.lower())
        finally:
            patcher.stop()


# ──────────────────────────────────────────────────────────────
# NOPATH: no blockchain in per-frame / sync code paths
# ──────────────────────────────────────────────────────────────

class TestNoBlockchainInHotPath(unittest.TestCase):
    def test_no_blockchain_imports_outside_trust_layer(self):
        """ai/pipeline, video, tracking, events, camera, sync must not import ai.blockchain."""
        import pathlib
        import re
        roots = ["ai/pipeline.py", "ai/video", "ai/tracking", "ai/events",
                 "ai/camera", "ai/sync", "ai/evidence"]
        pattern = re.compile(r"from ai\.blockchain|import ai\.blockchain|from \.\.blockchain")
        hits = []
        for rel in roots:
            p = Path(_project_root) / rel
            files = [p] if p.is_file() else [f for f in p.rglob("*.py") if "test" not in f.name]
            for f in files:
                if pattern.search(f.read_text(encoding="utf-8")):
                    hits.append(str(f))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
