"""Configuration for the perception service.

Every numeric threshold here is a *starting value*.  Spec section 5 requires the
final numbers to be tuned against recorded live frames of the real board, with
the projector on and off.  Record a session with ``python -m perception.service
--record <dir>`` and tune against it; do not tune to maximise a synthetic hit rate.

Values can be overridden by environment variables (``FLOODSHIFT_PERCEPTION_*``)
or a JSON file passed with ``--config``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import os
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DEFAULT_REGISTRATION_PATH = PACKAGE_DIR / "board_registration.json"
ENV_PREFIX = "FLOODSHIFT_PERCEPTION_"


@dataclass
class CameraConfig:
    # "auto" enumerates indices; an integer selects an index; a string that is
    # not an integer is treated as a URL or file path (DroidCam MJPEG URL,
    # a recorded video, or a directory of frames for reproducible tests).
    source: str = "auto"
    width: int = 1280
    height: int = 720
    probe_max_index: int = 8          # indices 0..N-1 are probed in "auto"
    probe_timeout_s: float = 2.5      # per index
    reconnect_delay_s: float = 1.0
    stale_frame_ms: int = 1500        # health turns red when no frame for this long
    intrinsics_path: str | None = None  # OpenCV calibration JSON (K, dist); optional
    recording_fps: float = 30.0       # playback rate for directory/video sources


@dataclass
class BoardConfig:
    registration_path: str = str(DEFAULT_REGISTRATION_PATH)
    warp_px_per_mm: float = 2.0       # top-down board canvas resolution
    min_markers: int = 2              # with corner points; centres-only mode needs 4 (3 = affine)
    max_reprojection_rms_uv: float = 0.008   # ~3.4 mm on a 420 mm board; above = degraded
    registration_grace_ms: int = 4000        # keep the last good homography this long
    jump_tolerance_uv: float = 0.02          # a re-solve moving the board corners more than this
                                             # while markers are missing is treated as occlusion noise
    marker_exclusion_margin_mm: float = 6.0  # dilation around marker quads in the candidate mask
    redetect_every_n_frames: int = 1         # ArUco runs every frame by default (cheap at 720p)
    use_ransac_from_points: int = 8          # findHomography RANSAC when >= this many points
    ransac_reproj_threshold_px: float = 3.0


@dataclass
class CandidateConfig:
    reference_frames: int = 15               # median of N empty-board frames
    diff_threshold: int = 24                 # gain-matched absolute intensity difference
    chroma_threshold: int = 18               # Lab a/b difference; catches coloured pieces at equal luma
    gain_clip: tuple[float, float] = (0.7, 1.4)
    edge_assist: bool = True                 # add changed edges + fill holes (white piece on a pale print)
    min_area_mm2: float = 500.0              # smallest footprint accepted (hospital base is 2475 mm^2)
    max_area_mm2: float = 9000.0             # larger blobs are hands / sleeves / shadows across the board
    edge_touch_max_area_mm2: float = 3500.0  # a blob touching the board edge above this size is a hand
    open_kernel_mm: float = 2.0
    close_kernel_mm: float = 5.0
    structure_gate: bool = False             # projector-safe mode: also require edge-structure change
    structure_threshold: int = 25
    shadow_suppression: bool = True          # drop darker-only, chroma-preserving regions (cast shadows)
    shadow_min_ratio: float = 0.45           # darker than this fraction of the reference is NOT a shadow
    changed_fraction_warning: float = 0.4    # most of the board changed: lighting moved, re-reference
    exclusion_polygons_uv: list[list[list[float]]] = field(default_factory=list)  # known projected UI areas


@dataclass
class TrackerConfig:
    gate_mm: float = 30.0            # association gate in board mm (nearest neighbour)
    move_gate_mm: float = 6.0        # centre drift below this counts as "still"
    stable_frames: int = 12          # consecutive still frames before PLACED/MOVED is emitted
    occlusion_grace_frames: int = 20 # frames a track may be unmatched before REMOVED (~0.7 s at 30 fps)
    lost_candidate_frames: int = 8   # an unstable candidate vanishing this long is LOST (no world event)
    reacquire_window_ms: int = 4000  # a new track appearing near a just-removed one carries previous_track_id
    reacquire_radius_mm: float = 25.0
    jitter_window: int = 10          # frames used for position jitter / smoothing
    appearance_change_threshold: float = 0.35  # mean HSV distance (normalised) triggering reclassification
    max_tracks: int = 12


@dataclass
class ConfidenceConfig:
    """Weights for the honest local quality score (spec 5: label it as local fusion quality)."""

    good_reprojection_rms_uv: float = 0.003
    bad_reprojection_rms_uv: float = 0.010
    good_jitter_mm: float = 1.0
    bad_jitter_mm: float = 6.0
    high_band_min_localization: float = 0.6
    high_band_min_class_confidence: float = 0.6
    review_band_min_localization: float = 0.3


@dataclass
class ServiceConfig:
    session_prefix: str = "sess"
    jsonl_path: str | None = None          # append observations here (operator/evidence log)
    observe_url: str | None = None         # optional HTTP sink for the backend adapter
    status_url: str | None = None          # optional HTTP sink for status (operator status line)
    status_every_s: float = 1.0
    http_timeout_s: float = 2.0
    sink_queue_size: int = 256
    save_rois_dir: str | None = None       # write ROI crops for Dev 2 here
    record_dir: str | None = None          # record frames + events for reproducible tests
    record_every_n_frames: int = 3
    sites_path: str | None = None          # real scenario sites.json; DEBUG display of nearest pad only
    debug_window: bool = True
    show_warp: bool = True
    loop_sleep_s: float = 0.002
    auto_reference: bool = True            # capture the empty-board reference once registration is valid
    reference_settle_ms: int = 1500        # wait after first valid registration before auto reference
    candidate_emit_interval_ms: int = 500  # pending-outline cadence per unemitted track
    parallax_correction: str = "approximate"  # "intrinsics" | "approximate" | "off"
    parallax_max_correction_mm: float = 10.0   # larger corrections mean an implausible pose: skip, flag
    parallax_min_camera_height_mm: float = 400.0  # a solved camera closer than this to the board is not trusted
    max_seconds: float | None = None           # headless runs / smoke tests: stop after this long
    control_port: int | None = None            # operator/adapter control API (perception/control.py); None = off
    control_host: str = "127.0.0.1"
    piece_height_mm: dict = field(default_factory=lambda: {
        "bridge": 13.0, "hospital": 22.0, "shelter": 22.0, "food_station": 22.0, "unknown": 17.0})
    live_captures_dir: str = "assets/live_captures"


@dataclass
class PerceptionConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    board: BoardConfig = field(default_factory=BoardConfig)
    candidates: CandidateConfig = field(default_factory=CandidateConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def load(path: str | Path | None = None, env: dict[str, str] | None = None) -> "PerceptionConfig":
        cfg = PerceptionConfig()
        if path:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            _apply_overrides(cfg, data)
        _apply_env(cfg, os.environ if env is None else env)
        return cfg


_SECTIONS = ("camera", "board", "candidates", "tracker", "confidence", "service")


def _apply_overrides(cfg: PerceptionConfig, data: dict[str, Any]) -> None:
    for section in _SECTIONS:
        values = data.get(section) or {}
        target = getattr(cfg, section)
        allowed = {f.name for f in fields(target)}
        for key, value in values.items():
            if key not in allowed:
                raise ValueError(f"unknown config key {section}.{key}")
            setattr(target, key, _coerce(getattr(target, key), value))


def _apply_env(cfg: PerceptionConfig, env: dict[str, str]) -> None:
    """``FLOODSHIFT_PERCEPTION_CAMERA_SOURCE=1`` -> ``cfg.camera.source = "1"``."""
    for section in _SECTIONS:
        target = getattr(cfg, section)
        for f in fields(target):
            name = f"{ENV_PREFIX}{section.upper()}_{f.name.upper()}"
            if name in env:
                setattr(target, f.name, _coerce(getattr(target, f.name), env[name]))


def _coerce(current: Any, value: Any) -> Any:
    if value is None or current is None:
        return value
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, tuple):
        if isinstance(value, str):
            value = json.loads(value)
        return tuple(type(current[0])(v) for v in value)
    if isinstance(current, list):
        if isinstance(value, str):
            value = json.loads(value)
        return list(value)
    return value if not isinstance(current, str) else str(value)
