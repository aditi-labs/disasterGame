"""Regression tests on the real board photo (2026-10-18), see fixtures/README.md.

The photo is a perspective phone picture of the physical printed map with its four
ArUco markers, rotated 90 degrees clockwise relative to the upright map.  These tests
pin the facts that were verified from it: dictionary family, IDs, corner layout and
printed rotation, plus the edge-of-frame decoding lesson.  They make no claim about
millimetre positions, which still need a ruler.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from perception.board_aruco import BoardRegistrar, BoardRegistration, detect_markers, make_detector, scan_dictionaries
from perception.config import DEFAULT_REGISTRATION_PATH

cv2 = pytest.importorskip("cv2")

PHOTO = Path(__file__).parent / "fixtures" / "real_board_photo_2026-10-18_portrait_1400.jpg"
pytestmark = pytest.mark.skipif(not PHOTO.is_file(), reason="real board photo fixture missing")


@pytest.fixture(scope="module")
def photo() -> np.ndarray:
    return cv2.imread(str(PHOTO))


def _rotation_cw(det) -> int:
    off = det.corners_px[0] - det.corners_px.mean(axis=0)
    return {(-1, -1): 0, (1, -1): 90, (1, 1): 180, (-1, 1): 270}[(int(np.sign(off[0])), int(np.sign(off[1])))]


def test_board_markers_are_4x4_family_ids_10_to_13(photo):
    found = scan_dictionaries(photo, ["DICT_4X4_50", "DICT_5X5_100", "DICT_6X6_250", "DICT_ARUCO_ORIGINAL"])
    assert "DICT_5X5_100" not in found and "DICT_6X6_250" not in found
    # plain scan: the edge-touching marker 12 may or may not decode at this scale
    assert set(found["DICT_4X4_50"]) >= {10, 11, 13}


def test_padded_retry_recovers_the_marker_touching_the_image_edge(photo):
    detector = make_detector("DICT_4X4_50")
    with_retry = {d.marker_id: d for d in detect_markers(detector, photo, expected_ids={10, 11, 12, 13})}
    assert set(with_retry) == {10, 11, 12, 13}
    h, w = photo.shape[:2]
    pos = {mid: with_retry[mid].center_px for mid in with_retry}
    # layout in the PHOTO frame (map rotated 90 deg CW): TL=12, TR=10, BR=11, BL=13
    assert pos[12][0] < w / 2 and pos[12][1] < h / 2
    assert pos[10][0] > w / 2 and pos[10][1] < h / 2
    assert pos[11][0] > w / 2 and pos[11][1] > h / 2
    assert pos[13][0] < w / 2 and pos[13][1] > h / 2
    # every printed pattern is rotated the same 90 deg CW in the photo frame
    assert {_rotation_cw(d) for d in with_retry.values()} == {90}


def test_shipped_registration_registers_the_upright_photo(photo):
    """Rotating the photo 90 deg CCW yields the upright frame the registration describes."""
    registration = BoardRegistration.load(DEFAULT_REGISTRATION_PATH)
    assert registration.dictionary == "DICT_4X4_50"
    assert {m.marker_id: m.label for m in registration.markers.values()} == {
        10: "top_left", 11: "top_right", 13: "bottom_right", 12: "bottom_left"}
    assert not registration.verified  # positions are photo estimates until measured with a ruler
    upright = cv2.rotate(photo, cv2.ROTATE_90_COUNTERCLOCKWISE)
    registrar = BoardRegistrar(registration, min_markers=4)
    state = registrar.update(upright, now_ms=1)
    assert state.valid and state.markers_used == [10, 11, 12, 13] and state.transform_kind == "homography"
    assert {_rotation_cw(d) for d in state.detections} == {0}
    # photo-estimated centres are self-consistent to well under the 0.025 uv pad tolerance
    assert state.rms_uv < 0.01, state.rms_uv
    # the board quad covers most of the upright frame
    from perception.geometry import board_quad_px
    quad = board_quad_px(state.homography)
    assert quad[:, 0].min() > -0.15 * upright.shape[1] and quad[:, 0].max() < 1.15 * upright.shape[1]
