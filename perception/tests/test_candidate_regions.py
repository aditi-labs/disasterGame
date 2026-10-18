from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from perception.candidate_regions import CandidateDetector, crop_roi
from perception.config import CandidateConfig

from .conftest import SyntheticBoard, MARKER_UVS

cv2 = pytest.importorskip("cv2")

BRIDGE = {"center_mm": (210.0, 150.0), "size_mm": (70.0, 40.0), "color_bgr": (40, 220, 240), "angle_deg": 0.0}
WHITE_PIECE = {"center_mm": (120.0, 300.0), "size_mm": (55.0, 45.0), "color_bgr": (250, 250, 250), "angle_deg": 20.0}


def _detector(board: SyntheticBoard, **overrides) -> CandidateDetector:
    cfg = CandidateConfig(**overrides)
    det = CandidateDetector(cfg, board.geometry)
    half = 15.0 / 420.0
    marker_polys = [np.array([[u - half, v - half], [u + half, v - half], [u + half, v + half], [u - half, v + half]])
                    for (u, v) in MARKER_UVS.values()]
    det.set_static_exclusions(marker_polys, [], marker_margin_mm=6.0)
    det.capture_reference([board.empty] * 3, now_ms=0)
    return det


def test_empty_board_yields_no_candidates(board):
    det = _detector(board)
    assert det.detect(board.empty) == []
    assert det.changed_fraction < 0.01


def test_yellow_bridge_and_white_piece_are_found_with_measured_geometry(board):
    det = _detector(board)
    cands = det.detect(board.with_pieces([BRIDGE, WHITE_PIECE]))
    assert len(cands) == 2
    by_pos = sorted(cands, key=lambda c: c.center_mm[1])
    bridge, white = by_pos
    assert np.allclose(bridge.center_mm, BRIDGE["center_mm"], atol=2.0)
    assert abs(bridge.bbox_mm[0] - 70) < 4 and abs(bridge.bbox_mm[1] - 40) < 4
    assert 1.5 < bridge.elongation < 2.0
    assert bridge.appearance.yellow_fraction > 0.8 and bridge.appearance.bright_low_sat_fraction < 0.2
    assert np.allclose(white.center_mm, WHITE_PIECE["center_mm"], atol=2.0)
    assert white.appearance.bright_low_sat_fraction > 0.8 and white.appearance.yellow_fraction < 0.1
    assert abs(white.orientation_deg - 20.0) < 4 or abs(white.orientation_deg - 200.0) < 4
    assert not bridge.touches_board_edge and not white.touches_board_edge


def test_marker_areas_are_excluded_even_if_changed(board):
    det = _detector(board)
    img = board.empty.copy()
    cx, cy = board.geometry.uv_to_warp_px(MARKER_UVS[10])
    cv2.rectangle(img, (int(cx) - 25, int(cy) - 25), (int(cx) + 25, int(cy) + 25), (0, 0, 255), -1)
    assert det.detect(img) == []


def test_size_gates_reject_specks_and_large_hands(board):
    det = _detector(board)
    img = board.with_pieces([{"center_mm": (300, 300), "size_mm": (12.0, 12.0), "color_bgr": (0, 0, 255)},
                             {"center_mm": (200, 200), "size_mm": (160.0, 90.0), "color_bgr": (60, 90, 140)}])
    assert det.detect(img) == []


def test_hand_entering_from_the_edge_is_ignored_but_a_piece_near_the_edge_is_kept(board):
    det = _detector(board)
    img = board.empty.copy()
    # a sleeve/hand: large blob touching the bottom edge
    cv2.rectangle(img, (300, 700), (420, 840), (60, 90, 140), -1)
    # a real piece 6 mm from the right edge (does not touch)
    piece = {"center_mm": (420 - 6 - 20, 100.0), "size_mm": (40.0, 40.0), "color_bgr": (250, 250, 250)}
    cands = det.detect(board.with_pieces([piece]) if False else _overlay(img, board, piece))
    assert len(cands) == 1 and np.allclose(cands[0].center_mm, piece["center_mm"], atol=2.5)


def _overlay(img, board, piece):
    out = img.copy()
    cx, cy = board.geometry.mm_to_warp_px(piece["center_mm"])
    lw, sw = piece["size_mm"]
    box = cv2.boxPoints(((float(cx), float(cy)), (lw * 2, sw * 2), 0.0))
    cv2.fillConvexPoly(out, box.astype(np.int32), piece["color_bgr"])
    return out


def test_cast_shadow_does_not_shift_the_footprint_centroid(board):
    det_shadow = _detector(board, shadow_suppression=True)
    det_plain = _detector(board, shadow_suppression=False)
    img = board.with_pieces([WHITE_PIECE])
    # a soft darker region just beyond the piece's right edge (the rotated piece reaches ~67 px), chroma unchanged
    cx, cy = board.geometry.mm_to_warp_px(WHITE_PIECE["center_mm"])
    shadow = img.copy()
    x0, x1 = int(cx) + 72, int(cx) + 140
    y0, y1 = int(cy) - 50, int(cy) + 50
    shadow[y0:y1, x0:x1] = (shadow[y0:y1, x0:x1] * 0.72).astype(np.uint8)
    with_s = det_shadow.detect(shadow)
    without_s = det_plain.detect(shadow)
    assert len(with_s) == 1
    assert abs(with_s[0].center_mm[0] - WHITE_PIECE["center_mm"][0]) < 2.5
    # without suppression the blob either merges with the shadow or the shadow becomes its own blob
    assert len(without_s) != 1 or abs(without_s[0].center_mm[0] - WHITE_PIECE["center_mm"][0]) > 2.5


def test_projector_glow_is_rejected_by_structure_gate_but_a_piece_survives(board):
    det = _detector(board, structure_gate=True)
    glow = board.empty.copy().astype(np.int16)
    glow[200:420, 200:420] += np.array([40, 25, -10], dtype=np.int16)  # a flat coloured light pool
    glow = np.clip(glow, 0, 255).astype(np.uint8)
    assert det.detect(glow) == []
    assert len(det.detect(board.with_pieces([BRIDGE]))) == 1


def test_lighting_shift_raises_changed_fraction_warning_signal(board):
    det = _detector(board)
    darker = (board.empty.astype(np.float32) * 0.55).astype(np.uint8)
    det.detect(darker)
    assert det.changed_fraction > 0.3


def test_crop_roi_is_clamped_and_padded(board):
    img = board.with_pieces([BRIDGE])
    crop, bbox = crop_roi(img, (820, 820, 30, 30), pad_px=20)
    assert bbox == (800, 800, 40, 40) and crop.shape[:2] == (40, 40)


def test_real_bridge_photo_composite_is_a_single_elongated_yellow_candidate():
    """Authentic photo of the printed yellow bridge (floodshift- tests/fixtures/board_frames), pasted on a
    plain grey canvas by the original team.  The reference here is the same canvas without the
    piece (the piece region replaced by the canvas median), which is a derived control, not a
    second capture.  Documented as such; it checks the yellow piece's measured geometry only."""
    path = Path(__file__).parent / "fixtures" / "real_bridge_piece_composite_1280x720.jpg"
    if not path.is_file():
        pytest.skip("real bridge fixture not present")
    img = cv2.imread(str(path))
    from perception.geometry import BoardGeometry
    geom = BoardGeometry(img.shape[1] / 2.0, img.shape[0] / 2.0, 2.0)  # treat the frame as a 640x360 mm plane
    det = CandidateDetector(CandidateConfig(min_area_mm2=300, max_area_mm2=20000), geom)
    det.set_static_exclusions([], [])
    ref = img.copy()
    ref[160:560, 480:800] = np.median(img[160:560, 480:800].reshape(-1, 3), axis=0).astype(np.uint8)
    det.capture_reference([ref], 0)
    cands = det.detect(img)
    yellow = [c for c in cands if c.appearance.yellow_fraction > 0.5]
    assert len(yellow) == 1
    assert 1.4 < yellow[0].elongation < 2.6
