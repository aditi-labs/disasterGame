"""Physical piece candidate proposals on the top-down board plane (spec 6.5, 6.9, 6.10).

Approach: a *reference* of the known-empty board (median of several warped frames)
is compared to each new warped frame.  Change is measured three ways and fused:

* gain-matched intensity difference (handles auto-exposure drift),
* Lab chroma difference (a coloured piece at the same luminance as the print),
* optionally an edge-structure difference (``structure_gate``), which a flat
  projected glow does not produce but a physical object does - the projector-safe mode.

Cast shadows (darker, chroma preserved) are suppressed so a piece's shadow does not
displace its footprint centroid.  Registered marker areas, operator-declared
projected UI areas and anything outside the board are masked out.  Blobs are gated
by physical area in mm^2, and large blobs touching the board edge are treated as
hands/sleeves.

Nothing here assigns a class.  Colour statistics are *reported* for Dev 2's fusion.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from .config import CandidateConfig
from .events import Appearance
from .geometry import BoardGeometry, contour_centroid, dilate_mask, oriented_box, polygon_mask


@dataclass
class Candidate:
    center_warp_px: tuple[float, float]     # area centroid of the non-shadow footprint
    center_mm: tuple[float, float]
    contour: np.ndarray
    bbox_warp_px: tuple[int, int, int, int]
    area_mm2: float
    bbox_mm: tuple[float, float]            # oriented (long, short)
    elongation: float
    orientation_deg: float                  # long axis angle on the board, [0,180)
    touches_board_edge: bool
    appearance: Appearance
    fill_ratio: float                       # contour area / oriented box area

    @property
    def crop_box(self) -> tuple[int, int, int, int]:
        return self.bbox_warp_px


class ReferenceModel:
    """Median image of the empty board on the warped plane."""

    def __init__(self) -> None:
        self.gray: np.ndarray | None = None
        self.lab: np.ndarray | None = None
        self.edges: np.ndarray | None = None
        self.captured_at_ms: int | None = None
        self.frame_count = 0

    @property
    def ready(self) -> bool:
        return self.gray is not None

    def capture(self, warped_frames: list[np.ndarray], now_ms: int) -> None:
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")
        if not warped_frames:
            raise ValueError("no frames to build a reference from")
        stack = np.stack([f for f in warped_frames]).astype(np.float32)
        median_bgr = np.median(stack, axis=0).astype(np.uint8)
        self.gray = cv2.GaussianBlur(cv2.cvtColor(median_bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        self.lab = cv2.GaussianBlur(cv2.cvtColor(median_bgr, cv2.COLOR_BGR2LAB), (5, 5), 0)
        self.edges = _edge_magnitude(self.gray)
        self.captured_at_ms = now_ms
        self.frame_count = len(warped_frames)

    def clear(self) -> None:
        self.gray = self.lab = self.edges = None
        self.captured_at_ms = None
        self.frame_count = 0


def _edge_magnitude(gray: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    return np.clip(mag / 4.0, 0, 255).astype(np.uint8)


def _odd(n: int) -> int:
    n = max(1, int(n))
    return n if n % 2 == 1 else n + 1


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill regions fully enclosed by the mask (flood from the border, invert)."""
    h, w = mask.shape[:2]
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood = padded.copy()
    ff_mask = np.zeros((h + 4, w + 4), dtype=np.uint8)
    cv2.floodFill(flood, ff_mask, (0, 0), 255)
    holes = cv2.bitwise_not(flood)[1:-1, 1:-1]
    return cv2.bitwise_or(mask, holes)


class CandidateDetector:
    def __init__(self, cfg: CandidateConfig, geometry: BoardGeometry):
        if cv2 is None:
            raise ImportError("opencv-contrib-python required")
        self.cfg = cfg
        self.geometry = geometry
        self.reference = ReferenceModel()
        self.changed_fraction = 0.0
        self.last_change_mask: np.ndarray | None = None
        w, h = geometry.warp_size
        self._board_mask = np.full((h, w), 255, dtype=np.uint8)
        self._static_exclusion = np.zeros((h, w), dtype=np.uint8)
        self._edge_band = np.zeros((h, w), dtype=np.uint8)
        band = max(1, int(round(geometry.mm_to_px_len(3.0))))
        self._edge_band[:band, :] = 255
        self._edge_band[-band:, :] = 255
        self._edge_band[:, :band] = 255
        self._edge_band[:, -band:] = 255
        self.set_static_exclusions([], [])

    # ---- masks
    def set_static_exclusions(self, marker_polys_uv: list[np.ndarray], projected_polys_uv: list[list[list[float]]],
                              marker_margin_mm: float = 6.0) -> None:
        """Registered marker areas (dilated by a margin) and declared projected UI zones, in UV."""
        w, h = self.geometry.warp_size
        polys_px = [self.geometry.uv_to_warp_px(np.asarray(p)) for p in marker_polys_uv]
        margin_px = int(round(self.geometry.mm_to_px_len(marker_margin_mm)))
        marker_mask = dilate_mask(polygon_mask((h, w), polys_px), margin_px)
        projected = polygon_mask((h, w), [self.geometry.uv_to_warp_px(np.asarray(p)) for p in projected_polys_uv])
        self._static_exclusion = cv2.bitwise_or(marker_mask, projected)

    @property
    def static_exclusion_mask(self) -> np.ndarray:
        return self._static_exclusion

    # ---- reference
    def capture_reference(self, warped_frames: list[np.ndarray], now_ms: int) -> None:
        self.reference.capture(warped_frames, now_ms)

    @property
    def reference_ready(self) -> bool:
        return self.reference.ready

    # ---- detection
    def change_mask(self, warped_bgr: np.ndarray, dynamic_exclusion: np.ndarray | None = None) -> np.ndarray:
        ref = self.reference
        if not ref.ready:
            raise RuntimeError("reference not captured")
        cfg = self.cfg
        gray = cv2.GaussianBlur(cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        lab = cv2.GaussianBlur(cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2LAB), (5, 5), 0)
        valid = cv2.bitwise_and(self._board_mask, cv2.bitwise_not(self._static_exclusion))
        if dynamic_exclusion is not None:
            valid = cv2.bitwise_and(valid, cv2.bitwise_not(dynamic_exclusion))

        # Gain-matched intensity change.  The gain comes from the *median* brightness ratio so
        # a bright piece covering a few percent of the board cannot drag the gain down and
        # hide itself (a mean-based gain does exactly that on a pale print).
        # Subsampled (every 8th row/col): the median of ~15k pixels equals the median of ~1M for
        # this purpose and costs a fraction of a millisecond instead of tens of milliseconds.
        sub = (slice(None, None, 8), slice(None, None, 8))
        valid_idx = valid[sub] > 0
        if valid_idx.any():
            ratio_all = ref.gray[sub][valid_idx].astype(np.float32) / np.maximum(gray[sub][valid_idx].astype(np.float32), 1.0)
            gain = float(np.clip(np.median(ratio_all), cfg.gain_clip[0], cfg.gain_clip[1]))
        else:
            gain = 1.0
        gray_matched = np.clip(gray.astype(np.float32) * gain, 0, 255).astype(np.uint8)
        intensity_diff = cv2.absdiff(gray_matched, ref.gray)
        _, intensity_change = cv2.threshold(intensity_diff, cfg.diff_threshold, 255, cv2.THRESH_BINARY)

        # Chroma change (a/b channels).
        ab_diff = cv2.absdiff(lab[..., 1:], ref.lab[..., 1:]).max(axis=2)
        _, chroma_change = cv2.threshold(ab_diff, cfg.chroma_threshold, 255, cv2.THRESH_BINARY)

        change = cv2.bitwise_or(intensity_change, chroma_change)

        # Lighting-change signal is measured BEFORE shadow suppression and structure gating,
        # so a global exposure/projector shift still raises the operator warning.
        board_area = max(1, cv2.countNonZero(valid))
        self.changed_fraction = cv2.countNonZero(cv2.bitwise_and(change, valid)) / board_area

        edges = None
        if cfg.edge_assist or cfg.structure_gate:
            edges = _edge_magnitude(gray)
            edge_diff = cv2.absdiff(edges, ref.edges)
            _, structure = cv2.threshold(edge_diff, cfg.structure_threshold, 255, cv2.THRESH_BINARY)

        if cfg.edge_assist:
            # A low-contrast (white-on-pale) piece still has a rim: add changed edges and fill
            # enclosed holes so the whole footprint becomes one solid region.
            change = cv2.bitwise_or(change, structure)
            change = _fill_holes(change)

        if cfg.shadow_suppression:
            # Shadow: darker than reference but not too dark, chroma essentially unchanged,
            # and not on an edge that changed (a piece rim is kept).
            ratio = gray_matched.astype(np.float32) / np.maximum(ref.gray.astype(np.float32), 1.0)
            shadow = ((ratio < 0.97) & (ratio > cfg.shadow_min_ratio) & (ab_diff < cfg.chroma_threshold // 2))
            if cfg.edge_assist:
                shadow &= structure == 0
            change = cv2.bitwise_and(change, cv2.bitwise_not(shadow.astype(np.uint8) * 255))

        if cfg.structure_gate:
            gate = dilate_mask(structure, int(round(self.geometry.mm_to_px_len(4.0))))
            change = cv2.bitwise_and(change, gate)

        change = cv2.bitwise_and(change, valid)
        open_k = _odd(self.geometry.mm_to_px_len(cfg.open_kernel_mm))
        close_k = _odd(self.geometry.mm_to_px_len(cfg.close_kernel_mm))
        change = cv2.morphologyEx(change, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k)))
        change = cv2.morphologyEx(change, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k)))
        if cfg.edge_assist:
            change = _fill_holes(change)
        self.last_change_mask = change
        return change

    def detect(self, warped_bgr: np.ndarray, dynamic_exclusion: np.ndarray | None = None) -> list[Candidate]:
        change = self.change_mask(warped_bgr, dynamic_exclusion)
        contours, _ = cv2.findContours(change, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hsv = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2HSV)
        out: list[Candidate] = []
        h_img, w_img = change.shape[:2]
        for contour in contours:
            area_px = cv2.contourArea(contour)
            area_mm2 = self.geometry.area_px_to_mm2(area_px)
            if area_mm2 < self.cfg.min_area_mm2 or area_mm2 > self.cfg.max_area_mm2:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            touches = x <= 1 or y <= 1 or x + w >= w_img - 1 or y + h >= h_img - 1
            if touches and area_mm2 > self.cfg.edge_touch_max_area_mm2:
                continue  # hand or sleeve reaching in from the edge
            centroid = contour_centroid(contour)
            if centroid is None:
                continue
            (bcx, bcy), (long_px, short_px), angle = oriented_box(contour)
            long_mm, short_mm = self.geometry.px_to_mm_len(long_px), self.geometry.px_to_mm_len(short_px)
            box_area_px = max(long_px * short_px, 1e-6)
            appearance = _appearance(hsv, change, (x, y, w, h))
            out.append(Candidate(
                center_warp_px=centroid,
                center_mm=tuple(self.geometry.warp_px_to_mm(centroid).tolist()),
                contour=contour,
                bbox_warp_px=(int(x), int(y), int(w), int(h)),
                area_mm2=float(area_mm2),
                bbox_mm=(float(long_mm), float(short_mm)),
                elongation=float(long_mm / max(short_mm, 1e-6)),
                orientation_deg=float(angle),
                touches_board_edge=bool(touches),
                appearance=appearance,
                fill_ratio=float(area_px / box_area_px),
            ))
        out.sort(key=lambda c: -c.area_mm2)
        return out


def _appearance(hsv: np.ndarray, mask: np.ndarray, bbox: tuple[int, int, int, int]) -> Appearance:
    x, y, w, h = bbox
    roi = hsv[y:y + h, x:x + w]
    roi_mask = mask[y:y + h, x:x + w] > 0
    if roi_mask.sum() == 0:
        return Appearance((0.0, 0.0, 0.0), 0.0, 0.0)
    px = roi[roi_mask]
    hch, sch, vch = px[:, 0].astype(np.float32), px[:, 1].astype(np.float32), px[:, 2].astype(np.float32)
    yellow = ((hch >= 15) & (hch <= 40) & (sch >= 60) & (vch >= 60)).mean()
    white = ((sch <= 60) & (vch >= 150)).mean()
    return Appearance((float(hch.mean()), float(sch.mean()), float(vch.mean())), float(yellow), float(white))


def prepare_roi(crop_bgr: np.ndarray, orientation_deg: float | None, *, max_px: int = 320,
                canonical_rotation: bool = True) -> np.ndarray:
    """Make a classifier crop small and consistent (lag + accuracy).

    * ``canonical_rotation``: rotate so the piece's long axis is horizontal.  Perceptron then
      sees every bridge the same way the top-view reference photos show it, instead of at an
      arbitrary angle on the board.  The canvas is expanded so nothing is cut off.
    * ``max_px``: downscale the longest side; a 320 px crop uploads and infers far faster than
      a full-resolution one with no useful detail lost at this scale.
    """
    out = crop_bgr
    if canonical_rotation and orientation_deg is not None and out.size:
        h, w = out.shape[:2]
        angle = float(orientation_deg) % 180.0
        if angle > 90.0:
            angle -= 180.0  # rotate the short way
        if abs(angle) > 2.0:
            m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
            cos, sin = abs(m[0, 0]), abs(m[0, 1])
            new_w, new_h = int(h * sin + w * cos), int(h * cos + w * sin)
            m[0, 2] += new_w / 2.0 - w / 2.0
            m[1, 2] += new_h / 2.0 - h / 2.0
            out = cv2.warpAffine(out, m, (new_w, new_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if max_px and out.size:
        longest = max(out.shape[:2])
        if longest > max_px:
            scale = max_px / float(longest)
            out = cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return out


def crop_roi(warped_bgr: np.ndarray, bbox_warp_px: tuple[int, int, int, int], pad_px: int = 12) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Perspective-corrected crop for the classifier, with padding clamped to the board."""
    x, y, w, h = bbox_warp_px
    h_img, w_img = warped_bgr.shape[:2]
    x0, y0 = max(0, x - pad_px), max(0, y - pad_px)
    x1, y1 = min(w_img, x + w + pad_px), min(h_img, y + h + pad_px)
    return warped_bgr[y0:y1, x0:x1].copy(), (x0, y0, x1 - x0, y1 - y0)
