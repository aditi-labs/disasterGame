from __future__ import annotations

import numpy as np
import pytest

from perception.geometry import (
    BoardGeometry,
    apply_homography,
    board_quad_px,
    camera_px_to_uv,
    homography_from_points,
    parallax_correct_mm,
    quad_displacement_uv,
    reprojection_errors,
    uv_to_camera_px,
)


def test_uv_mm_warp_round_trips():
    g = BoardGeometry(420, 420, 2.0)
    assert g.warp_size == (840, 840)
    uv = np.array([0.25, 0.75])
    assert np.allclose(g.mm_to_uv(g.uv_to_mm(uv)), uv)
    assert np.allclose(g.warp_px_to_uv(g.uv_to_warp_px(uv)), uv)
    assert np.allclose(g.warp_px_to_mm(g.mm_to_warp_px([100, 50])), [100, 50])
    assert g.area_px_to_mm2(4.0) == 1.0


def test_homography_from_four_points_maps_corners_exactly():
    src = np.array([[100, 80], [1180, 95], [1200, 700], [90, 690]], dtype=np.float64)
    dst = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    h, kind = homography_from_points(src, dst)
    assert kind == "homography"
    assert np.allclose(camera_px_to_uv(h, src), dst, atol=1e-6)
    assert np.allclose(uv_to_camera_px(h, dst), src, atol=1e-3)
    assert np.allclose(board_quad_px(h), src, atol=1e-3)
    rms_uv, rms_px, res = reprojection_errors(h, src, dst)
    assert rms_uv < 1e-6 and rms_px < 1e-3 and len(res) == 4


def test_three_points_give_affine_and_fewer_fail():
    src = np.array([[0, 0], [100, 0], [0, 100]], dtype=np.float64)
    dst = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float64)
    h, kind = homography_from_points(src, dst)
    assert kind == "affine"
    assert np.allclose(apply_homography(h, [[50, 50]]), [[0.5, 0.5]])
    h2, kind2 = homography_from_points(src[:2], dst[:2])
    assert h2 is None and kind2 == "insufficient"


def test_ransac_path_ignores_an_outlier():
    rng = np.random.default_rng(0)
    dst = rng.uniform(0, 1, size=(12, 2))
    true_h = np.array([[900, 40, 150], [-30, 600, 60], [0.0001, 0.00005, 1]])
    src = apply_homography(np.linalg.inv(np.linalg.inv(true_h)), dst)  # px = true_h @ uv
    src[3] += [60, -45]  # outlier
    h, kind = homography_from_points(src, dst, ransac_from=8, ransac_threshold_px=3.0)
    assert kind == "homography"
    inliers = [i for i in range(12) if i != 3]
    assert np.allclose(camera_px_to_uv(h, src[inliers]), dst[inliers], atol=1e-4)


def test_quad_displacement_is_zero_for_identical_and_positive_for_shifted():
    src = np.array([[100, 80], [1180, 95], [1200, 700], [90, 690]], dtype=np.float64)
    dst = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    h, _ = homography_from_points(src, dst)
    h2, _ = homography_from_points(src + [30, 0], dst)
    assert quad_displacement_uv(h, h) < 1e-9
    assert quad_displacement_uv(h, h2) > 0.02


def test_parallax_correction_moves_towards_camera_nadir_by_h_over_cz():
    cam = (210.0, 210.0, 1000.0)
    plane_hit = np.array([310.0, 210.0])  # 100 mm right of nadir
    corrected = parallax_correct_mm(plane_hit, cam, 20.0)
    # t = (1000-20)/1000 = 0.98 -> 98 mm from nadir
    assert np.allclose(corrected, [308.0, 210.0])
    # nothing moves at the nadir, and a camera lower than the piece is left untouched
    assert np.allclose(parallax_correct_mm([210.0, 210.0], cam, 20.0), [210.0, 210.0])
    assert np.allclose(parallax_correct_mm(plane_hit, (210.0, 210.0, 10.0), 20.0), plane_hit)
