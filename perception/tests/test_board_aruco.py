from __future__ import annotations

import numpy as np
import pytest

from perception.board_aruco import BoardRegistrar, BoardRegistration, MEASURED_STATUS, scan_dictionaries, summarize_for_measurement
from perception.geometry import camera_px_to_uv, apply_homography

from .conftest import MARKER_UVS, SyntheticBoard, camera_homography, make_registration, render_camera


def _setup(registration, board: SyntheticBoard | None = None):
    board = board or SyntheticBoard()
    h_b2c = camera_homography(board.geometry)
    cam = render_camera(board.empty, h_b2c)
    registrar = BoardRegistrar(registration, grace_ms=1000, jump_tolerance_uv=0.02)
    return board, h_b2c, cam, registrar


def _true_uv(board: SyntheticBoard, h_b2c: np.ndarray, px) -> np.ndarray:
    warp_px = apply_homography(np.linalg.inv(h_b2c), px)
    return board.geometry.warp_px_to_uv(warp_px)


def test_detects_all_registered_markers_and_registers_with_sixteen_points(registration):
    board, h_b2c, cam, registrar = _setup(registration)
    state = registrar.update(cam, now_ms=1000)
    assert state.valid and not state.held and state.transform_kind == "homography"
    assert state.markers_used == [10, 11, 12, 13]
    assert state.points_used == 16
    assert state.rms_uv < 0.002, state.rms_uv
    assert state.rms_px < 1.5, state.rms_px
    # arbitrary camera pixels map to the UV the synthetic camera was built from
    probes = np.array([[640, 360], [500, 200], [900, 600]], dtype=np.float64)
    got = camera_px_to_uv(state.homography, probes)
    assert np.allclose(got, _true_uv(board, h_b2c, probes), atol=0.003)


def test_registration_file_round_trip_and_status_flags(tmp_path):
    reg = make_registration(tmp_path)
    loaded = BoardRegistration.load(reg.path)
    assert loaded.markers[12].center_uv == MARKER_UVS[12]
    assert loaded.uses_corners and not loaded.verified
    loaded.status = MEASURED_STATUS
    for m in loaded.markers.values():
        m.verified = True
    assert loaded.verified
    loaded.save()
    assert BoardRegistration.load(reg.path).verified


def test_partial_occlusion_keeps_registering_with_corner_points(registration):
    board, h_b2c, cam, registrar = _setup(registration)
    full = registrar.update(cam, now_ms=1000)
    occluded = cam.copy()
    # cover marker 12 (bottom-right) with a "hand"
    px = apply_homography(h_b2c, board.geometry.uv_to_warp_px(MARKER_UVS[12]).reshape(1, 2))[0]
    import cv2
    cv2.circle(occluded, (int(px[0]), int(px[1])), 60, (60, 50, 45), -1)
    state = registrar.update(occluded, now_ms=1040)
    assert state.valid
    assert 12 not in state.markers_used and len(state.markers_used) == 3
    probes = np.array([[640, 360], [1000, 650]], dtype=np.float64)
    assert np.allclose(camera_px_to_uv(state.homography, probes), camera_px_to_uv(full.homography, probes), atol=0.004)


def test_centres_only_mode_needs_four_markers_and_holds_through_occlusion(centers_only_registration):
    board, h_b2c, cam, registrar = _setup(centers_only_registration)
    state = registrar.update(cam, now_ms=1000)
    assert state.valid and state.points_used == 4 and state.transform_kind == "homography"
    occluded = cam.copy()
    px = apply_homography(h_b2c, board.geometry.uv_to_warp_px(MARKER_UVS[11]).reshape(1, 2))[0]
    import cv2
    cv2.circle(occluded, (int(px[0]), int(px[1])), 60, (60, 50, 45), -1)
    held = registrar.update(occluded, now_ms=1200)
    assert held.valid and held.held and held.degraded  # affine from 3 centres is refused in favour of the hold
    assert np.allclose(held.homography, state.homography)
    expired = registrar.update(occluded, now_ms=1000 + 1000 + 500)
    # past the grace period a 3-centre affine is all we have: valid but flagged
    assert expired.transform_kind in ("affine", "none")
    assert expired.degraded


def test_lost_markers_hold_then_expire(registration):
    board, h_b2c, cam, registrar = _setup(registration)
    good = registrar.update(cam, now_ms=1000)
    blank = np.full_like(cam, 90)
    held = registrar.update(blank, now_ms=1500)
    assert held.valid and held.held and np.allclose(held.homography, good.homography)
    gone = registrar.update(blank, now_ms=3000)
    assert not gone.valid and gone.homography is None
    assert "need" in gone.reason


def test_board_jump_with_fewer_markers_is_refused_within_grace(registration):
    board, h_b2c, cam, registrar = _setup(registration)
    registrar.update(cam, now_ms=1000)
    # Shift the whole camera view (board slides) while hiding one marker: a real
    # occlusion never moves the board, so the solver must hold rather than jump.
    import cv2
    shifted = np.full_like(cam, 90)
    shifted[:, 80:] = cam[:, :-80]
    px = apply_homography(h_b2c, board.geometry.uv_to_warp_px(MARKER_UVS[13]).reshape(1, 2))[0]
    cv2.circle(shifted, (int(px[0]) + 80, int(px[1])), 60, (60, 50, 45), -1)
    state = registrar.update(shifted, now_ms=1100)
    assert state.held and "jump" in state.reason
    # Once all four are back the new pose is accepted even though it moved.
    full_shift = np.full_like(cam, 90)
    full_shift[:, 80:] = cam[:, :-80]
    accepted = registrar.update(full_shift, now_ms=1200)
    assert accepted.valid and not accepted.held and accepted.markers_used == [10, 11, 12, 13]


def test_orientation_solver_recovers_rotated_markers(tmp_path):
    rotations = {10: 90, 11: 0, 12: 270, 13: 180}
    board = SyntheticBoard(rotations=rotations)
    reg = make_registration(tmp_path)  # file says 0 for all
    board, h_b2c, cam, registrar = _setup(reg, board)
    wrong = registrar.update(cam, now_ms=1000)
    solved = registrar.solve_orientations(wrong.detections)
    assert {k: v * 90 for k, v in solved.items()} == rotations
    for mid, steps in solved.items():
        reg.markers[mid].rotation_deg = steps * 90
    registrar.reset_hold()
    right = registrar.update(cam, now_ms=2000)
    assert right.rms_uv < 0.002 and right.rms_uv < wrong.rms_uv


def test_unknown_ids_are_reported_not_used(tmp_path):
    board = SyntheticBoard()
    reg = make_registration(tmp_path)
    del reg.markers[13]
    board, h_b2c, cam, registrar = _setup(reg, board)
    state = registrar.update(cam, now_ms=1)
    assert state.valid and state.unknown_ids == [13] and 13 not in state.markers_used


def test_dictionary_scan_finds_the_printed_family(board):
    cam = render_camera(board.empty, camera_homography(board.geometry))
    found = scan_dictionaries(cam, ["DICT_4X4_100", "DICT_5X5_100", "DICT_6X6_250"])
    assert found.get("DICT_4X4_100") == [10, 11, 12, 13]
    assert "DICT_6X6_250" not in found


def test_measurement_summary_records_only_measured_values(registration):
    board, h_b2c, cam, registrar = _setup(registration)
    state = registrar.update(cam, now_ms=1)
    m = summarize_for_measurement(state, registration, camera_source="recording:test", frame_size=(1280, 720))
    assert m["markers_used"] == [10, 11, 12, 13] and m["points_used"] == 16
    assert m["reprojection_rms_uv"] == state.rms_uv and m["detected_ids_all"] == [10, 11, 12, 13]


def test_camera_pose_height_is_recovered_with_approximate_intrinsics(registration):
    from perception.intrinsics import Intrinsics
    board, h_b2c, cam, registrar = _setup(registration)
    approx = Intrinsics.approximate_for(1280, 720)
    registrar.camera_matrix, registrar.dist_coeffs, registrar.intrinsics_approximate = approx.camera_matrix, approx.dist_coeffs, True
    state = registrar.update(cam, now_ms=1)
    assert state.camera_pose is not None and state.camera_pose.approximate
    x, y, z = state.camera_pose.position_mm
    assert z > 200  # a plausible overhead distance; the synthetic view is a projective fiction, so only sanity
    assert 0 < x < 420 * 1.5 and -420 < y < 420 * 1.5
