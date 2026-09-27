"""Targeted OOM hypothesis test: does the local-video EOF reopen pattern leak?

The 13.6-minute 6-camera run died with MemoryError + ffmpeg av_frame_alloc
failures after ~241 "Video EOF, restarting..." cycles, and the capture loop's
local-EOF handler does release() -> new VideoCapture() -> open() per loop
(pipeline.py). This test isolates exactly that pattern:

    open -> decode every frame -> release   (xN)

and asserts process RSS growth stays bounded after a warmup phase. A leaking
decoder/native context would grow RSS by megabytes per cycle and fail loudly;
allocator noise on a healthy loop stays well under the threshold.

Requires psutil (present in the dev env); skipped where unavailable so CI
without it still passes.
"""

import gc
import os

import pytest

psutil = pytest.importorskip("psutil")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from ai.video.capture import VideoCapture  # noqa: E402

WARMUP_LOOPS = 5
MEASURED_LOOPS = 40
# A genuinely leaking decoder context is ~MBs per cycle; healthy allocator
# noise across 40 cycles of a tiny clip stays far below this.
MAX_TOTAL_GROWTH_MB = 30.0


def _make_clip(path: str, frames: int = 60, size=(640, 480)) -> str:
    w, h = size
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (w, h))
    assert out.isOpened(), "cv2.VideoWriter failed to open %s" % path
    for i in range(frames):
        img = np.full((h, w, 3), (i * 3) % 255, dtype=np.uint8)
        out.write(img)
    out.release()
    return path


def _reopen_loops(path: str, n: int) -> None:
    """Same pattern as the pipeline's local-EOF handler: release + fresh open."""
    for _ in range(n):
        cap = VideoCapture(source=path, source_type="video")
        try:
            assert cap.open(), "open failed mid-loop"
            while cap.read_frame() is not None:
                pass
        finally:
            cap.release()


def _rss_mb() -> float:
    gc.collect()
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def test_reopen_loop_does_not_leak_rss(tmp_path):
    clip = _make_clip(str(tmp_path / "rss_probe.mp4"))
    try:
        _reopen_loops(clip, WARMUP_LOOPS)  # stabilize allocator / codec caches
        rss_start = _rss_mb()
        _reopen_loops(clip, MEASURED_LOOPS)
        rss_end = _rss_mb()
    finally:
        try:
            os.remove(clip)
        except OSError:
            pass

    growth = rss_end - rss_start
    per_loop = growth / MEASURED_LOOPS
    print(
        "\n[OOM-PROBE] RSS: %.1f MB -> %.1f MB over %d reopen loops "
        "(%+.2f MB total, %+.3f MB/loop)"
        % (rss_start, rss_end, MEASURED_LOOPS, growth, per_loop)
    )
    assert growth < MAX_TOTAL_GROWTH_MB, (
        "reopen pattern leaked RSS: %+.1f MB over %d loops "
        "(%+.2f MB/loop) — likely native decoder leak in release/open cycle"
        % (growth, MEASURED_LOOPS, per_loop)
    )


_REAL_4K_CLIP = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "data", "cameras", "pexels-george-morina-6719160 (2160p).mp4",
)


def _reopen_partial(path: str, n: int, frames_per_loop: int = 60) -> None:
    """Open -> read a bounded window -> release, xN (per-open context scale).

    The OOM run used 1080p/2160p sources; a decoder-context leak scales with
    resolution, so the synthetic 640x480 probe alone is not conclusive.
    """
    for _ in range(n):
        cap = VideoCapture(source=path, source_type="video")
        try:
            assert cap.open(), "open failed mid-loop"
            for _ in range(frames_per_loop):
                if cap.read_frame() is None:
                    break
        finally:
            cap.release()


@pytest.mark.skipif(
    not os.path.isfile(_REAL_4K_CLIP), reason="real 2160p clip not present"
)
def test_reopen_loop_real_4k_clip_does_not_leak_rss():
    warmup, measured = 3, 15
    _reopen_partial(_REAL_4K_CLIP, warmup)
    rss_start = _rss_mb()
    _reopen_partial(_REAL_4K_CLIP, measured)
    rss_end = _rss_mb()

    growth = rss_end - rss_start
    per_loop = growth / measured
    print(
        "\n[OOM-PROBE 2160p] RSS: %.1f MB -> %.1f MB over %d reopen loops "
        "(%+.2f MB total, %+.3f MB/loop)"
        % (rss_start, rss_end, measured, growth, per_loop)
    )
    # A leaking 4K decoder context is tens of MB per open (YUV plane-sized);
    # healthy retention after warmup stays well below this.
    assert growth < 60.0, (
        "4K reopen pattern leaked RSS: %+.1f MB over %d loops (%+.2f MB/loop)"
        % (growth, measured, per_loop)
    )
