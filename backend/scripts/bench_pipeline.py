"""IBVAP pipeline benchmark harness (Section 20 baselines / Section 24 re-tests).

Drives the REAL CameraManager + CameraPipeline stack (same wiring as app
startup: engines, ANPR, OCR worker, face detection, MJPEG encode, zone
events) against local benchmark clips, and samples per-camera telemetry
plus host/GPU resource usage.

Usage (cwd = backend/):
    python scripts/bench_pipeline.py --cameras 1 --duration 60 --tag baseline-1cam
    python scripts/bench_pipeline.py --cameras 3 --duration 60 --tag baseline-3cam
    python scripts/bench_pipeline.py --cameras 6 --duration 60 --tag baseline-6cam

Metrics per camera:
    analytics_fps  = delta(frames_processed) / window   (real processed frames)
    display_fps    = delta(jpeg_version) / window       (shared JPEG publishes)
    metadata_fps   = delta(metadata_version) / window   (WS snapshot rate)
    dropped        = delta(dropped_frames) (stale frames overwritten, never faked)
    stage_ms       = rolling per-stage means (track/events/anpr/face/publish/loop_total)
Host/GPU: CPU%, process CPU%, RSS, GPU util%, GPU memory used (nvml).
Output: JSON to <repo>/reports/bench/ + human summary on stdout.
"""
import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
sys.path.insert(0, _BACKEND_DIR)

import psutil  # noqa: E402

from ai.config import settings  # noqa: E402
from ai.camera.config import CameraConfig  # noqa: E402
from ai.camera.manager import CameraManager  # noqa: E402
from ai.events.engine import Zone  # noqa: E402

CLIPS_DIR = os.path.join(_REPO_ROOT, "data", "cameras")

# Scenario slot -> clip filename (fps/res as probed 2026-09-27)
CLIPS = {
    "1080p30": "pexels-george-morina-5293898 (1080p).mp4",   # 1920x1080 @29.97
    "1080p25": "pexels-taryn-elliott-5309381 (1080p).mp4",   # 1920x1080 @25.00
    "4k30":    "Traffic Control CCTV.mp4",                   # 3840x2160 @30.00, 60s
    "4k30b":   "pexels-george-morina-6719160 (2160p).mp4",   # 3840x2160 @29.97
    "720p30":  "Automatic Number Plate Recognition (ANPR) _ Vehicle Number Plate Recognition (1).mp4",
    "1080p30b": "cam-01.mp4",                               # 1920x1080 @29.97
}

SCENARIOS = {
    1: ["1080p30"],
    3: ["1080p30", "1080p25", "4k30"],
    6: ["1080p30", "1080p25", "4k30", "4k30b", "720p30", "1080p30b"],
}

# Bottom-border strip zone (same geometry as the app's normalized legacy
# strip) so context/event/risk engines evaluate exactly as in production
# deployments where operators define zones.
ZONE_STRIP = [
    {"x": 0.10, "y": 0.80},
    {"x": 0.90, "y": 0.80},
    {"x": 0.90, "y": 0.95},
    {"x": 0.10, "y": 0.95},
]


def _make_zone(camera_id: str) -> Zone:
    return Zone(
        id="BENCH-ZONE-%s" % camera_id,
        camera_id=camera_id,
        name="bench strip",
        points=[dict(p) for p in ZONE_STRIP],
        enabled=True,
        severity="CRITICAL",
        zone_type="POLYGON_ZONE",
        rule="RESTRICTED_ENTRY",
    )


class GpuSampler:
    """NVML-based GPU utilization/memory sampler (whole-adapter view)."""

    def __init__(self):
        self._ok = False
        self._h = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._h = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._ok = True
        except Exception as e:
            print("[BENCH] GPU sampling unavailable: %s" % e)

    def read(self):
        if not self._ok:
            return None
        try:
            u = self._nvml.nvmlDeviceGetUtilizationRates(self._h)
            m = self._nvml.nvmlDeviceGetMemoryInfo(self._h)
            return {
                "util_pct": float(u.gpu),
                "mem_used_mb": round(m.used / (1024.0 * 1024.0), 1),
                "mem_total_mb": round(m.total / (1024.0 * 1024.0), 1),
            }
        except Exception:
            return None


def _delta(cur: int, prev: int) -> int:
    """Counter delta that tolerates a monotonic counter (never resets here)."""
    return max(0, cur - prev)


def run_bench(n_cameras: int, duration: float, settle: float, tag: str) -> dict:
    slots = SCENARIOS[n_cameras]
    configs = []
    for i, slot in enumerate(slots, start=1):
        clip = os.path.join(CLIPS_DIR, CLIPS[slot])
        if not os.path.exists(clip):
            raise SystemExit("Missing clip: %s" % clip)
        cid = "BENCH-%02d" % i
        configs.append((cid, slot, CameraConfig(
            camera_id=cid,
            name="Bench %d (%s)" % (i, slot),
            location="bench",
            source=clip,
            source_type="video",
            enabled=True,
        )))

    print("[BENCH] tag=%s cams=%d duration=%.0fs settle=%.0fs" % (
        tag, n_cameras, duration, settle))
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)  # prime
    psutil.cpu_percent(None)

    mgr = CameraManager(model_path=settings.MODEL_PATH)
    t_init0 = time.time()
    for cid, slot, cfg in configs:
        print("[BENCH] registering %s ..." % cid)
        mgr._sync_register_camera(cfg, auto_start=True, zones=[_make_zone(cid)])
    init_s = time.time() - t_init0
    print("[BENCH] registered in %.1fs; waiting for video connect" % init_s)

    # Wait for all pipelines to connect + publish first frames
    t_conn = time.time()
    while time.time() - t_conn < 120.0:
        statuses = [mgr.get_pipeline(cid).get_status() for cid, _, _ in configs]
        if all(s.get("video_connected") and s.get("frames_processed", 0) > 5
               for s in statuses):
            break
        time.sleep(0.5)
    else:
        print("[BENCH] WARNING: not all cameras connected within 120s")
    connect_s = time.time() - t_conn

    print("[BENCH] settle %.0fs ..." % settle)
    time.sleep(settle)

    gpu = GpuSampler()
    cameras = []
    for cid, slot, cfg in configs:
        p = mgr.get_pipeline(cid)
        s = p.get_status()
        cameras.append({
            "camera_id": cid, "slot": slot,
            "source_file": CLIPS[slot],
            "source_fps": s.get("source_fps"),
            "target_fps": s.get("target_fps"),
            "resolution": s.get("resolution"),
            "prev": {
                "frames": s.get("frames_processed", 0),
                "jpeg": s.get("jpeg_version", 0),
                "meta": s.get("metadata_version", 0),
                "dropped": s.get("dropped_frames", 0),
            },
            "fps_ticks": [], "stage_ticks": [], "stage_p95_ticks": [],
            "lat_ticks": [],
            "decode_ticks": [], "ocr_ticks": [],
            "dropped_total": 0,
        })

    ticks = []
    print("[BENCH] sampling %.0fs ..." % duration)
    t0 = time.time()
    while time.time() - t0 < duration:
        time.sleep(1.0)
        tick = {"t": round(time.time() - t0, 1),
                "cpu_pct": psutil.cpu_percent(None),
                "proc_cpu_pct": proc.cpu_percent(None),
                "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
                "gpu": gpu.read(), "cams": {}}
        for cam in cameras:
            p = mgr.get_pipeline(cam["camera_id"])
            if p is None:
                continue
            s = p.get_status()
            prev = cam["prev"]
            d_frames = _delta(s.get("frames_processed", 0), prev["frames"])
            d_jpeg = _delta(s.get("jpeg_version", 0), prev["jpeg"])
            d_meta = _delta(s.get("metadata_version", 0), prev["meta"])
            d_drop = _delta(s.get("dropped_frames", 0), prev["dropped"])
            prev.update({
                "frames": s.get("frames_processed", 0),
                "jpeg": s.get("jpeg_version", 0),
                "meta": s.get("metadata_version", 0),
                "dropped": s.get("dropped_frames", 0),
            })
            cam["fps_ticks"].append((d_frames, d_jpeg, d_meta))
            cam["stage_ticks"].append(s.get("stage_ms", {}))
            cam["stage_p95_ticks"].append(s.get("stage_p95_ms", {}))
            cam["lat_ticks"].append(s.get("avg_latency_ms", 0.0))
            cam["decode_ticks"].append(s.get("last_decode_ms", 0.0))
            cam["ocr_ticks"].append({
                "q": s.get("ocr_queue_depth", 0),
                "pending": s.get("ocr_pending", 0),
                "dropped_jobs": s.get("ocr_dropped_jobs", 0),
                "last_ms": s.get("last_ocr_ms", 0.0),
            })
            cam["dropped_total"] += d_drop
            tick["cams"][cam["camera_id"]] = {
                "frames_delta": d_frames, "jpeg_delta": d_jpeg,
                "meta_delta": d_meta, "drop_delta": d_drop,
                "state_fps": s.get("processing_fps"),
                "connected": s.get("video_connected"),
                "events": len((p.get_metadata() or {}).get("events") or []),
            }
        ticks.append(tick)
        print("  t=%4.0fs  cpu=%4.1f%%  rss=%5.0fMB  gpu=%s" % (
            tick["t"], tick["cpu_pct"], tick["rss_mb"],
            ("%.0f%%/%.0fMB" % (tick["gpu"]["util_pct"], tick["gpu"]["mem_used_mb"]))
            if tick["gpu"] else "-"))

    # ── Aggregate ─────────────────────────────────────────────────────
    n = max(1, len(ticks))
    cam_reports = []
    for cam in cameras:
        fps = [x[0] for x in cam["fps_ticks"]]
        jpg = [x[1] for x in cam["fps_ticks"]]
        met = [x[2] for x in cam["fps_ticks"]]
        stages = {}
        for st in cam["stage_ticks"]:
            for k, v in st.items():
                stages.setdefault(k, []).append(float(v))
        stage_mean = {k: round(sum(v) / len(v), 2) for k, v in stages.items()}
        p95s = {}
        for st in cam["stage_p95_ticks"]:
            for k, v in st.items():
                p95s.setdefault(k, []).append(float(v))
        # Worst per-tick p95 seen for each stage (tail evidence for §24).
        stage_p95_max = {k: round(max(v), 2) for k, v in p95s.items()}
        lats = [x for x in cam["lat_ticks"] if x]
        decs = [x for x in cam["decode_ticks"] if x]
        ocr_drops = [t["dropped_jobs"] for t in cam["ocr_ticks"]]
        cam_reports.append({
            "camera_id": cam["camera_id"], "slot": cam["slot"],
            "source_file": cam["source_file"],
            "source_fps": cam["source_fps"],
            "target_fps": cam["target_fps"],
            "resolution": cam["resolution"],
            "analytics_fps": round(sum(fps) / n, 2),
            "display_fps": round(sum(jpg) / n, 2),
            "metadata_fps": round(sum(met) / n, 2),
            "dropped_frames": cam["dropped_total"],
            "drop_per_s": round(cam["dropped_total"] / n, 2),
            "avg_latency_ms": round(sum(lats) / len(lats), 1) if lats else None,
            "decode_ms": round(sum(decs) / len(decs), 2) if decs else None,
            "stage_ms": stage_mean,
            "stage_p95_ms": stage_p95_max,
            "ocr_dropped_jobs": ocr_drops[-1] if ocr_drops else 0,
        })

    gpu_ticks = [t["gpu"] for t in ticks if t["gpu"]]
    report = {
        "tag": tag,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_cameras": n_cameras,
        "duration_s": duration,
        "settle_s": settle,
        "register_s": round(init_s, 1),
        "connect_wait_s": round(connect_s, 1),
        "ticks": len(ticks),
        "host": {
            "cpu_pct_mean": round(sum(t["cpu_pct"] for t in ticks) / n, 1),
            "cpu_pct_max": max(t["cpu_pct"] for t in ticks),
            "proc_cpu_pct_mean": round(sum(t["proc_cpu_pct"] for t in ticks) / n, 1),
            "rss_mb_mean": round(sum(t["rss_mb"] for t in ticks) / n, 1),
            "rss_mb_max": max(t["rss_mb"] for t in ticks),
        },
        "gpu": {
            "util_pct_mean": round(sum(g["util_pct"] for g in gpu_ticks) / len(gpu_ticks), 1) if gpu_ticks else None,
            "util_pct_max": max((g["util_pct"] for g in gpu_ticks), default=None),
            "mem_used_mb_max": max((g["mem_used_mb"] for g in gpu_ticks), default=None),
        } if gpu_ticks else None,
        "cameras": cam_reports,
        "settings": {
            "model_path": settings.MODEL_PATH,
            "device": settings.DEVICE,
            "anpr_enabled": settings.ANPR_ENABLED,
            "face_detection_enabled": settings.FACE_DETECTION_ENABLED,
            "face_detection_interval": settings.FACE_DETECTION_INTERVAL,
            "inference_fps_fallback": settings.INFERENCE_FPS,
            "ocr_queue_size": settings.OCR_WORKER_QUEUE_SIZE,
            "mjpeg_display_max_width": settings.MJPEG_DISPLAY_MAX_WIDTH,
            "zone": "bottom-strip polygon (4 pts)",
        },
    }

    # ── Persist first (shutdown can hang on model teardown) ──────────
    out_dir = os.path.join(_REPO_ROOT, "reports", "bench")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "%s_%dcam.json" % (tag, n_cameras))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # ── Shutdown ──────────────────────────────────────────────────────
    print("[BENCH] shutting down ...")
    try:
        mgr.shutdown_all()
    except Exception as e:
        print("[BENCH] shutdown error: %s" % e)

    # ── Human summary ────────────────────────────────────────────────
    print("\n==== BENCH %s | %d cam | %.0fs ====" % (tag, n_cameras, duration))
    for c in cam_reports:
        st = c["stage_ms"]
        print("%s %-10s src=%.2f tgt=%.2f | analytics=%.2f display=%.2f "
              "meta=%.2f fps | drop=%d (%.1f/s) | lat=%.0fms dec=%.1fms" % (
                  c["camera_id"], c["slot"], c["source_fps"] or 0,
                  c["target_fps"] or 0, c["analytics_fps"], c["display_fps"],
                  c["metadata_fps"], c["dropped_frames"], c["drop_per_s"],
                  c["avg_latency_ms"] or 0, c["decode_ms"] or 0))
        print("           stages(ms): " + " ".join(
            "%s=%.1f" % (k, v) for k, v in sorted(st.items())))
        p95 = c.get("stage_p95_ms") or {}
        if p95:
            print("           p95(ms):   " + " ".join(
                "%s=%.1f" % (k, v) for k, v in sorted(p95.items())))
    h = report["host"]
    g = report["gpu"] or {}
    print("host: cpu=%.1f%% (max %.1f%%) proc_cpu=%.1f%% rss=%.0fMB (max %.0fMB)"
          % (h["cpu_pct_mean"], h["cpu_pct_max"], h["proc_cpu_pct_mean"],
             h["rss_mb_mean"], h["rss_mb_max"]))
    if g:
        print("gpu: util=%.1f%% (max %.1f%%) mem=%.0fMB" % (
            g["util_pct_mean"] or 0, g["util_pct_max"] or 0,
            g["mem_used_mb_max"] or 0))
    print("JSON: %s" % out_path)
    return report


def main():
    ap = argparse.ArgumentParser(description="IBVAP pipeline benchmark")
    ap.add_argument("--cameras", type=int, required=True, choices=[1, 3, 6])
    ap.add_argument("--duration", type=float, default=60.0,
                    help="sampling window seconds (default 60)")
    ap.add_argument("--settle", type=float, default=10.0,
                    help="warmup/settle seconds before sampling (default 10)")
    ap.add_argument("--tag", required=True, help="run label, e.g. baseline-1cam")
    args = ap.parse_args()
    run_bench(args.cameras, args.duration, args.settle, args.tag)


if __name__ == "__main__":
    main()
