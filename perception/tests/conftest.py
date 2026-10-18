"""Shared helpers for perception tests.

Spec section 10: unit tests may use small mathematical inputs for pure transforms.
The synthetic board here is exactly that - a deterministic raster with real ArUco
patterns at known UV positions - used to test the *mathematics* of registration,
warping, candidate extraction and tracking.  It is not a game scenario and no test
here claims hardware acceptance; those come from recorded real-board runs
(see docs/BOARD_REGISTRATION.md and perception/README.md).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

cv2 = pytest.importorskip("cv2")

from perception.board_aruco import BoardRegistration, MarkerSpec  # noqa: E402
from perception.camera import Frame  # noqa: E402
from perception.geometry import BoardGeometry  # noqa: E402

BOARD_MM = 420.0
MARKER_MM = 30.0
MARKER_UVS = {10: (0.06, 0.06), 11: (0.94, 0.06), 12: (0.94, 0.94), 13: (0.06, 0.94)}


def make_registration(tmp_path: Path, *, marker_size_mm: float | None = MARKER_MM,
                      rotations: dict[int, int] | None = None, dictionary: str = "DICT_4X4_100") -> BoardRegistration:
    markers = {}
    for mid, uv in MARKER_UVS.items():
        markers[mid] = MarkerSpec(mid, uv, rotation_deg=(rotations or {}).get(mid, 0), verified=False)
    reg = BoardRegistration(dictionary=dictionary, markers=markers, board_width_mm=BOARD_MM, board_height_mm=BOARD_MM,
                            marker_size_mm=marker_size_mm, status="UNVERIFIED_TENTATIVE",
                            candidate_dictionaries=["DICT_4X4_100", "DICT_4X4_50"], scenario_id="test",
                            path=tmp_path / "registration.json")
    reg.save()
    return reg


class SyntheticBoard:
    """Top-down board raster (2 px/mm) with ArUco markers and an optional piece."""

    def __init__(self, px_per_mm: float = 2.0, seed: int = 7, dictionary: str = "DICT_4X4_100",
                 marker_size_mm: float = MARKER_MM, rotations: dict[int, int] | None = None):
        self.geometry = BoardGeometry(BOARD_MM, BOARD_MM, px_per_mm)
        w, h = self.geometry.warp_size
        rng = np.random.default_rng(seed)
        base = np.full((h, w, 3), 225, dtype=np.uint8)
        # Printed-map-like texture: faint roads, contour lines and a river band.
        for _ in range(40):
            p1 = rng.integers(0, [w, h]); p2 = rng.integers(0, [w, h])
            cv2.line(base, tuple(int(x) for x in p1), tuple(int(x) for x in p2), (190, 190, 190), 1)
        for _ in range(25):
            c = rng.integers(0, [w, h]); r = int(rng.integers(10, 80))
            cv2.circle(base, tuple(int(x) for x in c), r, (205, 205, 205), 1)
        cv2.rectangle(base, (int(w * 0.45), 0), (int(w * 0.55), h), (210, 190, 160), -1)
        noise = rng.integers(-6, 7, size=base.shape, dtype=np.int16)
        base = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        self.dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
        size_px = int(round(marker_size_mm * px_per_mm))
        for mid, uv in MARKER_UVS.items():
            img = cv2.aruco.generateImageMarker(self.dictionary, mid, size_px)
            steps = ((rotations or {}).get(mid, 0) // 90) % 4
            for _ in range(steps):
                img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            cx, cy = self.geometry.uv_to_warp_px(uv)
            x0, y0 = int(round(cx - size_px / 2)), int(round(cy - size_px / 2))
            pad = int(round(4 * px_per_mm))
            cv2.rectangle(base, (x0 - pad, y0 - pad), (x0 + size_px + pad, y0 + size_px + pad), (255, 255, 255), -1)
            base[y0:y0 + size_px, x0:x0 + size_px] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        self.empty = base

    def with_pieces(self, pieces: list[dict]) -> np.ndarray:
        """pieces: {center_mm, size_mm (long, short), color_bgr, angle_deg}."""
        img = self.empty.copy()
        for p in pieces:
            cx, cy = self.geometry.mm_to_warp_px(p["center_mm"])
            lw, sw = p.get("size_mm", (70.0, 40.0))
            box = cv2.boxPoints(((float(cx), float(cy)), (lw * self.geometry.px_per_mm, sw * self.geometry.px_per_mm),
                                 float(p.get("angle_deg", 0.0))))
            cv2.fillConvexPoly(img, box.astype(np.int32), p.get("color_bgr", (40, 220, 240)))
            # a darker rim so the piece has edge structure like a 3D print
            cv2.polylines(img, [box.astype(np.int32)], True, tuple(int(c * 0.6) for c in p.get("color_bgr", (40, 220, 240))), 2)
        return img


def camera_homography(board_geometry: BoardGeometry, cam_size: tuple[int, int] = (1280, 720),
                      quad: np.ndarray | None = None) -> np.ndarray:
    """Board-warp-px -> camera-px homography for a mildly oblique overhead camera."""
    w, h = board_geometry.warp_size
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    if quad is None:
        cw, ch = cam_size
        quad = np.array([[cw * 0.22, ch * 0.08], [cw * 0.80, ch * 0.10], [cw * 0.84, ch * 0.94], [cw * 0.18, ch * 0.92]],
                        dtype=np.float32)
    return cv2.getPerspectiveTransform(src, quad.astype(np.float32))


def render_camera(board_img: np.ndarray, h_board_to_cam: np.ndarray, cam_size: tuple[int, int] = (1280, 720),
                  background: int = 90, blur: int = 0) -> np.ndarray:
    canvas = np.full((cam_size[1], cam_size[0], 3), background, dtype=np.uint8)
    out = cv2.warpPerspective(board_img, h_board_to_cam, cam_size, dst=canvas, borderMode=cv2.BORDER_TRANSPARENT)
    if blur:
        out = cv2.GaussianBlur(out, (blur | 1, blur | 1), 0)
    return out


def frame_from(image: np.ndarray, frame_id: int, t_ms: int, provenance: str = "recording:synthetic") -> Frame:
    return Frame(image=image, frame_id=frame_id, captured_at_ms=t_ms, provenance=f"{provenance}#{frame_id}")


@pytest.fixture
def board() -> SyntheticBoard:
    return SyntheticBoard()


@pytest.fixture
def registration(tmp_path) -> BoardRegistration:
    return make_registration(tmp_path)


@pytest.fixture
def centers_only_registration(tmp_path) -> BoardRegistration:
    return make_registration(tmp_path, marker_size_mm=None)


def write_frames_dir(path: Path, images: list[np.ndarray]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(images):
        cv2.imwrite(str(path / f"{i:05d}.png"), img)
    return path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
