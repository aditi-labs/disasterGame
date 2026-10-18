"""Existing board ArUco markers -> camera-to-board registration (spec 6.2, 6.3, 6.4).

* Detects markers with ``cv2.aruco.ArucoDetector`` using the dictionary named in
  ``board_registration.json``; the calibrate flow can scan every candidate
  dictionary to confirm what is really printed on the board.
* Solves the camera px -> board UV homography from **all four corners** of every
  registered marker when the physical marker size is known (16 points for four
  markers, so three or even two markers still register), or from marker centres
  when it is not (then four markers are required; three give a degraded affine).
* Records RMS reprojection error in UV and px, per marker.
* Holds the last good registration for a bounded grace interval when markers are
  occluded by a hand or a piece, and refuses a re-solve that would jump the board
  corners while markers are missing (spec 5 integrity rules).
* Board markers are calibration references only: they are exported as exclusion
  polygons so they can never become piece candidates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import itertools
import json
from pathlib import Path
import time
from typing import Any

import numpy as np

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from .geometry import (
    BoardGeometry,
    apply_homography,
    board_quad_px,
    homography_from_points,
    quad_displacement_uv,
    reprojection_errors,
    solve_camera_pose,
    CameraPose,
)

MEASURED_STATUS = "MEASURED"
TENTATIVE_STATUS = "UNVERIFIED_TENTATIVE"


# ------------------------------------------------------------------ registration file
@dataclass
class MarkerSpec:
    marker_id: int
    center_uv: tuple[float, float]
    rotation_deg: int = 0          # 0/90/180/270: printed rotation relative to board axes
    role: str = "board_corner"
    label: str = ""
    verified: bool = False

    @property
    def rotation_steps(self) -> int:
        return int(round(self.rotation_deg / 90.0)) % 4


@dataclass
class BoardRegistration:
    dictionary: str
    markers: dict[int, MarkerSpec]
    board_width_mm: float
    board_height_mm: float
    marker_size_mm: float | None
    status: str
    candidate_dictionaries: list[str] = field(default_factory=list)
    scenario_id: str | None = None
    measured: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        return self.status == MEASURED_STATUS and all(m.verified for m in self.markers.values())

    @property
    def uses_corners(self) -> bool:
        return self.marker_size_mm is not None and self.marker_size_mm > 0

    @staticmethod
    def load(path: str | Path) -> "BoardRegistration":
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        markers = {}
        for m in data.get("markers", []):
            markers[int(m["id"])] = MarkerSpec(
                marker_id=int(m["id"]),
                center_uv=(float(m["center_uv"][0]), float(m["center_uv"][1])),
                rotation_deg=int(m.get("rotation_deg", 0)),
                role=str(m.get("role", "board_corner")),
                label=str(m.get("label", "")),
                verified=bool(m.get("verified", False)),
            )
        board = data.get("board", {})
        aruco = data.get("aruco", {})
        return BoardRegistration(
            dictionary=str(aruco.get("dictionary", "DICT_4X4_100")),
            markers=markers,
            board_width_mm=float(board.get("width_mm", 420.0)),
            board_height_mm=float(board.get("height_mm", 420.0)),
            marker_size_mm=(None if aruco.get("marker_size_mm") in (None, 0) else float(aruco["marker_size_mm"])),
            status=str(data.get("status", TENTATIVE_STATUS)),
            candidate_dictionaries=list(aruco.get("candidate_dictionaries", [])),
            scenario_id=board.get("scenario_id"),
            measured=dict(data.get("measured", {})),
            path=p,
            raw=data,
        )

    def geometry(self, px_per_mm: float) -> BoardGeometry:
        return BoardGeometry(self.board_width_mm, self.board_height_mm, px_per_mm)

    def marker_corner_uvs(self, spec: MarkerSpec) -> np.ndarray | None:
        """Board UV of the marker's four physical corners, clockwise from the board-aligned TL."""
        if not self.uses_corners:
            return None
        half = self.marker_size_mm / 2.0
        cx, cy = spec.center_uv[0] * self.board_width_mm, spec.center_uv[1] * self.board_height_mm
        corners_mm = np.array([[cx - half, cy - half], [cx + half, cy - half],
                               [cx + half, cy + half], [cx - half, cy + half]])
        return corners_mm / np.array([self.board_width_mm, self.board_height_mm])

    def to_json_dict(self) -> dict[str, Any]:
        data = dict(self.raw) if self.raw else {}
        data["schema"] = "floodshift.board_registration.v1"
        data["status"] = self.status
        data.setdefault("board", {})
        data["board"].update({"scenario_id": self.scenario_id, "width_mm": self.board_width_mm,
                              "height_mm": self.board_height_mm, "uv_origin": "top_left"})
        data.setdefault("aruco", {})
        data["aruco"].update({"dictionary": self.dictionary, "marker_size_mm": self.marker_size_mm,
                              "candidate_dictionaries": self.candidate_dictionaries})
        data["markers"] = [
            {"id": m.marker_id, "role": m.role, "label": m.label, "center_uv": [m.center_uv[0], m.center_uv[1]],
             "rotation_deg": m.rotation_deg, "verified": m.verified}
            for m in sorted(self.markers.values(), key=lambda s: s.marker_id)
        ]
        data["measured"] = self.measured
        return data

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no path to save the registration to")
        target.write_text(json.dumps(self.to_json_dict(), indent=2) + "\n", encoding="utf-8")
        self.path = target
        return target


# ------------------------------------------------------------------ detections
@dataclass
class MarkerDetection:
    marker_id: int
    corners_px: np.ndarray  # (4,2) in OpenCV order: pattern TL, TR, BR, BL

    @property
    def center_px(self) -> tuple[float, float]:
        c = self.corners_px.mean(axis=0)
        return float(c[0]), float(c[1])

    @property
    def side_px(self) -> float:
        d = np.linalg.norm(np.roll(self.corners_px, -1, axis=0) - self.corners_px, axis=1)
        return float(d.mean())


def dictionary_by_name(name: str):
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    if not hasattr(cv2.aruco, name):
        raise ValueError(f"unknown ArUco dictionary {name}")
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def make_detector(dictionary_name: str):
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.cornerRefinementWinSize = 5
    # The real markers are large (about 13 % of the print): allow wide adaptive-threshold windows.
    # (minMarkerDistanceRate is left at its default: lowering it produced duplicate decodes of
    # one marker on the real photo; the edge case it was meant for is handled by the padded retry.)
    params.adaptiveThreshWinSizeMax = 73
    return cv2.aruco.ArucoDetector(dictionary_by_name(dictionary_name), params)


EDGE_PAD_PX = 48


def _run_detector(detector, gray: np.ndarray, offset: float = 0.0) -> list[MarkerDetection]:
    corners, ids, _ = detector.detectMarkers(gray)
    out: list[MarkerDetection] = []
    if ids is None:
        return out
    for c, marker_id in zip(corners, ids.flatten()):
        out.append(MarkerDetection(int(marker_id), np.asarray(c, dtype=np.float64).reshape(4, 2) - offset))
    return out


def detect_markers(detector, frame: np.ndarray, expected_ids: set[int] | None = None) -> list[MarkerDetection]:
    """Detect markers; if any expected ID is missing, retry once on a white-padded frame.

    Lesson from the first real board photo (2026-10-18): a marker whose paper touches
    the image border loses its quiet zone and silently fails to decode.  Padding the
    frame restores it.  The retry costs nothing when every expected marker is found.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    found = _dedupe(_run_detector(detector, gray))
    if expected_ids:
        missing = expected_ids - {d.marker_id for d in found}
        if missing:
            padded = cv2.copyMakeBorder(gray, EDGE_PAD_PX, EDGE_PAD_PX, EDGE_PAD_PX, EDGE_PAD_PX,
                                        cv2.BORDER_CONSTANT, value=255)
            seen = {d.marker_id for d in found}
            for d in _dedupe(_run_detector(detector, padded, offset=EDGE_PAD_PX)):
                if d.marker_id in missing and d.marker_id not in seen:
                    found.append(d)
                    seen.add(d.marker_id)
    return found


def _dedupe(detections: list[MarkerDetection]) -> list[MarkerDetection]:
    """One detection per ID: keep the largest quad (a nested duplicate is always smaller)."""
    best: dict[int, MarkerDetection] = {}
    for d in detections:
        cur = best.get(d.marker_id)
        if cur is None or d.side_px > cur.side_px:
            best[d.marker_id] = d
    return list(best.values())


SPURIOUS_SIDE_RATIO = 0.4


def drop_spurious_unknowns(detections: list[MarkerDetection], registered_ids: set[int]) -> tuple[list[MarkerDetection], list[int]]:
    """Unregistered IDs much smaller than the registered markers are texture false positives.

    All real board markers are printed at one size; on the 2026-10-18 photo a 13 px blob in
    the map print decoded as ID 37 next to 100 px markers.  Returns (kept, dropped_ids).
    """
    registered = [d for d in detections if d.marker_id in registered_ids]
    if not registered:
        return detections, []
    median_side = float(np.median([d.side_px for d in registered]))
    kept, dropped = [], []
    for d in detections:
        if d.marker_id not in registered_ids and d.side_px < SPURIOUS_SIDE_RATIO * median_side:
            dropped.append(d.marker_id)
        else:
            kept.append(d)
    return kept, sorted(set(dropped))


def scan_dictionaries(frame: np.ndarray, names: list[str]) -> dict[str, list[int]]:
    """Which marker IDs each candidate dictionary finds in this frame (calibrate flow)."""
    found: dict[str, list[int]] = {}
    for name in names:
        try:
            dets = detect_markers(make_detector(name), frame)
        except ValueError:
            continue
        if dets:
            found[name] = sorted(d.marker_id for d in dets)
    return found


# ------------------------------------------------------------------ state
@dataclass
class RegistrationState:
    valid: bool
    homography: np.ndarray | None          # camera px -> board UV
    transform_kind: str                    # "homography" | "affine" | "none"
    markers_used: list[int]
    points_used: int
    rms_uv: float | None
    rms_px: float | None
    per_marker_rms_uv: dict[int, float]
    solved_at_ms: int                      # when the homography in use was solved
    held: bool                             # True when a previous solve is being reused
    degraded: bool                         # affine, high error, or held past the first frame
    reason: str                            # human readable
    detections: list[MarkerDetection] = field(default_factory=list)
    unknown_ids: list[int] = field(default_factory=list)
    camera_pose: CameraPose | None = None
    visible_registered: int = 0            # registered markers seen in THIS frame (0 => board not in view)

    def age_ms(self, now_ms: int) -> int:
        return max(0, now_ms - self.solved_at_ms)

    @property
    def board_in_view(self) -> bool:
        """True when the board can actually be seen now (not merely remembered from a hold)."""
        return self.valid and (not self.held or self.visible_registered > 0)

    def as_status(self, now_ms: int, registration: BoardRegistration) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "transform": self.transform_kind,
            "markers_used": self.markers_used,
            "markers_expected": sorted(registration.markers),
            "unknown_ids_seen": self.unknown_ids,
            "points_used": self.points_used,
            "reprojection_rms_uv": None if self.rms_uv is None else round(self.rms_uv, 5),
            "reprojection_rms_px": None if self.rms_px is None else round(self.rms_px, 2),
            "held": self.held,
            "degraded": self.degraded,
            "board_in_view": self.board_in_view,
            "visible_registered": self.visible_registered,
            "age_ms": self.age_ms(now_ms),
            "reason": self.reason,
            "registration_status": registration.status,
            "registration_verified": registration.verified,
            "dictionary": registration.dictionary,
            "marker_size_mm": registration.marker_size_mm,
            "camera_height_mm": None if self.camera_pose is None else round(self.camera_pose.position_mm[2], 1),
            "camera_pose_approximate": None if self.camera_pose is None else self.camera_pose.approximate,
        }


def _no_registration(reason: str, detections: list[MarkerDetection], unknown: list[int], now_ms: int) -> RegistrationState:
    return RegistrationState(False, None, "none", [], 0, None, None, {}, now_ms, False, True, reason,
                             detections, unknown)


class BoardRegistrar:
    """Per-frame marker detection and temporally stabilised registration."""

    def __init__(self, registration: BoardRegistration, *, min_markers: int = 2,
                 max_rms_uv: float = 0.008, grace_ms: int = 4000, jump_tolerance_uv: float = 0.02,
                 ransac_from_points: int = 8, ransac_threshold_px: float = 3.0,
                 smoothing_alpha: float = 0.5, camera_matrix: np.ndarray | None = None,
                 dist_coeffs: np.ndarray | None = None, intrinsics_approximate: bool = True,
                 clock=None):
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")
        self.registration = registration
        self.detector = make_detector(registration.dictionary)
        self.min_markers = min_markers
        self.max_rms_uv = max_rms_uv
        self.grace_ms = grace_ms
        self.jump_tolerance_uv = jump_tolerance_uv
        self.ransac_from_points = ransac_from_points
        self.ransac_threshold_px = ransac_threshold_px
        self.smoothing_alpha = smoothing_alpha
        self.camera_matrix = camera_matrix
        self.dist_coeffs = dist_coeffs
        self.intrinsics_approximate = intrinsics_approximate
        self.clock = clock or (lambda: int(time.time() * 1000))
        self._last_good: RegistrationState | None = None
        self._smoothed_quad: np.ndarray | None = None
        self._smoothed_ids: tuple[int, ...] = ()
        self.last_state: RegistrationState | None = None
        self.last_spurious_ids: list[int] = []

    # -- correspondences
    def _correspondences(self, detections: list[MarkerDetection]) -> tuple[np.ndarray, np.ndarray, list[int], list[tuple[int, int]]]:
        """src px, dst uv, marker ids used, and (marker_id, point_index) tags."""
        src, dst, used, tags = [], [], [], []
        reg = self.registration
        for det in detections:
            spec = reg.markers.get(det.marker_id)
            if spec is None:
                continue
            used.append(det.marker_id)
            if reg.uses_corners:
                corner_uvs = reg.marker_corner_uvs(spec)
                shift = spec.rotation_steps
                for i in range(4):
                    src.append(det.corners_px[i])
                    dst.append(corner_uvs[(i + shift) % 4])
                    tags.append((det.marker_id, i))
            else:
                src.append(det.center_px)
                dst.append(spec.center_uv)
                tags.append((det.marker_id, -1))
        return (np.asarray(src, dtype=np.float64).reshape(-1, 2),
                np.asarray(dst, dtype=np.float64).reshape(-1, 2), used, tags)

    def _solve_from(self, src: np.ndarray, dst: np.ndarray):
        return homography_from_points(src, dst, ransac_from=self.ransac_from_points,
                                      ransac_threshold_px=self.ransac_threshold_px)

    # -- public
    def detect(self, frame: np.ndarray) -> list[MarkerDetection]:
        return detect_markers(self.detector, frame, expected_ids=set(self.registration.markers))

    def update(self, frame: np.ndarray, now_ms: int | None = None,
               detections: list[MarkerDetection] | None = None) -> RegistrationState:
        now = self.clock() if now_ms is None else now_ms
        dets = self.detect(frame) if detections is None else detections
        dets, self.last_spurious_ids = drop_spurious_unknowns(dets, set(self.registration.markers))
        unknown = sorted({d.marker_id for d in dets if d.marker_id not in self.registration.markers})
        src, dst, used, tags = self._correspondences(dets)
        used_sorted = sorted(set(used))

        fresh: RegistrationState | None = None
        reason = ""
        enough = len(used_sorted) >= self.min_markers
        if self.registration.uses_corners:
            enough = enough and src.shape[0] >= 4
        else:
            enough = enough and src.shape[0] >= 3
        if enough:
            h, kind = self._solve_from(src, dst)
            if h is not None:
                rms_uv, rms_px, res = reprojection_errors(h, src, dst)
                per_marker: dict[int, list[float]] = {}
                for (mid, _), r in zip(tags, res):
                    per_marker.setdefault(mid, []).append(float(r))
                per_marker_rms = {mid: float(np.sqrt(np.mean(np.square(v)))) for mid, v in per_marker.items()}
                degraded = kind != "homography" or rms_uv > self.max_rms_uv
                if kind != "homography":
                    reason = f"{kind} from {src.shape[0]} points (no perspective term)"
                elif rms_uv > self.max_rms_uv:
                    reason = f"reprojection rms {rms_uv:.4f} uv above {self.max_rms_uv}"
                else:
                    reason = "ok"
                fresh = RegistrationState(True, h, kind, used_sorted, int(src.shape[0]), rms_uv, rms_px,
                                          per_marker_rms, now, False, degraded, reason, dets, unknown)
            else:
                reason = f"solver failed ({kind})"
        else:
            reason = (f"{len(used_sorted)} registered marker(s) visible, need {self.min_markers}"
                      if not used_sorted else f"only {src.shape[0]} point(s); set marker_size_mm or show more markers")

        state = self._stabilise(fresh, reason, dets, unknown, now)
        state.visible_registered = len(used_sorted)
        if state.valid and state.homography is not None and self.camera_matrix is not None and not state.held:
            state.camera_pose = self._pose(src, dst)
        elif state.valid and self._last_good is not None and self._last_good.camera_pose is not None:
            state.camera_pose = self._last_good.camera_pose
        self.last_state = state
        return state

    def _pose(self, src: np.ndarray, dst_uv: np.ndarray) -> CameraPose | None:
        if src.shape[0] < 4:
            return None
        geom = np.array([self.registration.board_width_mm, self.registration.board_height_mm])
        try:
            return solve_camera_pose(dst_uv * geom, src, self.camera_matrix, self.dist_coeffs,
                                     approximate=self.intrinsics_approximate)
        except cv2.error:  # pragma: no cover - solver edge cases
            return None

    def _stabilise(self, fresh: RegistrationState | None, reason: str, dets, unknown, now: int) -> RegistrationState:
        held = self._last_good
        if fresh is None or not fresh.valid:
            if held is not None and now - held.solved_at_ms <= self.grace_ms:
                return RegistrationState(True, held.homography, held.transform_kind, held.markers_used,
                                         held.points_used, held.rms_uv, held.rms_px, held.per_marker_rms_uv,
                                         held.solved_at_ms, True, True,
                                         f"holding last registration ({reason})", dets, unknown, held.camera_pose)
            return _no_registration(reason, dets, unknown, now)

        # Occlusion guard: fewer markers than before AND the board corners would jump.
        if held is not None and len(fresh.markers_used) < len(held.markers_used):
            jump = quad_displacement_uv(held.homography, fresh.homography)
            if jump > self.jump_tolerance_uv and now - held.solved_at_ms <= self.grace_ms:
                return RegistrationState(True, held.homography, held.transform_kind, held.markers_used,
                                         held.points_used, held.rms_uv, held.rms_px, held.per_marker_rms_uv,
                                         held.solved_at_ms, True, True,
                                         f"holding: partial markers would jump board by {jump:.3f} uv",
                                         dets, unknown, held.camera_pose)

        # Temporal smoothing of the board quad when the same marker set is visible.
        ids = tuple(fresh.markers_used)
        quad = board_quad_px(fresh.homography)
        if self._smoothed_quad is not None and ids == self._smoothed_ids and fresh.transform_kind == "homography":
            a = self.smoothing_alpha
            quad = a * quad + (1 - a) * self._smoothed_quad
            h_uv_to_px = cv2.getPerspectiveTransform(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32),
                                                     quad.astype(np.float32))
            try:
                fresh.homography = np.linalg.inv(h_uv_to_px)
            except np.linalg.LinAlgError:
                pass
        self._smoothed_quad = quad
        self._smoothed_ids = ids
        self._last_good = fresh
        return fresh

    def reset_hold(self) -> None:
        """Operator RECALIBRATE: forget the held registration and smoothing."""
        self._last_good = None
        self._smoothed_quad = None
        self._smoothed_ids = ()

    # -- exclusion geometry
    def marker_polygons_px(self, detections: list[MarkerDetection], *, registered_only: bool = False) -> list[np.ndarray]:
        polys = []
        for d in detections:
            if registered_only and d.marker_id not in self.registration.markers:
                continue
            polys.append(d.corners_px.copy())
        return polys

    def registered_marker_polygons_uv(self) -> list[np.ndarray]:
        """Where the registered markers are on the board plane (independent of detection)."""
        polys = []
        reg = self.registration
        for spec in reg.markers.values():
            corners = reg.marker_corner_uvs(spec)
            if corners is None:
                # Unknown size: exclude a conservative 30 mm square around the centre.
                half = 15.0 / np.array([reg.board_width_mm, reg.board_height_mm])
                c = np.array(spec.center_uv)
                corners = np.array([c - half, [c[0] + half[0], c[1] - half[1]], c + half, [c[0] - half[0], c[1] + half[1]]])
            polys.append(corners)
        return polys

    # -- calibrate flow helpers
    def solve_orientations(self, detections: list[MarkerDetection]) -> dict[int, int]:
        """Find each registered marker's printed rotation (0..3 quarter turns) by minimising RMS.

        Needs the marker size.  Brute-forces all combinations for up to four
        markers; with more, seeds from centres and refines per marker.
        """
        reg = self.registration
        if not reg.uses_corners:
            return {}
        known = [d for d in detections if d.marker_id in reg.markers]
        if not known:
            return {}
        original = {m.marker_id: m.rotation_deg for m in reg.markers.values()}

        def rms_for(assignment: dict[int, int]) -> float:
            for mid, steps in assignment.items():
                reg.markers[mid].rotation_deg = steps * 90
            src, dst, _, _ = self._correspondences(known)
            h, kind = self._solve_from(src, dst)
            if h is None or kind != "homography":
                return float("inf")
            return reprojection_errors(h, src, dst)[0]

        best: dict[int, int] = {}
        try:
            ids = [d.marker_id for d in known]
            if len(ids) <= 4:
                best_rms = float("inf")
                for combo in itertools.product(range(4), repeat=len(ids)):
                    assignment = dict(zip(ids, combo))
                    r = rms_for(assignment)
                    if r < best_rms:
                        best_rms, best = r, assignment
            else:
                best = {mid: 0 for mid in ids}
                for mid in ids:
                    scores = []
                    for steps in range(4):
                        trial = dict(best)
                        trial[mid] = steps
                        scores.append((rms_for(trial), steps))
                    best[mid] = min(scores)[1]
        finally:
            for mid, deg in original.items():
                reg.markers[mid].rotation_deg = deg
        return best


def summarize_for_measurement(state: RegistrationState, registration: BoardRegistration, *, camera_source: str,
                              frame_size: tuple[int, int], measured_by: str | None = None,
                              notes: str | None = None) -> dict[str, Any]:
    """Build the ``measured`` block written by the calibrate flow (spec docs/BOARD_REGISTRATION.md)."""
    return {
        "measured_on": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "measured_by": measured_by,
        "camera_source": camera_source,
        "frame_size": list(frame_size),
        "reprojection_rms_uv": state.rms_uv,
        "reprojection_rms_px": state.rms_px,
        "per_marker_rms_uv": {str(k): v for k, v in state.per_marker_rms_uv.items()},
        "markers_used": state.markers_used,
        "points_used": state.points_used,
        "transform": state.transform_kind,
        "detected_ids_all": sorted({d.marker_id for d in state.detections}),
        "marker_size_mm": registration.marker_size_mm,
        "notes": notes,
    }
