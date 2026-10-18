"""Camera ingest and health (spec 6.1, 6.8).

* Enumerates working camera indices instead of hardcoding one.
* Accepts an index, a stream URL (DroidCam's MJPEG feed, e.g.
  ``http://<phone-ip>:4747/video``), a video file, or a directory of frames.
  Directory/video sources are *recordings*: frames carry ``recording:`` provenance
  and are never reported as live.
* Captures on a background thread that always keeps only the newest frame, so a
  slow consumer (or a stalled classifier) never backs up the camera.
* Reports measured FPS, frame age, reconnect count and errors for the operator
  status line.

DroidCam on macOS appears either as a virtual camera device (an index found by
:func:`enumerate_cameras`) or, with no driver installed, through its HTTP MJPEG
URL.  Both paths are handled by :func:`open_source`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import subprocess
import threading
import time
from typing import Iterable, Protocol

import numpy as np

try:  # pragma: no cover - import guard
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from .events import CameraHealth

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")
VIDEO_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv", ".m4v")


# --------------------------------------------------------------------------- sources
class FrameSource(Protocol):
    """Minimal interface the capture worker needs."""

    def read(self) -> tuple[bool, np.ndarray | None]: ...
    def release(self) -> None: ...
    def describe(self) -> str: ...
    @property
    def is_recording(self) -> bool: ...
    @property
    def can_reconnect(self) -> bool: ...
    def reconnect(self) -> bool: ...
    @property
    def frame_index(self) -> int: ...


def _require_cv2() -> None:
    if cv2 is None:
        raise ImportError("opencv-contrib-python is required for perception.camera")


class DeviceSource:
    """A local camera index (built-in, Continuity Camera, DroidCam virtual device)."""

    def __init__(self, index: int, width: int, height: int):
        _require_cv2()
        self.index = index
        self.width_req = width
        self.height_req = height
        self._cap: "cv2.VideoCapture | None" = None
        self._frame_index = 0
        self.open()

    def open(self) -> None:
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            raise RuntimeError(f"camera index {self.index} could not be opened")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width_req)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height_req)
        self._cap = cap

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        if ok and frame is not None:
            self._frame_index += 1
        return ok, frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def describe(self) -> str:
        return f"device:{self.index}"

    @property
    def is_recording(self) -> bool:
        return False

    @property
    def can_reconnect(self) -> bool:
        return True

    def reconnect(self) -> bool:
        self.release()
        try:
            self.open()
            return True
        except RuntimeError:
            return False

    @property
    def frame_index(self) -> int:
        return self._frame_index


class StreamSource:
    """A network stream such as DroidCam's MJPEG endpoint."""

    def __init__(self, url: str):
        _require_cv2()
        self.url = url
        self._cap: "cv2.VideoCapture | None" = None
        self._frame_index = 0
        self.open()

    def open(self) -> None:
        cap = cv2.VideoCapture(self.url)
        if not cap.isOpened():
            raise RuntimeError(f"stream {self.url} could not be opened")
        self._cap = cap

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        if ok and frame is not None:
            self._frame_index += 1
        return ok, frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def describe(self) -> str:
        return f"stream:{self.url}"

    @property
    def is_recording(self) -> bool:
        return False

    @property
    def can_reconnect(self) -> bool:
        return True

    def reconnect(self) -> bool:
        self.release()
        try:
            self.open()
            return True
        except RuntimeError:
            return False

    @property
    def frame_index(self) -> int:
        return self._frame_index


class RecordingSource:
    """A recorded video file or a directory of image frames (sorted by name).

    Used for reproducible tests on authentic captures of the real board.  The
    provenance string identifies the file so a recording is never mistaken for
    a live camera (spec section 10, no-fake-data policy).
    """

    def __init__(self, path: str | Path, fps: float = 30.0, loop: bool = False):
        _require_cv2()
        self.path = Path(path)
        self.fps = max(0.1, float(fps))
        self.loop = loop
        self._frame_index = 0
        self._files: list[Path] = []
        self._cap = None
        self._last_t = 0.0
        self.finished = False
        if self.path.is_dir():
            self._files = sorted(p for p in self.path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            if not self._files:
                raise RuntimeError(f"no image frames in {self.path}")
        elif self.path.suffix.lower() in VIDEO_SUFFIXES:
            self._cap = cv2.VideoCapture(str(self.path))
            if not self._cap.isOpened():
                raise RuntimeError(f"video {self.path} could not be opened")
        elif self.path.suffix.lower() in IMAGE_SUFFIXES:
            self._files = [self.path]
            self.loop = True  # a single still image: keep serving it
        else:
            raise RuntimeError(f"unsupported recording path {self.path}")

    def _pace(self) -> None:
        period = 1.0 / self.fps
        now = time.monotonic()
        wait = self._last_t + period - now
        if wait > 0:
            time.sleep(wait)
        self._last_t = time.monotonic()

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.finished:
            return False, None
        self._pace()
        if self._cap is not None:
            ok, frame = self._cap.read()
            if not ok and self.loop:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
            if not ok:
                self.finished = True
                return False, None
            self._frame_index += 1
            return True, frame
        if self._frame_index >= len(self._files):
            if self.loop:
                self._frame_index = 0
            else:
                self.finished = True
                return False, None
        frame = cv2.imread(str(self._files[self._frame_index]))
        self._frame_index += 1
        if frame is None:
            return False, None
        return True, frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()

    def describe(self) -> str:
        return f"recording:{self.path}"

    @property
    def is_recording(self) -> bool:
        return True

    @property
    def can_reconnect(self) -> bool:
        return False

    def reconnect(self) -> bool:
        return False

    @property
    def frame_index(self) -> int:
        return self._frame_index


# ------------------------------------------------------------------ enumeration
@dataclass
class CameraProbe:
    index: int
    ok: bool
    width: int | None
    height: int | None
    name_hint: str | None = None
    error: str | None = None


def system_camera_names() -> list[str]:
    """Best-effort device names from the OS, for the operator's information only.

    OpenCV does not expose device names; on macOS ``system_profiler`` lists them
    in roughly the same order as AVFoundation indices.  Returns [] elsewhere.
    """
    if platform.system() != "Darwin":
        return []
    try:
        out = subprocess.run(["system_profiler", "SPCameraDataType"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return []
    names: list[str] = []
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith(("Model ID", "Unique ID", "Camera")):
            names.append(stripped[:-1])
    return names


def _probe_index(index: int, width: int, height: int, timeout_s: float) -> CameraProbe:
    result: dict = {}

    def worker() -> None:
        try:
            cap = cv2.VideoCapture(index)
            if not cap.isOpened():
                result["error"] = "not opened"
                cap.release()
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, frame = cap.read()
            if ok and frame is not None:
                result["shape"] = frame.shape
            else:
                result["error"] = "opened but no frame"
            cap.release()
        except Exception as exc:  # pragma: no cover - driver specific
            result["error"] = str(exc)

    if platform.system() == "Darwin":
        # macOS: the AVFoundation camera-permission prompt must run on the main thread
        # ("can not spin main run loop from other thread"), so probe synchronously here.
        worker()
    else:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout_s)
        if thread.is_alive():
            return CameraProbe(index, False, None, None, error="timeout")
    if "shape" in result:
        h, w = result["shape"][:2]
        return CameraProbe(index, True, int(w), int(h))
    error = result.get("error", "unknown")
    if platform.system() == "Darwin" and error == "not opened":
        error = "not opened (if this is a real camera: grant Camera permission to the terminal app in System Settings > Privacy & Security > Camera)"
    return CameraProbe(index, False, None, None, error=error)


def enumerate_cameras(max_index: int = 8, width: int = 1280, height: int = 720,
                      timeout_s: float = 2.5) -> list[CameraProbe]:
    """Probe indices ``0..max_index-1`` and report which deliver frames."""
    _require_cv2()
    names = system_camera_names()
    probes = []
    for index in range(max_index):
        probe = _probe_index(index, width, height, timeout_s)
        if index < len(names):
            probe.name_hint = names[index]
        probes.append(probe)
    return probes


def open_source(source: str | int, width: int = 1280, height: int = 720, *,
                probe_max_index: int = 8, probe_timeout_s: float = 2.5,
                recording_fps: float = 30.0) -> FrameSource:
    """Resolve a configured source string into a :class:`FrameSource`.

    ``"auto"`` picks the first working index (preferring the one that honours
    the requested resolution).  Digits select an index.  ``http://``/``rtsp://``
    open a stream (DroidCam).  An existing path opens a recording.
    """
    _require_cv2()
    if isinstance(source, int):
        return DeviceSource(source, width, height)
    text = str(source).strip()
    if text == "auto":
        probes = [p for p in enumerate_cameras(probe_max_index, width, height, probe_timeout_s) if p.ok]
        if not probes:
            raise RuntimeError("no working camera found (probed indices 0..%d); "
                               "for DroidCam, start its client or pass its MJPEG URL as the source"
                               % (probe_max_index - 1))
        exact = [p for p in probes if p.width == width and p.height == height]
        chosen = (exact or probes)[0]
        return DeviceSource(chosen.index, width, height)
    if text.isdigit():
        return DeviceSource(int(text), width, height)
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "rtsp://", "rtmp://", "udp://", "tcp://")):
        return StreamSource(text)
    path = Path(text)
    if path.exists():
        return RecordingSource(path, fps=recording_fps)
    raise RuntimeError(f"camera source {text!r} is neither an index, a stream URL nor an existing path")


# ------------------------------------------------------------------ worker
@dataclass
class Frame:
    image: np.ndarray
    frame_id: int
    captured_at_ms: int
    provenance: str


class CameraWorker:
    """Background capture thread that keeps only the newest frame."""

    def __init__(self, source: FrameSource, *, stale_frame_ms: int = 1500,
                 reconnect_delay_s: float = 1.0, undistort=None):
        self.source = source
        self.stale_frame_ms = stale_frame_ms
        self.reconnect_delay_s = reconnect_delay_s
        self.undistort = undistort  # callable(frame) -> frame, or None
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._consumed_id = -1
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frames_total = 0
        self._reconnects = 0
        self._error: str | None = None
        self._fps = 0.0
        self._fps_window: list[float] = []
        self.width: int | None = None
        self.height: int | None = None
        self.ended = False  # recordings only

    # -- lifecycle
    def start(self) -> "CameraWorker":
        self._thread = threading.Thread(target=self._run, name="camera-capture", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.source.release()

    # -- data
    def latest(self, *, only_new: bool = True) -> Frame | None:
        with self._lock:
            frame = self._latest
            if frame is None:
                return None
            if only_new and frame.frame_id == self._consumed_id:
                return None
            self._consumed_id = frame.frame_id
            return frame

    def wait_for_frame(self, timeout_s: float) -> Frame | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            frame = self.latest()
            if frame is not None:
                return frame
            if self.ended:
                return None
            time.sleep(0.01)
        return None

    def health(self) -> CameraHealth:
        with self._lock:
            latest = self._latest
            age = None if latest is None else int(time.time() * 1000) - latest.captured_at_ms
        connected = latest is not None and (age is not None and age <= self.stale_frame_ms or self.source.is_recording)
        return CameraHealth(
            connected=bool(connected and not self.ended),
            source=self.source.describe(),
            width=self.width,
            height=self.height,
            fps_measured=round(self._fps, 1),
            last_frame_age_ms=age,
            frames_total=self._frames_total,
            reconnects=self._reconnects,
            error=self._error,
        )

    # -- thread body
    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            ok, image = self.source.read()
            if not ok or image is None:
                if self.source.is_recording:
                    self.ended = True
                    return
                failures += 1
                if failures >= 10 and self.source.can_reconnect:
                    self._error = "no frames; reconnecting"
                    time.sleep(self.reconnect_delay_s)
                    if self.source.reconnect():
                        self._reconnects += 1
                        self._error = None
                    failures = 0
                else:
                    time.sleep(0.005)
                continue
            failures = 0
            if self.undistort is not None:
                image = self.undistort(image)
            now = time.time()
            self._fps_window.append(now)
            self._fps_window = [t for t in self._fps_window if now - t <= 2.0]
            if len(self._fps_window) >= 2:
                span = self._fps_window[-1] - self._fps_window[0]
                self._fps = (len(self._fps_window) - 1) / span if span > 0 else 0.0
            self._frames_total += 1
            self.height, self.width = image.shape[:2]
            provenance = (f"{self.source.describe()}#{self.source.frame_index}"
                          if self.source.is_recording else f"live:{self.source.describe()}")
            frame = Frame(image=image, frame_id=self._frames_total, captured_at_ms=int(now * 1000),
                          provenance=provenance)
            with self._lock:
                self._latest = frame


def iter_frames(worker: CameraWorker, *, stop_when_ended: bool = True) -> Iterable[Frame]:
    """Convenience generator for scripts and tests."""
    while True:
        frame = worker.latest()
        if frame is not None:
            yield frame
        elif worker.ended and stop_when_ended:
            return
        else:
            time.sleep(0.002)
