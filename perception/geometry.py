"""Image (px) <-> board UV <-> board mm transforms (spec 6.3, 6.5, 6.9, section 8 chain).

Frames of reference used by the perception service:

* **camera px** - pixels of the (optionally undistorted) camera frame.
* **board UV** - normalised board coordinates, (0,0) top-left, (1,1) bottom-right,
  as the world and the projector use them.
* **board mm** - UV scaled by the physical board size (420 x 420 mm per scenario).
* **warp px** - a synthetic top-down raster of the board plane at a fixed
  pixels-per-mm, where piece sizes are perspective-free and gates can be set in mm.

The camera-to-board homography maps camera px -> UV.  The projector-to-board
transform is a *separate* calibration owned by the UI lane and never mixed in here.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

UNIT_SQUARE = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=np.float64)


@dataclass(frozen=True)
class BoardGeometry:
    width_mm: float
    height_mm: float
    px_per_mm: float = 2.0

    @property
    def warp_size(self) -> tuple[int, int]:
        """(width_px, height_px) of the top-down raster."""
        return int(round(self.width_mm * self.px_per_mm)), int(round(self.height_mm * self.px_per_mm))

    # ---- UV <-> mm
    def uv_to_mm(self, uv) -> np.ndarray:
        arr = np.asarray(uv, dtype=np.float64)
        return arr * np.array([self.width_mm, self.height_mm])

    def mm_to_uv(self, mm) -> np.ndarray:
        arr = np.asarray(mm, dtype=np.float64)
        return arr / np.array([self.width_mm, self.height_mm])

    # ---- warp px <-> UV / mm
    def warp_px_to_uv(self, px) -> np.ndarray:
        w, h = self.warp_size
        arr = np.asarray(px, dtype=np.float64)
        return arr / np.array([w, h])

    def uv_to_warp_px(self, uv) -> np.ndarray:
        w, h = self.warp_size
        return np.asarray(uv, dtype=np.float64) * np.array([w, h])

    def warp_px_to_mm(self, px) -> np.ndarray:
        return np.asarray(px, dtype=np.float64) / self.px_per_mm

    def mm_to_warp_px(self, mm) -> np.ndarray:
        return np.asarray(mm, dtype=np.float64) * self.px_per_mm

    def mm_to_px_len(self, mm: float) -> float:
        return float(mm) * self.px_per_mm

    def px_to_mm_len(self, px: float) -> float:
        return float(px) / self.px_per_mm

    def area_px_to_mm2(self, area_px: float) -> float:
        return float(area_px) / (self.px_per_mm ** 2)

    # ---- homography helpers
    def uv_to_warp_matrix(self) -> np.ndarray:
        w, h = self.warp_size
        return np.array([[w, 0, 0], [0, h, 0], [0, 0, 1]], dtype=np.float64)

    def camera_to_warp_matrix(self, h_cam_to_uv: np.ndarray) -> np.ndarray:
        return self.uv_to_warp_matrix() @ h_cam_to_uv


def apply_homography(h: np.ndarray, points) -> np.ndarray:
    """Apply a 3x3 projective transform to an (N,2) array of points."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    ones = np.ones((pts.shape[0], 1))
    hom = (h @ np.hstack([pts, ones]).T).T
    w = hom[:, 2:3]
    w = np.where(np.abs(w) < 1e-12, 1e-12, w)
    return hom[:, :2] / w


def camera_px_to_uv(h_cam_to_uv: np.ndarray, px) -> np.ndarray:
    return apply_homography(h_cam_to_uv, px)


def uv_to_camera_px(h_cam_to_uv: np.ndarray, uv) -> np.ndarray:
    return apply_homography(np.linalg.inv(h_cam_to_uv), uv)


def board_quad_px(h_cam_to_uv: np.ndarray) -> np.ndarray:
    """The board's unit square expressed in camera pixels (4,2): TL, TR, BR, BL."""
    return uv_to_camera_px(h_cam_to_uv, UNIT_SQUARE)


def warp_board(frame: np.ndarray, h_cam_to_uv: np.ndarray, geometry: BoardGeometry,
               interpolation: int | None = None) -> np.ndarray:
    """Render the board plane as a top-down raster."""
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    m = geometry.camera_to_warp_matrix(h_cam_to_uv)
    flags = cv2.INTER_LINEAR if interpolation is None else interpolation
    return cv2.warpPerspective(frame, m, geometry.warp_size, flags=flags)


def homography_from_points(src_px: np.ndarray, dst_uv: np.ndarray, *, ransac_from: int = 8,
                           ransac_threshold_px: float = 3.0) -> tuple[np.ndarray | None, str]:
    """Solve camera px -> UV.

    Returns ``(H, kind)`` with kind ``"homography"`` (>= 4 points), ``"affine"``
    (exactly 3 points, degraded: no perspective term) or ``(None, "insufficient")``.
    RANSAC is used only with enough redundancy, and the threshold is applied in the
    *pixel* domain by solving px <- UV and inverting, so the UV scale does not make
    the threshold meaningless.
    """
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    src = np.asarray(src_px, dtype=np.float64).reshape(-1, 2)
    dst = np.asarray(dst_uv, dtype=np.float64).reshape(-1, 2)
    n = src.shape[0]
    if n >= 4:
        if n >= ransac_from:
            h_uv_to_px, _ = cv2.findHomography(dst, src, cv2.RANSAC, ransac_threshold_px)
        else:
            h_uv_to_px, _ = cv2.findHomography(dst, src, 0)
        if h_uv_to_px is None or abs(np.linalg.det(h_uv_to_px)) < 1e-15:
            return None, "degenerate"
        return np.linalg.inv(h_uv_to_px), "homography"
    if n == 3:
        a, _ = cv2.estimateAffine2D(src.astype(np.float32), dst.astype(np.float32), method=cv2.LMEDS)
        if a is None:
            return None, "degenerate"
        h = np.vstack([a, [0.0, 0.0, 1.0]])
        return h, "affine"
    return None, "insufficient"


def reprojection_errors(h_cam_to_uv: np.ndarray, src_px: np.ndarray, dst_uv: np.ndarray) -> tuple[float, float, np.ndarray]:
    """RMS error in UV, RMS error in px, and per-point UV residual norms."""
    src = np.asarray(src_px, dtype=np.float64).reshape(-1, 2)
    dst = np.asarray(dst_uv, dtype=np.float64).reshape(-1, 2)
    pred_uv = apply_homography(h_cam_to_uv, src)
    res_uv = np.linalg.norm(pred_uv - dst, axis=1)
    rms_uv = float(np.sqrt(np.mean(res_uv ** 2))) if len(res_uv) else float("nan")
    try:
        pred_px = apply_homography(np.linalg.inv(h_cam_to_uv), dst)
        res_px = np.linalg.norm(pred_px - src, axis=1)
        rms_px = float(np.sqrt(np.mean(res_px ** 2))) if len(res_px) else float("nan")
    except np.linalg.LinAlgError:
        rms_px = float("nan")
    return rms_uv, rms_px, res_uv


def quad_displacement_uv(h_a: np.ndarray, h_b: np.ndarray) -> float:
    """Largest movement (in UV) of the four board corners between two registrations.

    Both homographies map camera px -> UV; the comparison is done in camera space
    (where the board corners are) and mapped through the *other* homography, which
    is what an occlusion-induced jump looks like to downstream UV consumers.
    """
    quad_a = board_quad_px(h_a)
    moved = apply_homography(h_b, quad_a)
    return float(np.max(np.linalg.norm(moved - UNIT_SQUARE, axis=1)))


def polygon_mask(shape_hw: tuple[int, int], polygons_px: list[np.ndarray], value: int = 255) -> np.ndarray:
    """Rasterise polygons (each (N,2) px) into a uint8 mask."""
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    mask = np.zeros(shape_hw[:2], dtype=np.uint8)
    for poly in polygons_px:
        pts = np.asarray(poly, dtype=np.int32).reshape(-1, 1, 2)
        if len(pts) >= 3:
            cv2.fillPoly(mask, [pts], value)
    return mask


def dilate_mask(mask: np.ndarray, radius_px: int) -> np.ndarray:
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    if radius_px <= 0:
        return mask
    k = 2 * int(radius_px) + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.dilate(mask, kernel)


# ---------------------------------------------------------------- parallax
@dataclass(frozen=True)
class CameraPose:
    """Camera centre in board millimetres (x right, y down, z up out of the board)."""

    position_mm: tuple[float, float, float]
    approximate: bool
    rvec: np.ndarray
    tvec: np.ndarray


def solve_camera_pose(object_points_mm: np.ndarray, image_points_px: np.ndarray, camera_matrix: np.ndarray,
                      dist_coeffs: np.ndarray | None, *, approximate: bool) -> CameraPose | None:
    """PnP on board-plane points (z=0) to recover the camera position above the board."""
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    obj = np.asarray(object_points_mm, dtype=np.float64).reshape(-1, 2)
    if obj.shape[0] < 4:
        return None
    obj3 = np.hstack([obj, np.zeros((obj.shape[0], 1))])
    img = np.asarray(image_points_px, dtype=np.float64).reshape(-1, 2)
    dist = np.zeros(5) if dist_coeffs is None else np.asarray(dist_coeffs, dtype=np.float64)
    flags = cv2.SOLVEPNP_IPPE if obj.shape[0] >= 4 else cv2.SOLVEPNP_ITERATIVE
    ok, rvec, tvec = cv2.solvePnP(obj3, img, np.asarray(camera_matrix, dtype=np.float64), dist, flags=flags)
    if not ok:
        return None
    rot, _ = cv2.Rodrigues(rvec)
    cam_in_board = (-rot.T @ tvec).ravel()
    # OpenCV's board frame here has z pointing *into* the board when y is down and x is right
    # (right-handed: x right, y down => z away from the viewer).  The camera sits at negative z;
    # we report height as a positive "up" distance for readability.
    position = (float(cam_in_board[0]), float(cam_in_board[1]), float(-cam_in_board[2]))
    return CameraPose(position_mm=position, approximate=approximate, rvec=rvec, tvec=tvec)


def parallax_correct_mm(point_mm_at_plane, camera_position_mm: tuple[float, float, float],
                        object_height_mm: float) -> np.ndarray:
    """Move a board-plane intersection to the true footprint centre of a raised object.

    A piece top at height ``h`` is seen along a ray from the camera; the homography
    intersects that ray with the board plane (z=0), which displaces the point away
    from the camera's nadir by ``h / Cz`` of the horizontal distance.  Walking back
    along the ray gives the top-centre's horizontal position, which for a
    vertical-sided piece is its contact footprint centre (spec 6.9).
    """
    p0 = np.asarray(point_mm_at_plane, dtype=np.float64)
    cx, cy, cz = camera_position_mm
    if cz <= object_height_mm or cz <= 1e-6:
        return p0
    t = (cz - object_height_mm) / cz
    c = np.array([cx, cy])
    return c + t * (p0 - c)


def contour_centroid(contour: np.ndarray) -> tuple[float, float] | None:
    """Area centroid of a contour (not the bounding-box centre)."""
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    m = cv2.moments(contour)
    if abs(m["m00"]) < 1e-9:
        return None
    return float(m["m10"] / m["m00"]), float(m["m01"] / m["m00"])


def oriented_box(contour: np.ndarray) -> tuple[tuple[float, float], tuple[float, float], float]:
    """((cx, cy), (long, short), long_axis_angle_deg) of the minimum-area rectangle.

    Angle is measured in image convention (x right, y down), 0 = long axis along +x,
    normalised to [0, 180).
    """
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    (cx, cy), (w, h), angle = cv2.minAreaRect(contour)
    if w >= h:
        long_side, short_side, long_angle = w, h, angle
    else:
        long_side, short_side, long_angle = h, w, angle + 90.0
    long_angle = float(long_angle % 180.0)
    return (float(cx), float(cy)), (float(long_side), float(max(short_side, 1e-6))), long_angle
