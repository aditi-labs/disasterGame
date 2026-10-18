"""Perception service runner (spec section 4 ``perception/service.py``, section 6).

Camera thread -> board registration -> top-down warp -> candidates -> tracker ->
typed observations -> non-blocking sinks.  Classification is delegated to a
pluggable :class:`ClassifierPort` (Lane C) and never blocks this loop.

Run::

    python -m perception.service --list-cameras
    python -m perception.service --calibrate            # measure the real board markers
    python -m perception.service --source auto --jsonl runs/obs.jsonl
    python -m perception.service --source http://192.168.1.20:4747/video   # DroidCam MJPEG
    python -m perception.service --source assets/live_captures/run1/frames  # replay a recording

Operator keys in the debug window: Q quit, R re-capture empty-board reference,
C recalibrate (drop held registration), N new session (reset tracks/bindings),
P pause/resume, X clear pending candidates, E re-emit the latest still track,
S save the raw frame to assets/live_captures, W toggle warp view, M toggle change
mask, G toggle projector-safe structure gate.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Protocol
import uuid

import numpy as np

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from . import __version__
from .board_aruco import (
    BoardRegistrar,
    BoardRegistration,
    MEASURED_STATUS,
    RegistrationState,
    scan_dictionaries,
    summarize_for_measurement,
)
from .camera import CameraWorker, Frame, enumerate_cameras, open_source
from .candidate_regions import Candidate, CandidateDetector, crop_roi, prepare_roi
from .config import PerceptionConfig, REPO_ROOT
from .confidence import score
from .control import ControlServer
from .debug_view import draw_camera_view, draw_warp_view, load_sites
from .events import (
    BoardUV,
    ClassificationResult,
    ConfidenceBand,
    GeometryQuality,
    Lifecycle,
    ObservationSource,
    PhysicalObservation,
    ROIRequest,
    make_event_id,
    now_ms,
)
from .geometry import BoardGeometry, parallax_correct_mm, warp_board
from .intrinsics import Intrinsics, Undistorter
from .sinks import CallbackSink, FanoutSink, HttpPoster, HttpSink, JsonlSink, ObservationSink, StdoutSink
from .tracker import PieceTracker, Track, TrackEvent, TrackState


# --------------------------------------------------------------------- classifier port
class ClassifierPort(Protocol):
    """What Lane C plugs in.  ``submit`` must return immediately."""

    def submit(self, request: ROIRequest) -> None: ...
    def poll(self) -> list[ClassificationResult]: ...
    def status(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


class NullClassifier:
    """No classifier attached: every track stays unclassified (REVIEW band, never auto-commit)."""

    def __init__(self) -> None:
        self.submitted = 0

    def submit(self, request: ROIRequest) -> None:
        self.submitted += 1

    def poll(self) -> list[ClassificationResult]:
        return []

    def status(self) -> dict[str, Any]:
        return {"kind": "none", "available": False, "submitted": self.submitted,
                "note": "no classifier attached; classes come only from the operator"}

    def close(self) -> None:
        pass


def load_classifier(spec: str | None) -> ClassifierPort:
    """``module.path:factory`` -> ClassifierPort instance (Dev 2 supplies the factory)."""
    if not spec:
        return NullClassifier()
    module_name, _, attr = spec.partition(":")
    module = importlib.import_module(module_name)
    factory = getattr(module, attr or "create_classifier")
    return factory()


class RoiArchiver:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def save(self, request: ROIRequest) -> Path:
        name = f"{request.session_id}_{request.track_id}_{request.frame_id:06d}_{request.reason}.png"
        path = self.dir / name
        cv2.imwrite(str(path), request.crop_bgr)
        meta = {k: v for k, v in request.__dict__.items() if k != "crop_bgr"}
        meta["board_uv"] = request.board_uv.as_dict() if request.board_uv else None
        path.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        self.count += 1
        return path


class Recorder:
    """Writes frames + events + status so a live run can be replayed as a test (spec 10)."""

    def __init__(self, directory: str | Path, every_n_frames: int, manifest: dict[str, Any]):
        self.dir = Path(directory)
        self.frames_dir = self.dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.every = max(1, every_n_frames)
        self.events = (self.dir / "events.jsonl").open("a", encoding="utf-8")
        self.status_log = (self.dir / "status.jsonl").open("a", encoding="utf-8")
        (self.dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        self.frames_written = 0

    def frame(self, frame: Frame) -> None:
        if frame.frame_id % self.every == 0:
            cv2.imwrite(str(self.frames_dir / f"{frame.frame_id:06d}.jpg"), frame.image, [cv2.IMWRITE_JPEG_QUALITY, 92])
            self.frames_written += 1

    def event(self, observation: PhysicalObservation) -> None:
        self.events.write(observation.to_json() + "\n")
        self.events.flush()

    def status(self, status: dict[str, Any]) -> None:
        self.status_log.write(json.dumps(status, default=str) + "\n")
        self.status_log.flush()

    def close(self) -> None:
        self.events.close()
        self.status_log.close()


# --------------------------------------------------------------------- service
@dataclass
class TrackView:
    track_id: str
    state: str
    uv: tuple[float, float] | None
    raw_uv: tuple[float, float] | None
    band: str | None
    piece_class: str | None


class PerceptionService:
    def __init__(self, cfg: PerceptionConfig, *, classifier: ClassifierPort | None = None,
                 sinks: list[ObservationSink] | None = None, registration: BoardRegistration | None = None):
        if cv2 is None:
            raise ImportError("opencv-contrib-python is required")
        self.cfg = cfg
        self.registration = registration or BoardRegistration.load(cfg.board.registration_path)
        self.geometry: BoardGeometry = self.registration.geometry(cfg.board.warp_px_per_mm)
        self.intrinsics: Intrinsics | None = None
        self.undistorter: Undistorter | None = None
        if cfg.camera.intrinsics_path:
            self.intrinsics = Intrinsics.load(cfg.camera.intrinsics_path)
            self.undistorter = Undistorter(self.intrinsics)
        self.registrar = BoardRegistrar(
            self.registration, min_markers=cfg.board.min_markers, max_rms_uv=cfg.board.max_reprojection_rms_uv,
            grace_ms=cfg.board.registration_grace_ms, jump_tolerance_uv=cfg.board.jump_tolerance_uv,
            ransac_from_points=cfg.board.use_ransac_from_points, ransac_threshold_px=cfg.board.ransac_reproj_threshold_px,
        )
        self.detector = CandidateDetector(cfg.candidates, self.geometry)
        self.detector.set_static_exclusions(self.registrar.registered_marker_polygons_uv(),
                                            cfg.candidates.exclusion_polygons_uv,
                                            marker_margin_mm=cfg.board.marker_exclusion_margin_mm)
        self.tracker = PieceTracker(cfg.tracker)
        self.classifier: ClassifierPort = classifier or NullClassifier()
        self.sink = FanoutSink(list(sinks or []))
        self.session_id = self._new_session_id()
        self.sites = load_sites(cfg.service.sites_path)
        self.roi_archiver = RoiArchiver(cfg.service.save_rois_dir) if cfg.service.save_rois_dir else None
        self.recorder: Recorder | None = None
        self.status_poster: HttpPoster | None = HttpPoster(cfg.service.status_url, timeout_s=cfg.service.http_timeout_s,
                                                           queue_size=16, name="status-sink") if cfg.service.status_url else None
        self.camera: CameraWorker | None = None
        self.control: ControlServer | None = None
        if cfg.service.control_port is not None:
            self.control = ControlServer(self, cfg.service.control_host, cfg.service.control_port).start()
        self.registration_state: RegistrationState | None = None
        self.last_frame: Frame | None = None
        self.last_warped: np.ndarray | None = None
        self.last_candidates: list[Candidate] = []
        self.paused = False
        self.warnings: list[str] = []
        self.track_views: dict[str, TrackView] = {}
        self.last_band: dict[str, ConfidenceBand] = {}
        self.last_candidate_emit_ms: dict[str, int] = {}
        self.last_observation: PhysicalObservation | None = None
        self.observations_emitted = 0
        self._reference_pending = cfg.service.auto_reference
        self._reference_buffer: list[np.ndarray] = []
        self._first_valid_ms: int | None = None
        self._reference_requested_manually = False
        self._process_times: list[float] = []
        self._stage_times: dict[str, deque] = {k: deque(maxlen=120) for k in
                                               ("aruco", "warp", "candidates", "tracker", "classify", "total")}
        self._cadence = max(1, cfg.board.redetect_every_n_frames)
        self._frames_seen = 0
        self._last_status_post = 0.0
        self._approx_intrinsics_set_for: tuple[int, int] | None = None

    # ---------------------------------------------------------------- lifecycle
    def _new_session_id(self) -> str:
        return f"{self.cfg.service.session_prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    def start(self) -> "PerceptionService":
        source = open_source(self.cfg.camera.source, self.cfg.camera.width, self.cfg.camera.height,
                             probe_max_index=self.cfg.camera.probe_max_index,
                             probe_timeout_s=self.cfg.camera.probe_timeout_s,
                             recording_fps=self.cfg.camera.recording_fps)
        self.camera = CameraWorker(source, stale_frame_ms=self.cfg.camera.stale_frame_ms,
                                   reconnect_delay_s=self.cfg.camera.reconnect_delay_s,
                                   undistort=self.undistorter).start()
        if self.cfg.service.record_dir:
            self.recorder = Recorder(self.cfg.service.record_dir, self.cfg.service.record_every_n_frames, {
                "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "session_id": self.session_id,
                "source": source.describe(), "is_recording_source": source.is_recording,
                "registration": self.registration.to_json_dict(), "config": self.cfg.as_dict(),
                "perception_version": __version__,
            })
        return self

    def stop(self) -> None:
        if self.camera is not None:
            self.camera.stop()
        if self.control is not None:
            self.control.stop()
        self.sink.close()
        self.classifier.close()
        if self.status_poster is not None:
            self.status_poster.close()
        if self.recorder is not None:
            self.recorder.close()

    # ---------------------------------------------------------------- operator API
    def capture_reference(self) -> None:
        """Operator says the board is empty: rebuild the change reference from the next frames."""
        self._reference_pending = True
        self._reference_requested_manually = True
        self._reference_buffer.clear()
        self.detector.reference.clear()
        self.tracker.clear_pending()
        self._first_valid_ms = None

    def reset_session(self) -> str:
        """RESET GAME / REPLAY: clear tracks, bindings, pending flags and caches; keep hardware."""
        self.tracker.reset()
        self.track_views.clear()
        self.last_band.clear()
        self.last_candidate_emit_ms.clear()
        self.session_id = self._new_session_id()
        return self.session_id

    def recalibrate(self) -> None:
        """RECALIBRATE: drop the held/smoothed registration so the next frame re-solves cleanly."""
        self.registrar.reset_hold()

    def clear_pending(self, track_id: str | None = None) -> int:
        return self.tracker.clear_pending(track_id)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_projected_exclusions(self, polygons_uv: list[list[list[float]]]) -> None:
        """UI lane can declare where it is projecting UI so those areas are never candidates."""
        self.cfg.candidates.exclusion_polygons_uv = polygons_uv
        self.detector.set_static_exclusions(self.registrar.registered_marker_polygons_uv(), polygons_uv,
                                            marker_margin_mm=self.cfg.board.marker_exclusion_margin_mm)

    def bind_world_token(self, track_id: str, world_token_id: str) -> None:
        self.tracker.bind_world_token(track_id, world_token_id)

    def mark_rejected(self, track_id: str, reason: str) -> None:
        self.tracker.mark_rejected(track_id, reason, now_ms())

    def unbind_world_token(self, track_id: str) -> None:
        self.tracker.unbind_world_token(track_id)

    def handle_adapter_feedback(self, feedback: dict[str, Any]) -> None:
        """Proposed adapter response: {track_id, accepted, world_token_id?, rejection_reason?}."""
        track_id = feedback.get("track_id")
        if not track_id:
            return
        if feedback.get("accepted"):
            token = feedback.get("world_token_id")
            if token:
                self.bind_world_token(str(track_id), str(token))
            if feedback.get("removed"):
                self.unbind_world_token(str(track_id))
        else:
            self.mark_rejected(str(track_id), str(feedback.get("rejection_reason") or "rejected"))

    def apply_operator_class(self, track_id: str, piece_class: str, operator: str = "operator") -> bool:
        """Operator identifies a piece by eye; recorded with source 'operator', never 'perceptron'."""
        from .events import PieceClass
        result = ClassificationResult(track_id=track_id, piece_class=PieceClass(piece_class),
                                      class_source=operator, confidence=None, valid=True, evidence="operator")
        applied = self.tracker.apply_classification(result, now_ms())
        return applied

    def request_reemit(self, track_id: str | None = None) -> PhysicalObservation | None:
        """Operator retry: re-emit the latest still track (or the given one) without moving it."""
        if track_id is None:
            still = [t for t in self.tracker.tracks.values() if t.state == TrackState.STABLE]
            if not still:
                return None
            track_id = max(still, key=lambda t: t.last_seen_ms).track_id
        frame_id = self.last_frame.frame_id if self.last_frame else 0
        event = self.tracker.request_reemit(track_id, now_ms(), frame_id)
        if event is None or self.registration_state is None or self.last_frame is None:
            return None
        obs = self._observation_from_event(event, self.registration_state, self.last_frame)
        self._emit(obs)
        return obs

    def save_capture(self) -> Path | None:
        if self.last_frame is None:
            return None
        directory = REPO_ROOT / self.cfg.service.live_captures_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.session_id}_f{self.last_frame.frame_id:06d}.jpg"
        cv2.imwrite(str(path), self.last_frame.image)
        return path

    # ---------------------------------------------------------------- per frame
    def process_frame(self, frame: Frame) -> list[PhysicalObservation]:
        t0 = time.perf_counter()
        if self.control is not None:
            self.control.apply_pending()
        now = frame.captured_at_ms
        self.last_frame = frame
        image = frame.image
        self._ensure_pose_intrinsics(image.shape[1], image.shape[0])
        self._frames_seen += 1
        t_stage = time.perf_counter()
        prev = self.registration_state
        # ArUco cadence: between detections the last registration is reused (its age keeps
        # counting); a missing/invalid registration is always re-tried on the next frame.
        if prev is None or not prev.valid or self._frames_seen % self._cadence == 0:
            reg = self.registrar.update(image, now)
        else:
            reg = prev
        self._stage_times["aruco"].append(time.perf_counter() - t_stage)
        self.registration_state = reg
        self.last_candidates = []
        warped = None
        reference_ok = self.detector.reference_ready

        if reg.valid and reg.homography is not None:
            t_stage = time.perf_counter()
            warped = warp_board(image, reg.homography, self.geometry)
            self._stage_times["warp"].append(time.perf_counter() - t_stage)
            self.last_warped = warped
            if self._reference_pending:
                reference_ok = self._collect_reference(warped, now, reg)
            if reference_ok and not self.paused:
                t_stage = time.perf_counter()
                self.last_candidates = self.detector.detect(warped)
                self._stage_times["candidates"].append(time.perf_counter() - t_stage)
                if self.detector.changed_fraction > self.cfg.candidates.changed_fraction_warning:
                    self._warn("most of the board differs from the reference (lighting/projector changed?) - press R on an empty board")
                else:
                    self._unwarn("most of the board differs")
        else:
            self.last_warped = None

        # Tracks age only while the board is actually in view: a held registration with zero
        # visible markers (camera covered/unplugged) must not turn into invented removals.
        registration_ok = bool(reg.board_in_view and reference_ok and not self.paused)
        if reg.valid and not reg.board_in_view:
            self.last_candidates = []
        t_stage = time.perf_counter()
        events = self.tracker.update(self.last_candidates, now, frame.frame_id, registration_ok=registration_ok)
        observations = [self._observation_from_event(e, reg, frame) for e in events]
        self._stage_times["tracker"].append(time.perf_counter() - t_stage)

        if registration_ok:
            t_stage = time.perf_counter()
            observations.extend(self._pending_candidate_observations(reg, frame, now))
            observations.extend(self._apply_classifier_results(reg, frame, now))
            if warped is not None:
                self._request_classifications(warped, frame, now)
            self._stage_times["classify"].append(time.perf_counter() - t_stage)

        for obs in observations:
            self._emit(obs)
        self._refresh_track_views(reg)
        if self.recorder is not None:
            self.recorder.frame(frame)
        total = time.perf_counter() - t0
        self._process_times.append(total)
        self._process_times = self._process_times[-60:]
        self._stage_times["total"].append(total)
        self._adapt_cadence()
        return observations

    def _adapt_cadence(self) -> None:
        """Raise the ArUco cadence when the loop falls behind real time, lower it when it recovers."""
        cfg = self.cfg.board
        if not cfg.adaptive_cadence or self._frames_seen % 30 != 0 or len(self._process_times) < 30:
            return
        budget_s = 1.0 / max(1.0, cfg.target_fps)
        avg = sum(self._process_times[-30:]) / 30.0
        base = max(1, cfg.redetect_every_n_frames)
        if avg > budget_s and self._cadence < max(base, cfg.adaptive_cadence_max):
            self._cadence += 1
            self._warn(f"loop at {avg * 1000:.0f} ms/frame: ArUco every {self._cadence} frames")
        elif avg < 0.6 * budget_s and self._cadence > base:
            self._cadence -= 1
            self._unwarn("loop at")

    def timing_summary(self) -> dict[str, dict[str, float | None]]:
        out: dict[str, dict[str, float | None]] = {}
        for name, times in self._stage_times.items():
            vals = sorted(times)
            if not vals:
                out[name] = {"p50_ms": None, "p95_ms": None}
                continue
            out[name] = {"p50_ms": round(vals[len(vals) // 2] * 1000, 2),
                         "p95_ms": round(vals[min(len(vals) - 1, int(len(vals) * 0.95))] * 1000, 2)}
        return out

    def _ensure_pose_intrinsics(self, width: int, height: int) -> None:
        mode = self.cfg.service.parallax_correction
        if mode == "off":
            return
        if self.intrinsics is not None and not self.intrinsics.approximate:
            if self.registrar.camera_matrix is None:
                k = self.undistorter.new_camera_matrix if self.undistorter else self.intrinsics.camera_matrix
                self.registrar.camera_matrix = k
                self.registrar.dist_coeffs = np.zeros(5)  # frames are undistorted before detection
                self.registrar.intrinsics_approximate = False
            return
        if mode == "approximate" and self._approx_intrinsics_set_for != (width, height):
            approx = Intrinsics.approximate_for(width, height)
            self.registrar.camera_matrix = approx.camera_matrix
            self.registrar.dist_coeffs = approx.dist_coeffs
            self.registrar.intrinsics_approximate = True
            self._approx_intrinsics_set_for = (width, height)

    def _collect_reference(self, warped: np.ndarray, now: int, reg: RegistrationState) -> bool:
        if reg.held or reg.degraded:
            return False  # do not build a reference through a degraded registration
        if self._first_valid_ms is None:
            self._first_valid_ms = now
        settle = 0 if self._reference_requested_manually else self.cfg.service.reference_settle_ms
        if now - self._first_valid_ms < settle:
            return False
        self._reference_buffer.append(warped.copy())
        if len(self._reference_buffer) >= self.cfg.candidates.reference_frames:
            self.detector.capture_reference(self._reference_buffer, now)
            self._reference_buffer.clear()
            self._reference_pending = False
            self._reference_requested_manually = False
            return True
        return False

    # ---------------------------------------------------------------- observations
    def _track_uv(self, track: Track, reg: RegistrationState, center_mm: tuple[float, float] | None = None
                  ) -> tuple[BoardUV | None, BoardUV | None, float | None, float | None]:
        """(corrected uv, raw plane uv, correction_mm, assumed_height_mm)."""
        if not reg.valid or reg.homography is None:
            return None, None, None, None
        mm = np.asarray(center_mm if center_mm is not None else track.center_mm, dtype=np.float64)
        raw_uv = self.geometry.mm_to_uv(mm)
        raw = BoardUV(float(raw_uv[0]), float(raw_uv[1]))
        pose = reg.camera_pose
        svc = self.cfg.service
        if pose is None or svc.parallax_correction == "off":
            return raw, raw, None, None
        if pose.position_mm[2] < svc.parallax_min_camera_height_mm:
            self._warn("camera pose implausible (height %.0f mm): parallax correction skipped" % pose.position_mm[2])
            return raw, raw, None, None
        cls = track.classification.piece_class.value if track.classification.piece_class else "unknown"
        height = float(svc.piece_height_mm.get(cls, svc.piece_height_mm.get("unknown", 17.0)))
        corrected_mm = parallax_correct_mm(mm, pose.position_mm, height)
        correction = float(np.linalg.norm(corrected_mm - mm))
        if correction > svc.parallax_max_correction_mm:
            self._warn("parallax correction %.1f mm exceeds limit: skipped (check intrinsics/camera height)" % correction)
            return raw, raw, None, None
        self._unwarn("parallax correction")
        self._unwarn("camera pose implausible")
        uv = self.geometry.mm_to_uv(corrected_mm)
        return BoardUV(float(uv[0]), float(uv[1])), raw, correction, height

    def _geometry_quality(self, track: Track, cand: Candidate | None, reg: RegistrationState, now: int,
                          correction: float | None, height: float | None) -> GeometryQuality:
        jitter_uv = track.jitter_mm() / max(self.registration.board_width_mm, self.registration.board_height_mm)
        return GeometryQuality(
            markers_used=len(reg.markers_used),
            reprojection_rms_uv=reg.rms_uv,
            reprojection_rms_px=reg.rms_px,
            registration_age_ms=reg.age_ms(now),
            registration_held=reg.held,
            position_jitter_uv=float(jitter_uv),
            frames_observed=track.frames_observed,
            frames_stable=track.frames_stable,
            area_mm2=None if cand is None else cand.area_mm2,
            bbox_mm=None if cand is None else cand.bbox_mm,
            elongation=None if cand is None else cand.elongation,
            touches_board_edge=bool(cand.touches_board_edge) if cand is not None else False,
            parallax_correction_mm=correction,
            assumed_height_mm=height,
            camera_pose_approximate=None if reg.camera_pose is None else reg.camera_pose.approximate,
        )

    def _source(self, frame: Frame) -> ObservationSource:
        return ObservationSource.RECORDING if frame.provenance.startswith("recording:") else ObservationSource.LIVE_CAMERA

    def _observation_from_event(self, event: TrackEvent, reg: RegistrationState, frame: Frame) -> PhysicalObservation:
        track = event.track
        uv, raw_uv, correction, height = self._track_uv(track, reg, event.center_mm)
        geometry = self._geometry_quality(track, event.candidate, reg, event.at_ms, correction, height)
        scored = score(track, event.lifecycle, uv, reg, geometry, self.cfg.confidence,
                       board_mm=(self.registration.board_width_mm, self.registration.board_height_mm))
        cls = track.classification
        camera_px = None
        if reg.valid and reg.homography is not None and raw_uv is not None:
            from .geometry import uv_to_camera_px
            px = uv_to_camera_px(reg.homography, [(raw_uv.u, raw_uv.v)])[0]
            camera_px = (float(px[0]), float(px[1]))
        reason = scored.reason if not event.note else f"{event.note}; {scored.reason}"
        obs = PhysicalObservation(
            event_id=make_event_id(self.session_id, track.track_id, event.lifecycle, event.emission_index),
            session_id=self.session_id,
            track_id=track.track_id,
            piece_class=cls.piece_class if cls.valid else None,
            lifecycle=event.lifecycle,
            board_uv=uv,
            detection_confidence=scored.detection,
            localization_confidence=scored.localization,
            confidence_band=scored.band,
            observed_at_ms=event.at_ms,
            source=self._source(frame),
            orientation_deg=None if event.candidate is None else event.candidate.orientation_deg,
            class_source=cls.class_source if cls.valid else None,
            class_confidence=cls.confidence if cls.valid else None,
            frame_id=event.frame_id,
            camera_px=camera_px,
            previous_track_id=track.previous_track_id,
            geometry=geometry,
            appearance=None if event.candidate is None else event.candidate.appearance,
            frame_provenance=frame.provenance,
            reason=reason,
        )
        if event.lifecycle in (Lifecycle.PLACED, Lifecycle.MOVED):
            self.last_band[track.track_id] = scored.band
        return obs

    def _pending_candidate_observations(self, reg: RegistrationState, frame: Frame, now: int) -> list[PhysicalObservation]:
        out = []
        interval = self.cfg.service.candidate_emit_interval_ms
        for track in list(self.tracker.tracks.values()):
            if track.emitted or track.frames_missing > 0 or track.state == TrackState.RETIRED:
                continue
            last = self.last_candidate_emit_ms.get(track.track_id)
            if last is not None and now - last < interval:
                continue
            self.last_candidate_emit_ms[track.track_id] = now
            track.emissions += 1
            event = TrackEvent(track, Lifecycle.CANDIDATE, track.emissions, frame.frame_id, now, track.center_mm,
                               track.last_candidate, "pending")
            out.append(self._observation_from_event(event, reg, frame))
        return out

    def _apply_classifier_results(self, reg: RegistrationState, frame: Frame, now: int) -> list[PhysicalObservation]:
        out = []
        for result in self.classifier.poll():
            applied = self.tracker.apply_classification(result, now)
            track = self.tracker.tracks.get(result.track_id)
            if not applied or track is None or not result.valid:
                continue
            # A class arriving after the track was already emitted: re-emit so the adapter can act,
            # but only if the earlier emission could not be acted on (not HIGH) and it is still there.
            if track.emitted and track.state == TrackState.STABLE and self.last_band.get(track.track_id) != ConfidenceBand.HIGH:
                lifecycle = Lifecycle.MOVED if track.bound else Lifecycle.PLACED
                event = self.tracker.request_reemit(track.track_id, now, frame.frame_id, note="class_update")
                if event is not None:
                    event.lifecycle = lifecycle
                    out.append(self._observation_from_event(event, reg, frame))
        return out

    def _request_classifications(self, warped: np.ndarray, frame: Frame, now: int) -> None:
        can_accept = getattr(self.classifier, "can_accept", None)
        for track in self.tracker.tracks_needing_classification():
            if callable(can_accept) and not can_accept():
                break  # bounded in-flight requests: the track simply asks again on a later frame
            cand = track.last_candidate
            if cand is None:
                continue
            crop, bbox = crop_roi(warped, cand.bbox_warp_px, pad_px=int(self.geometry.mm_to_px_len(6.0)))
            crop = prepare_roi(crop, cand.orientation_deg, max_px=self.cfg.service.roi_max_px,
                               canonical_rotation=self.cfg.service.roi_canonical_rotation)
            uv, _, _, _ = self._track_uv(track, self.registration_state) if self.registration_state else (None, None, None, None)
            request = ROIRequest(
                request_id=uuid.uuid4().hex[:12], session_id=self.session_id, track_id=track.track_id,
                frame_id=frame.frame_id, crop_bgr=crop, crop_bbox_warp_px=bbox, board_uv=uv,
                orientation_deg=cand.orientation_deg, observed_at_ms=now, reason=track.classification_reason,
                frame_provenance=frame.provenance,
            )
            self.tracker.mark_classification_requested(track.track_id, request.request_id)
            if self.roi_archiver is not None:
                self.roi_archiver.save(request)
            self.classifier.submit(request)

    def _emit(self, obs: PhysicalObservation) -> None:
        self.observations_emitted += 1
        self.last_observation = obs
        self.sink.emit(obs)
        if self.recorder is not None:
            self.recorder.event(obs)

    def _refresh_track_views(self, reg: RegistrationState) -> None:
        views: dict[str, TrackView] = {}
        for track in self.tracker.tracks.values():
            uv, raw, _, _ = self._track_uv(track, reg)
            band = self.last_band.get(track.track_id)
            views[track.track_id] = TrackView(
                track.track_id, track.state.value,
                None if uv is None else (uv.u, uv.v), None if raw is None else (raw.u, raw.v),
                None if band is None else band.value,
                track.classification.piece_class.value if track.classification.valid and track.classification.piece_class else None,
            )
        self.track_views = views

    def _warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    def _unwarn(self, prefix: str) -> None:
        self.warnings = [w for w in self.warnings if not w.startswith(prefix)]

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        now = now_ms()
        reg = self.registration_state
        proc_ms = (sum(self._process_times) / len(self._process_times) * 1000.0) if self._process_times else None
        classifier_status = self.classifier.status()
        cam_health = self.camera.health().as_dict() if self.camera else {"connected": False, "source": self.cfg.camera.source}
        if reg is None or not reg.valid:
            calibration = "uncalibrated"
        elif reg.held or reg.degraded:
            calibration = "held" if reg.held else "degraded"
        elif self.registration.verified:
            calibration = "calibrated"
        else:
            calibration = "valid_unmeasured"
        if classifier_status.get("kind") == "none":
            perceptron = "not_connected"
        else:
            perceptron = "ready" if classifier_status.get("available") else "degraded"
        return {
            # Flat keys the retained gateway (/perception/status, /health) and spec section 9 status line read.
            # They never overstate: a photo-estimated registration is "valid_unmeasured", never "calibrated".
            "mode": ("recording" if (self.last_frame is not None and self.last_frame.provenance.startswith("recording:"))
                     or str(cam_health.get("source", "")).startswith("recording:") else "live"),
            "calibration": calibration,
            "perceptron": perceptron,
            "objects_tracked": len(self.tracker.tracks),
            "perception_version": __version__,
            "session_id": self.session_id,
            "paused": self.paused,
            "camera": cam_health,
            "control": self.control.status() if self.control else None,
            "undistortion": "measured_intrinsics" if self.undistorter else "none",
            "parallax_correction": self.cfg.service.parallax_correction,
            "registration": reg.as_status(now, self.registration) if reg else {"valid": False, "reason": "no frame yet",
                                                                                 "registration_status": self.registration.status,
                                                                                 "registration_verified": self.registration.verified},
            "reference": {"ready": self.detector.reference_ready, "pending": self._reference_pending,
                          "captured_at_ms": self.detector.reference.captured_at_ms,
                          "frames": self.detector.reference.frame_count,
                          "changed_fraction": round(self.detector.changed_fraction, 3)},
            "candidates": len(self.last_candidates),
            "tracks": self.tracker.snapshot(),
            "classifier": classifier_status,
            "sinks": self.sink.status(),
            "status_sink": self.status_poster.status() if self.status_poster else None,
            "observations_emitted": self.observations_emitted,
            "processing_ms_avg": None if proc_ms is None else round(proc_ms, 1),
            "timing": self.timing_summary(),
            "aruco_cadence": self._cadence,
            "warnings": list(self.warnings),
            "structure_gate": self.cfg.candidates.structure_gate,
            "board_mm": [self.registration.board_width_mm, self.registration.board_height_mm],
            "scenario_id": self.registration.scenario_id,
        }

    def _maybe_post_status(self) -> None:
        if time.monotonic() - self._last_status_post < self.cfg.service.status_every_s:
            return
        self._last_status_post = time.monotonic()
        status = self.status()
        if self.status_poster is not None:
            self.status_poster.post(status)
        if self.recorder is not None:
            self.recorder.status(status)

    # ---------------------------------------------------------------- main loop
    def status_lines(self) -> list[str]:
        s = self.status()
        cam, reg, ref = s["camera"], s["registration"], s["reference"]
        lines = [
            f"FLOODSHIFT perception {__version__} | session {s['session_id']} | {'PAUSED' if self.paused else 'running'}",
            f"camera {'OK' if cam.get('connected') else 'DOWN'} {cam.get('source')} {cam.get('width')}x{cam.get('height')} "
            f"{cam.get('fps_measured')}fps proc {s['processing_ms_avg']}ms p95 {s['timing']['total']['p95_ms']}ms "
            f"(aruco {s['timing']['aruco']['p50_ms']} cand {s['timing']['candidates']['p50_ms']} every {s['aruco_cadence']}f)",
            f"registration {'VALID' if reg.get('valid') else 'NONE'}{' HELD' if reg.get('held') else ''}"
            f"{' DEGRADED' if reg.get('degraded') else ''} markers {reg.get('markers_used')}/{reg.get('markers_expected')} "
            f"rms {reg.get('reprojection_rms_uv')}uv {reg.get('reprojection_rms_px')}px "
            f"[{reg.get('registration_status')}{'' if reg.get('registration_verified') else ' - NOT VERIFIED ON BOARD'}]",
            f"reference {'ready' if ref['ready'] else ('capturing...' if ref['pending'] else 'MISSING (press R)')} "
            f"changed {ref['changed_fraction']} | candidates {s['candidates']} tracks {len(s['tracks'])} "
            f"| classifier {s['classifier'].get('kind')} {'available' if s['classifier'].get('available') else 'unavailable'}",
        ]
        if reg.get("unknown_ids_seen"):
            lines.append(f"unregistered marker ids visible: {reg['unknown_ids_seen']}")
        if reg.get("reason") and reg.get("reason") != "ok":
            lines.append(f"registration note: {reg['reason']}")
        for w in self.warnings[:3]:
            lines.append(f"WARNING: {w}")
        if self.last_observation is not None:
            o = self.last_observation
            uv = "-" if o.board_uv is None else f"({o.board_uv.u:.3f},{o.board_uv.v:.3f})"
            lines.append(f"last event: {o.track_id} {o.lifecycle.value} {o.piece_class.value if o.piece_class else '?'} "
                         f"{uv} [{o.confidence_band.value}] {o.reason}")
        return lines

    def run(self) -> int:
        if self.camera is None:
            self.start()
        assert self.camera is not None
        show = self.cfg.service.debug_window
        show_warp = self.cfg.service.show_warp
        show_mask = False
        keys = "Q quit R reference C recal N new-session P pause X clear-pending E re-emit S save W warp M mask G struct-gate"
        print(f"[perception] source={self.camera.source.describe()} registration={self.registration.status} "
              f"(verified={self.registration.verified}) dictionary={self.registration.dictionary} "
              f"markers={sorted(self.registration.markers)} size_mm={self.registration.marker_size_mm}")
        if not self.registration.verified:
            print("[perception] WARNING: board registration is NOT verified on the physical board. "
                  "Run `python -m perception.service --calibrate` over the real board first.")
        first = self.camera.wait_for_frame(10.0)
        if first is None:
            print("[perception] ERROR: no frame from camera within 10 s", file=sys.stderr)
            return 2
        self.process_frame(first)
        started = time.monotonic()
        try:
            while True:
                if self.cfg.service.max_seconds is not None and time.monotonic() - started >= self.cfg.service.max_seconds:
                    print(f"[perception] max_seconds reached; status: {json.dumps(self.status(), default=str)[:1500]}")
                    break
                frame = self.camera.latest()
                if frame is None:
                    if self.camera.ended:
                        print("[perception] recording ended")
                        break
                    time.sleep(self.cfg.service.loop_sleep_s)
                    if show:
                        self._pump_keys(1)
                    continue
                self.process_frame(frame)
                self._maybe_post_status()
                if show:
                    view = draw_camera_view(frame.image, self.registration_state, self.geometry,
                                            [v.__dict__ for v in self.track_views.values()], self.status_lines(),
                                            self.sites, keys)
                    cv2.imshow("FLOODSHIFT perception (operator)", view)
                    if show_warp:
                        warp_view = draw_warp_view(self.last_warped, self.detector.last_change_mask, self.last_candidates,
                                                   [v.__dict__ for v in self.track_views.values()], self.geometry,
                                                   self.detector.static_exclusion_mask, show_mask)
                        if warp_view is not None:
                            cv2.imshow("FLOODSHIFT board plane (operator)", warp_view)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        break
                    if key == ord("r"):
                        self.capture_reference()
                        print("[perception] reference capture requested: keep the board EMPTY")
                    elif key == ord("c"):
                        self.recalibrate()
                    elif key == ord("n"):
                        print(f"[perception] new session {self.reset_session()}")
                    elif key == ord("p"):
                        self.set_paused(not self.paused)
                    elif key == ord("x"):
                        print(f"[perception] cleared {self.clear_pending()} pending candidate(s)")
                    elif key == ord("e"):
                        obs = self.request_reemit()
                        print(f"[perception] re-emitted {obs.event_id if obs else 'nothing (no still track)'}")
                    elif key == ord("s"):
                        print(f"[perception] saved {self.save_capture()}")
                    elif key == ord("w"):
                        show_warp = not show_warp
                        if not show_warp:
                            cv2.destroyWindow("FLOODSHIFT board plane (operator)")
                    elif key == ord("m"):
                        show_mask = not show_mask
                    elif key == ord("g"):
                        self.cfg.candidates.structure_gate = not self.cfg.candidates.structure_gate
                        print(f"[perception] structure gate {'ON' if self.cfg.candidates.structure_gate else 'off'}")
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            if show:
                cv2.destroyAllWindows()
        return 0

    def _pump_keys(self, ms: int) -> None:
        cv2.waitKey(ms)


# --------------------------------------------------------------------- calibrate flow
def run_calibrate(cfg: PerceptionConfig, registration: BoardRegistration, *, measured_by: str | None,
                  write_after_s: float | None, output: Path | None) -> int:
    """Measure what is really on the board (spec 6.2/6.3, docs/BOARD_REGISTRATION.md).

    Shows every dictionary that finds markers, the IDs it finds, and the live
    reprojection error of the configured registration.  ``O`` solves per-marker
    rotation (needs ``marker_size_mm``).  ``W`` writes the registration with status
    MEASURED and the measured error block.  Nothing is written without a solve.
    """
    source = open_source(cfg.camera.source, cfg.camera.width, cfg.camera.height,
                         probe_max_index=cfg.camera.probe_max_index, probe_timeout_s=cfg.camera.probe_timeout_s,
                         recording_fps=cfg.camera.recording_fps)
    camera = CameraWorker(source).start()
    registrar = BoardRegistrar(registration, min_markers=cfg.board.min_markers, max_rms_uv=cfg.board.max_reprojection_rms_uv,
                               grace_ms=0, jump_tolerance_uv=cfg.board.jump_tolerance_uv)
    print(f"[calibrate] expected dictionary {registration.dictionary}, expected ids {sorted(registration.markers)}, "
          f"marker size {registration.marker_size_mm} mm, board {registration.board_width_mm}x{registration.board_height_mm} mm")
    print("[calibrate] keys: O solve rotations, W write MEASURED registration, Q quit")
    scan: dict[str, list[int]] = {}
    started = time.monotonic()
    state: RegistrationState | None = None
    written = False
    frame_count = 0
    names = registration.candidate_dictionaries or [registration.dictionary]
    try:
        while True:
            frame = camera.latest()
            if frame is None:
                if camera.ended:
                    break
                cv2.waitKey(5)
                continue
            frame_count += 1
            if frame_count % 15 == 1:
                scan = scan_dictionaries(frame.image, names)
            state = registrar.update(frame.image, frame.captured_at_ms)
            lines = [f"configured {registration.dictionary}: ids {sorted(d.marker_id for d in state.detections)}"]
            for name, ids in scan.items():
                lines.append(f"{name}: {ids}")
            if state.valid and not state.held:
                lines.append(f"registration {state.transform_kind} markers {state.markers_used} points {state.points_used} "
                             f"rms {state.rms_uv:.5f} uv / {state.rms_px:.2f} px")
                for mid, r in sorted(state.per_marker_rms_uv.items()):
                    lines.append(f"  marker {mid}: {r:.5f} uv ({r * registration.board_width_mm:.1f} mm)")
            else:
                lines.append(f"no registration: {state.reason}")
            if not registration.uses_corners:
                lines.append("marker_size_mm not set: centres only; pass --marker-size-mm <measured> for corner solve")
            view = draw_camera_view(frame.image, state, registration.geometry(cfg.board.warp_px_per_mm), [],
                                    lines, [], "O rotations  W write  Q quit")
            if cfg.service.debug_window:
                cv2.imshow("FLOODSHIFT calibrate", view)
                key = cv2.waitKey(1) & 0xFF
            else:
                key = 255
            auto = write_after_s is not None and time.monotonic() - started >= write_after_s
            if key == ord("o") and registration.uses_corners:
                rotations = registrar.solve_orientations(state.detections)
                for mid, steps in rotations.items():
                    registration.markers[mid].rotation_deg = steps * 90
                print(f"[calibrate] solved rotations: { {k: v * 90 for k, v in rotations.items()} }")
            if (key == ord("w") or auto) and state is not None and state.valid and not state.held:
                registration.status = MEASURED_STATUS
                for mid in state.markers_used:
                    registration.markers[mid].verified = True
                registration.measured = summarize_for_measurement(
                    state, registration, camera_source=source.describe(), frame_size=(frame.image.shape[1], frame.image.shape[0]),
                    measured_by=measured_by, notes="written by perception.service --calibrate")
                path = registration.save(output)
                print(f"[calibrate] wrote {path} (rms {state.rms_uv:.5f} uv, {state.rms_px:.2f} px, markers {state.markers_used})")
                written = True
                if auto:
                    break
            if key == ord("q"):
                break
    finally:
        camera.stop()
        if cfg.service.debug_window:
            cv2.destroyAllWindows()
    if not written:
        print("[calibrate] nothing written")
    return 0 if written else 1


# --------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="perception.service", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="JSON config overrides")
    p.add_argument("--source", help="auto | <index> | <DroidCam/stream URL> | <video or frames dir>")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--registration", help="path to board_registration.json")
    p.add_argument("--intrinsics", help="camera intrinsics JSON for undistortion")
    p.add_argument("--list-cameras", action="store_true")
    p.add_argument("--calibrate", action="store_true", help="measure the real board markers and write the registration")
    p.add_argument("--marker-size-mm", type=float, help="measured edge length of the printed markers")
    p.add_argument("--marker", action="append", default=[], metavar="ID:U:V[:ROT]",
                   help="override/add a marker's measured centre in board UV (repeatable)")
    p.add_argument("--measured-by", help="who measured the board (written into the registration)")
    p.add_argument("--write-after-s", type=float, help="calibrate: write automatically after N seconds (headless)")
    p.add_argument("--output", help="calibrate: write the registration to this path instead of in place")
    p.add_argument("--jsonl", help="append observations to this JSONL file")
    p.add_argument("--stdout", action="store_true", help="print observations as JSON lines")
    p.add_argument("--observe-url", help="POST observations to the backend adapter")
    p.add_argument("--status-url", help="POST status to the operator backend")
    p.add_argument("--record", help="record frames + events + status to this directory")
    p.add_argument("--save-rois", help="write classifier ROI crops here (for Dev 2)")
    p.add_argument("--sites", help="real scenario sites.json for DEBUG nearest-pad display")
    p.add_argument("--classifier", help="module:factory returning a ClassifierPort (Dev 2)")
    p.add_argument("--no-window", action="store_true")
    p.add_argument("--no-auto-reference", action="store_true")
    p.add_argument("--structure-gate", action="store_true", help="projector-safe candidate mode")
    p.add_argument("--parallax", choices=["intrinsics", "approximate", "off"])
    p.add_argument("--max-seconds", type=float, help="stop after N seconds (headless smoke test / timed recording)")
    p.add_argument("--control-port", type=int, help="serve the operator/adapter control API on this port (see perception/control.py)")
    p.add_argument("--control-host", default=None)
    p.add_argument("--fast", action="store_true",
                   help="weak-laptop preset: 1.5 px/mm warp, ArUco every 2 frames, no warp window, sparse recording, 256 px ROIs")
    return p


def config_from_args(args: argparse.Namespace) -> PerceptionConfig:
    cfg = PerceptionConfig.load(args.config)
    if args.source:
        cfg.camera.source = args.source
    if args.width:
        cfg.camera.width = args.width
    if args.height:
        cfg.camera.height = args.height
    if args.registration:
        cfg.board.registration_path = args.registration
    if args.intrinsics:
        cfg.camera.intrinsics_path = args.intrinsics
    if args.jsonl:
        cfg.service.jsonl_path = args.jsonl
    if args.observe_url:
        cfg.service.observe_url = args.observe_url
    if args.status_url:
        cfg.service.status_url = args.status_url
    if args.record:
        cfg.service.record_dir = args.record
    if args.save_rois:
        cfg.service.save_rois_dir = args.save_rois
    if args.sites:
        cfg.service.sites_path = args.sites
    if args.no_window:
        cfg.service.debug_window = False
    if args.no_auto_reference:
        cfg.service.auto_reference = False
    if args.structure_gate:
        cfg.candidates.structure_gate = True
    if args.parallax:
        cfg.service.parallax_correction = args.parallax
    if args.max_seconds:
        cfg.service.max_seconds = args.max_seconds
    if args.control_port is not None:
        cfg.service.control_port = args.control_port
    if args.control_host:
        cfg.service.control_host = args.control_host
    if args.fast:
        cfg.board.warp_px_per_mm = 1.0
        cfg.board.redetect_every_n_frames = 2
        cfg.service.show_warp = False
        cfg.service.record_every_n_frames = 10
        cfg.service.roi_max_px = 256
    return cfg


LEGACY_OBSERVE_SUFFIX = "/perception/observe"


def observe_url_is_legacy_gateway(url: str | None) -> bool:
    """The retained gateway's /perception/observe takes the legacy ObjectObservation, not
    PhysicalObservation, and converts every confirmed observation into a placement
    (docs/INTEGRATION_CONTRACT.md).  Posting there would misfile lifecycle and class
    fields, so the service refuses it.  Point --observe-url at the shared adapter."""
    return bool(url) and url.rstrip("/").endswith(LEGACY_OBSERVE_SUFFIX)


def apply_marker_overrides(registration: BoardRegistration, args: argparse.Namespace) -> None:
    from .board_aruco import MarkerSpec
    if args.marker_size_mm:
        registration.marker_size_mm = float(args.marker_size_mm)
    for text in args.marker:
        parts = text.split(":")
        if len(parts) < 3:
            raise SystemExit(f"--marker expects ID:U:V[:ROT], got {text!r}")
        mid, u, v = int(parts[0]), float(parts[1]), float(parts[2])
        rot = int(parts[3]) if len(parts) > 3 else 0
        spec = registration.markers.get(mid) or MarkerSpec(mid, (u, v))
        spec.center_uv = (u, v)
        spec.rotation_deg = rot
        registration.markers[mid] = spec


def main(argv: list[str] | None = None) -> int:
    # Secrets and service settings live in the repo-root .env (spec 3, rule 6); never in code or VITE_* vars.
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:  # pragma: no cover - python-dotenv is in requirements
        pass
    args = build_parser().parse_args(argv)
    cfg = config_from_args(args)
    if args.list_cameras:
        probes = enumerate_cameras(cfg.camera.probe_max_index, cfg.camera.width, cfg.camera.height, cfg.camera.probe_timeout_s)
        for p in probes:
            print(f"index {p.index}: {'OK' if p.ok else 'no'} {p.width}x{p.height} {p.name_hint or ''} {p.error or ''}")
        print("DroidCam without a virtual-camera driver: pass --source http://<phone-ip>:4747/video")
        return 0
    if observe_url_is_legacy_gateway(cfg.service.observe_url):
        print(f"[perception] ERROR: --observe-url {cfg.service.observe_url} is the retained gateway's legacy endpoint; "
              "it does not accept PhysicalObservation (see docs/INTEGRATION_CONTRACT.md). "
              "Point it at the shared observation adapter instead.", file=sys.stderr)
        return 2
    registration = BoardRegistration.load(cfg.board.registration_path)
    apply_marker_overrides(registration, args)
    if args.calibrate:
        return run_calibrate(cfg, registration, measured_by=args.measured_by, write_after_s=args.write_after_s,
                             output=Path(args.output) if args.output else None)
    sinks: list[ObservationSink] = []
    if cfg.service.jsonl_path:
        sinks.append(JsonlSink(cfg.service.jsonl_path))
    if args.stdout:
        sinks.append(StdoutSink())
    classifier = load_classifier(args.classifier)
    if hasattr(classifier, "max_inflight"):
        classifier.max_inflight = max(1, cfg.service.classifier_max_inflight)
    service = PerceptionService(cfg, classifier=classifier, sinks=sinks, registration=registration)
    if cfg.service.observe_url:
        def on_response(payload: dict[str, Any], response: Any) -> None:
            if isinstance(response, dict):
                feedback = dict(response)
                feedback.setdefault("track_id", payload.get("track_id"))
                service.handle_adapter_feedback(feedback)
        service.sink.add(HttpSink(cfg.service.observe_url, timeout_s=cfg.service.http_timeout_s,
                                  queue_size=cfg.service.sink_queue_size, on_response=on_response))
    if not sinks and not cfg.service.observe_url:
        service.sink.add(CallbackSink(lambda o: print(f"[obs] {o.to_json()}")))
    return service.run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
