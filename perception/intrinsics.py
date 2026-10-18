"""Optional camera intrinsics and undistortion (spec 6.4).

Lens distortion matters for a wide phone camera (DroidCam) looking at a 420 mm
board with 0.025 UV (10.5 mm) pad tolerances.  If a calibration file exists the
capture worker undistorts every frame before ArUco detection; if it does not, the
service runs undistorted-free and says so in its status.  Nothing is guessed.

File format (JSON)::

    {"image_size": [1280, 720],
     "camera_matrix": [[fx,0,cx],[0,fy,cy],[0,0,1]],
     "dist_coeffs": [k1,k2,p1,p2,k3],
     "rms_reprojection_px": 0.31, "calibrated_on": "...", "source": "..."}
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]


@dataclass
class Intrinsics:
    camera_matrix: np.ndarray      # 3x3
    dist_coeffs: np.ndarray        # (n,)
    image_size: tuple[int, int]    # (w, h)
    approximate: bool = False      # True when derived from image size, not measured
    rms_reprojection_px: float | None = None
    source: str | None = None

    @staticmethod
    def load(path: str | Path) -> "Intrinsics":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return Intrinsics(
            camera_matrix=np.asarray(data["camera_matrix"], dtype=np.float64).reshape(3, 3),
            dist_coeffs=np.asarray(data.get("dist_coeffs", [0, 0, 0, 0, 0]), dtype=np.float64).ravel(),
            image_size=(int(data["image_size"][0]), int(data["image_size"][1])),
            approximate=False,
            rms_reprojection_px=data.get("rms_reprojection_px"),
            source=str(path),
        )

    @staticmethod
    def approximate_for(width: int, height: int, horizontal_fov_deg: float = 62.0) -> "Intrinsics":
        """Pinhole guess from image size, for parallax correction only.

        Flagged ``approximate``; the service reports it as such.  Not used for
        undistortion (no distortion is assumed) and never written to disk as a
        measured calibration.
        """
        fx = width / (2.0 * np.tan(np.deg2rad(horizontal_fov_deg) / 2.0))
        k = np.array([[fx, 0, width / 2.0], [0, fx, height / 2.0], [0, 0, 1]], dtype=np.float64)
        return Intrinsics(k, np.zeros(5), (width, height), approximate=True, source="approximate_from_image_size")

    def save(self, path: str | Path, *, calibrated_on: str | None = None) -> None:
        if self.approximate:
            raise ValueError("refusing to save approximate intrinsics as a calibration file")
        payload = {
            "image_size": list(self.image_size),
            "camera_matrix": self.camera_matrix.tolist(),
            "dist_coeffs": self.dist_coeffs.tolist(),
            "rms_reprojection_px": self.rms_reprojection_px,
            "calibrated_on": calibrated_on,
            "source": self.source,
        }
        Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class Undistorter:
    """Cached remap for a fixed frame size."""

    def __init__(self, intrinsics: Intrinsics):
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")
        self.intrinsics = intrinsics
        self._maps: tuple[np.ndarray, np.ndarray] | None = None
        self._size: tuple[int, int] | None = None
        self.new_camera_matrix: np.ndarray = intrinsics.camera_matrix

    def __call__(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if self._maps is None or self._size != (w, h):
            new_k, _ = cv2.getOptimalNewCameraMatrix(self.intrinsics.camera_matrix, self.intrinsics.dist_coeffs,
                                                     (w, h), alpha=0.0)
            self.new_camera_matrix = new_k
            self._maps = cv2.initUndistortRectifyMap(self.intrinsics.camera_matrix, self.intrinsics.dist_coeffs,
                                                     None, new_k, (w, h), cv2.CV_16SC2)
            self._size = (w, h)
        return cv2.remap(frame, self._maps[0], self._maps[1], interpolation=cv2.INTER_LINEAR)


def calibrate_from_chessboard(frames: list[np.ndarray], pattern_size: tuple[int, int] = (9, 6),
                              square_mm: float = 25.0) -> Intrinsics | None:
    """Standard OpenCV chessboard calibration on operator-captured frames.

    Returns None when fewer than 5 frames contain the full pattern.
    """
    if cv2 is None:
        raise ImportError("opencv-contrib-python required")
    objp = np.zeros((pattern_size[0] * pattern_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2) * square_mm
    obj_points, img_points = [], []
    size = None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        size = (gray.shape[1], gray.shape[0])
        found, corners = cv2.findChessboardCorners(gray, pattern_size, None)
        if not found:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        obj_points.append(objp)
        img_points.append(corners)
    if size is None or len(obj_points) < 5:
        return None
    rms, k, dist, _, _ = cv2.calibrateCamera(obj_points, img_points, size, None, None)
    return Intrinsics(k, dist.ravel(), size, approximate=False, rms_reprojection_px=float(rms),
                      source=f"chessboard:{len(obj_points)}_frames")
