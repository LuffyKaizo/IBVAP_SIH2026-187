"""Video capture abstraction — file, webcam, and RTSP sources.

Hardened for IP CCTV / RTSP ingestion:

- RTSP connections use OpenCV FFMPEG backend with configurable
  OPEN_TIMEOUT / READ_TIMEOUT (verified supported by the installed
  OpenCV build; BUFFERSIZE is applied via set() after open because the
  FFMPEG backend rejects it inside the .open(params) list).
- Bounded exponential backoff reconnect for network sources (MP4 and
  webcam do not reconnect — they are local resources; MP4 EOF is
  handled by the pipeline restart path).
- Stale-frame detection: if no frame arrives within
  FRAME_TIMEOUT_SECONDS, the status reports STALE/UNHEALTHY without
  killing a technically-alive socket.
- Real measured FPS tracking (separate from nominal source FPS).
- RTSP credentials are never exposed: `source_display` masks the
  password portion of the URL in every log/status path.
"""

import cv2
import time
import re as _re
import numpy as np
from typing import Optional, Generator
from dataclasses import dataclass, field

from ai.config import settings


def mask_rtsp_credentials(source: str) -> str:
    """Mask the password in an rtsp/http URL: rtsp://user:pass@host -> rtsp://user:****@host."""
    return _re.sub(r"(://[^:/@\s]+:)([^@\s]+)(@)", r"\1****\3", source)


@dataclass
class FrameInfo:
    """Metadata for a single captured frame."""
    frame_number: int
    timestamp_sec: float
    wall_timestamp: float  # time.time() when the frame was captured
    width: int
    height: int
    source_fps: float
    read_latency_ms: float


@dataclass
class CaptureStatus:
    """Current status of the video capture session."""
    source_type: str
    source: str          # credential-masked display form
    connected: bool
    status: str = "DISCONNECTED"  # CONNECTED|CONNECTING|RECONNECTING|STALE|DISCONNECTED|STOPPED|ERROR
    width: int = 0
    height: int = 0
    fps: float = 0.0            # nominal source fps (container metadata)
    measured_source_fps: float = 0.0  # actual incoming frame rate (measured)
    total_frames: int = 0
    frames_read: int = 0
    last_frame_timestamp: Optional[float] = None
    elapsed_sec: float = 0.0
    effective_fps: float = 0.0
    reconnect_count: int = 0
    last_error: Optional[str] = None


# Connection states (module-level constants for reuse by tests/UI)
ST_CONNECTED = "CONNECTED"
ST_CONNECTING = "CONNECTING"
ST_RECONNECTING = "RECONNECTING"
ST_STALE = "STALE"
ST_DISCONNECTED = "DISCONNECTED"
ST_STOPPED = "STOPPED"
ST_ERROR = "ERROR"


class VideoCapture:
    """Unified video source capture using OpenCV.

    Supports MP4 files, webcams, and RTSP streams.
    For RTSP: bounded exponential-backoff reconnect, stale-frame
    detection, measured FPS, and credential masking.
    """

    def __init__(self, source: Optional[str] = None, source_type: Optional[str] = None):
        self.source = source or settings.VIDEO_SOURCE
        self.source_type = source_type or settings.VIDEO_SOURCE_TYPE
        self._cap: Optional[cv2.VideoCapture] = None
        self._connected: bool = False
        self._status: str = ST_DISCONNECTED
        self._frames_read: int = 0
        self._start_time: float = 0.0
        self._last_frame_time: float = 0.0
        self._width: int = 0
        self._height: int = 0
        self._fps: float = 0.0
        self._total_frames: int = 0
        # Reconnect / health state
        self._reconnect_count: int = 0
        self._last_error: Optional[str] = None
        self._stale: bool = False
        self._stopped: bool = False
        # Measured incoming FPS (windowed)
        self._fps_window: list = []
        self._frame_times: list = []
        self._total_frames_ever: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _is_network_source(self) -> bool:
        s = (self.source or "").lower()
        return s.startswith("rtsp://") or s.startswith("rtsps://") or s.startswith("http://") or s.startswith("https://")

    def _open_once(self) -> bool:
        """Single attempt to open the source. Returns True on success."""
        try:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None

            if self.source_type == "rtsp" or self._is_network_source():
                self._cap = cv2.VideoCapture()
                # NOTE: this OpenCV FFMPEG build accepts OPEN/READ timeouts in
                # the params list but rejects CAP_PROP_BUFFERSIZE there;
                # buffersize is set separately after a successful open.
                params = [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(settings.RTSP_OPEN_TIMEOUT_SEC * 1000),
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(settings.RTSP_READ_TIMEOUT_SEC * 1000),
                ]
                ok = self._cap.open(self.source, cv2.CAP_FFMPEG, params)
                if ok:
                    try:
                        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, settings.RTSP_BUFFER_SIZE)
                    except Exception:
                        pass  # backend may ignore; not critical
            elif self.source_type == "webcam":
                idx = int(self.source) if str(self.source).isdigit() else 0
                self._cap = cv2.VideoCapture(idx)
            else:
                # MP4 / file
                self._cap = cv2.VideoCapture(self.source)

            if self._cap is None or not self._cap.isOpened():
                self._last_error = "open failed (source unavailable or unreachable)"
                return False

            self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._fps = self._cap.get(cv2.CAP_PROP_FPS)
            if self._fps and (self._fps != self._fps):  # NaN check
                self._fps = 0.0
            self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self._connected = True
            self._status = ST_CONNECTED
            self._stale = False
            self._last_error = None
            self._last_frame_time = time.time()
            return True
        except Exception as e:
            # mask credentials in any exception text
            self._last_error = mask_rtsp_credentials(str(e))
            self._connected = False
            return False

    def _backoff_delay(self) -> float:
        """Exponential backoff with cap: 1, 2, 4, 8 ... MAX (bounded, no tight loop)."""
        delay = settings.RECONNECT_INITIAL_DELAY_SEC * (2 ** min(self._reconnect_count, 6))
        return min(delay, settings.RECONNECT_MAX_DELAY_SEC)

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleep in small slices, aborting early when stop() is requested.

        Returns False if aborted (stopped), True if the full delay elapsed.
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stopped:
                return False
            time.sleep(min(0.1, max(0.0, deadline - time.time())))
        return not self._stopped

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def open(self) -> bool:
        """Open the video source.

        Local sources (MP4/webcam): a single attempt, mirroring previous behavior.
        Network sources (RTSP): bounded retry loop with exponential backoff;
        gives up only after RECONNECT_MAX_ATTEMPTS consecutive failures
        (0 = retry forever) so a temporary network outage cannot crash startup.
        """
        self._stopped = False
        self._start_time = time.time()
        self._frames_read = 0
        self._total_frames_ever = 0
        self._fps_window = []
        self._status = ST_CONNECTING

        if not self._is_network_source():
            ok = self._open_once()
            if not ok:
                self._status = ST_ERROR if self.source_type != "video" else ST_DISCONNECTED
            return ok

        attempts = 0
        while True:
            if self._stopped:
                self._status = ST_STOPPED
                return False
            attempts += 1
            print("[IBVAP-VIDEO] Connecting to %s (attempt %d)..." % (
                mask_rtsp_credentials(self.source), attempts))
            if self._open_once():
                print("[IBVAP-VIDEO] Connected: %s" % mask_rtsp_credentials(self.source))
                return True
            self._status = ST_RECONNECTING
            if settings.RECONNECT_MAX_ATTEMPTS and attempts >= settings.RECONNECT_MAX_ATTEMPTS:
                self._status = ST_ERROR
                print("[IBVAP-VIDEO] Giving up after %d attempts" % attempts)
                return False
            delay = self._backoff_delay()
            print("[IBVAP-VIDEO] Not available; retrying in %.1fs (status=%s)" % (delay, self._status))
            if not self._sleep_interruptible(delay):
                self._status = ST_STOPPED
                return False
            # consecutive-failure backoff growth
            self._reconnect_count += 1

    def reconnect(self) -> bool:
        """Attempt a controlled reconnect after a read failure.

        Increments the reconnect counter and applies exponential backoff
        before the attempt. Returns True if reconnected.
        """
        self._connected = False
        self._status = ST_RECONNECTING
        self._reconnect_count += 1
        delay = self._backoff_delay()
        print("[IBVAP-VIDEO] Reconnecting to %s in %.1fs (attempt %d)..." % (
            mask_rtsp_credentials(self.source), delay, self._reconnect_count))
        if not self._sleep_interruptible(delay):
            self._status = ST_STOPPED
            return False
        if self._open_once():
            print("[IBVAP-VIDEO] Reconnected: %s" % mask_rtsp_credentials(self.source))
            return True
        self._status = ST_RECONNECTING
        return False

    def read_frame(self) -> Optional[np.ndarray]:
        """Read a single frame. Returns BGR numpy array or None."""
        if self._cap is None or not self._cap.isOpened():
            return None
        start = time.time()
        try:
            ret, frame = self._cap.read()
        except Exception as e:
            self._last_error = mask_rtsp_credentials(str(e))
            return None
        now = time.time()
        if ret and frame is not None:
            self._frames_read += 1
            self._total_frames_ever += 1
            self._last_frame_time = now
            self._stale = False
            if self._status in (ST_STALE, ST_RECONNECTING):
                self._status = ST_CONNECTED
            # measured incoming fps (3-second window)
            self._frame_times.append(now)
            cutoff = now - 3.0
            self._frame_times = [t for t in self._frame_times if t > cutoff]
            return frame
        # read failed
        if self._cap is not None and self._cap.isOpened() and self._is_network_source():
            # Alive socket but no frame; stale detection judges health.
            self._last_error = "frame read failed"
            self._stale = True
        else:
            # Local file reached EOF/end, or the handle died.
            self._connected = False
            self._status = ST_DISCONNECTED
        return None

    def is_stale(self) -> bool:
        """True when no frame arrived within FRAME_TIMEOUT_SECONDS."""
        if self._last_frame_time <= 0:
            return False
        idle = time.time() - self._last_frame_time
        return idle > settings.FRAME_TIMEOUT_SECONDS

    def frame_generator(self, target_fps: Optional[int] = None) -> Generator[tuple[np.ndarray, FrameInfo], None, None]:
        """Yield (frame, info) tuples at target FPS.

        Uses frame-skipping behavior — never accumulates frames in memory.
        If reading is slower than target FPS, yields every frame read.
        """
        fps = target_fps or settings.INFERENCE_FPS
        target_interval = 1.0 / fps
        frame_num = 0

        while True:
            loop_start = time.time()
            frame = self.read_frame()
            if frame is None:
                break

            h, w = frame.shape[:2]
            info = FrameInfo(
                frame_number=frame_num,
                timestamp_sec=round(time.time() - self._start_time, 3),
                wall_timestamp=now if (now := time.time()) else time.time(),
                width=w,
                height=h,
                source_fps=self._fps,
                read_latency_ms=round((time.time() - loop_start) * 1000, 2),
            )
            frame_num += 1
            yield frame, info

            # Frame skipping: sleep only if we're faster than target
            elapsed = time.time() - loop_start
            if elapsed < target_interval:
                time.sleep(target_interval - elapsed)

    def get_status(self) -> CaptureStatus:
        """Return current capture session status."""
        elapsed = time.time() - self._start_time if self._start_time else 0.0
        eff_fps = self._frames_read / elapsed if elapsed > 0 else 0.0
        measured_fps = (
            len(self._frame_times) / 3.0
            if len(self._frame_times) >= 2 and self._frame_times
            else 0.0
        )

        # Derive status
        if self._stopped:
            status = ST_STOPPED
        elif not self._connected or self._cap is None or not self._cap.isOpened():
            status = self._status if self._status in (ST_RECONNECTING, ST_ERROR, ST_CONNECTING) else ST_DISCONNECTED
        elif self.is_stale():
            status = ST_STALE
        else:
            status = ST_CONNECTED

        return CaptureStatus(
            source_type=self.source_type,
            source=mask_rtsp_credentials(self.source),
            connected=self._connected and self._cap is not None and self._cap.isOpened(),
            status=status,
            width=self._width,
            height=self._height,
            fps=self._fps,
            measured_source_fps=round(measured_fps, 2),
            total_frames=self._total_frames,
            frames_read=self._frames_read,
            last_frame_timestamp=self._last_frame_time if self._last_frame_time else None,
            elapsed_sec=round(elapsed, 2),
            effective_fps=round(eff_fps, 2),
            reconnect_count=self._reconnect_count,
            last_error=self._last_error,
        )

    def get_resolution(self) -> tuple[int, int]:
        """Return (width, height)."""
        return (self._width, self._height)

    def get_fps(self) -> float:
        """Return source FPS."""
        return self._fps

    def get_frame_count(self) -> int:
        """Total frames in source (MP4) or 0 for streams."""
        return self._total_frames

    @property
    def is_network_source(self) -> bool:
        """True when the source is a network stream (RTSP/HTTP)."""
        return self._is_network_source()

    @property
    def is_connected(self) -> bool:
        return self._connected and self._cap is not None and self._cap.isOpened()

    def stop(self):
        """Signal generators/reconnect loops to stop; marks status STOPPED."""
        self._stopped = True
        self._status = ST_STOPPED

    def release(self):
        """Release the capture and all resources."""
        self._stopped = True
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._connected = False
        if self._status != ST_STOPPED:
            self._status = ST_STOPPED

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.release()
