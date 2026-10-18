"""Operator-only debug rendering (spec 6.9 raw-vs-snapped, section 9 SHOW DEBUG).

Everything drawn here is for the operator laptop window.  Nothing in this module
is ever sent to the projector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

try:  # pragma: no cover
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

from .board_aruco import RegistrationState
from .events import ConfidenceBand
from .geometry import BoardGeometry, board_quad_px, uv_to_camera_px

COLORS = {
    "marker": (0, 200, 0),
    "marker_unknown": (140, 140, 140),
    "board": (255, 200, 0),
    "candidate": (160, 160, 160),
    "review": (0, 200, 255),
    "high": (0, 255, 120),
    "reject": (0, 0, 255),
    "moving": (255, 120, 0),
    "missing": (120, 0, 200),
    "pad": (255, 0, 255),
    "text": (255, 255, 255),
}


def load_sites(path: str | Path | None) -> list[dict[str, Any]]:
    """Real scenario pads for DEBUG display only.  Empty when no file is configured."""
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    sites = data.get("sites", data) if isinstance(data, dict) else data
    out = []
    for s in sites:
        if "board_uv" in s:
            out.append({"id": s.get("id"), "kind": s.get("kind"), "board_uv": tuple(s["board_uv"]),
                        "tolerance_uv": float(s.get("tolerance_uv", 0.025))})
    return out


def nearest_site(sites: list[dict[str, Any]], uv: tuple[float, float]) -> tuple[dict[str, Any] | None, float]:
    best, best_d = None, float("inf")
    for s in sites:
        d = float(np.hypot(s["board_uv"][0] - uv[0], s["board_uv"][1] - uv[1]))
        if d < best_d:
            best, best_d = s, d
    return best, best_d


def band_color(band: str | None, state: str) -> tuple[int, int, int]:
    if state == "moving":
        return COLORS["moving"]
    if state == "missing":
        return COLORS["missing"]
    if band == ConfidenceBand.HIGH.value:
        return COLORS["high"]
    if band == ConfidenceBand.REVIEW.value:
        return COLORS["review"]
    if band == ConfidenceBand.REJECT.value:
        return COLORS["reject"]
    return COLORS["candidate"]


def draw_camera_view(frame: np.ndarray, registration: RegistrationState, geometry: BoardGeometry,
                     tracks: list[dict[str, Any]], status_lines: list[str], sites: list[dict[str, Any]],
                     keys_hint: str) -> np.ndarray:
    out = frame.copy()
    for det in registration.detections:
        known = det.marker_id in registration.markers_used
        color = COLORS["marker"] if known else COLORS["marker_unknown"]
        cv2.polylines(out, [det.corners_px.astype(np.int32).reshape(-1, 1, 2)], True, color, 2)
        cx, cy = det.center_px
        cv2.putText(out, f"id{det.marker_id}", (int(cx) + 8, int(cy) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    if registration.valid and registration.homography is not None:
        quad = board_quad_px(registration.homography).astype(np.int32)
        cv2.polylines(out, [quad.reshape(-1, 1, 2)], True, COLORS["board"], 2 if not registration.held else 1)
        if sites:
            for s in sites:
                px = uv_to_camera_px(registration.homography, [s["board_uv"]])[0]
                cv2.circle(out, (int(px[0]), int(px[1])), 6, COLORS["pad"], 1)
        for t in tracks:
            uv = t.get("uv")
            if uv is None:
                continue
            px = uv_to_camera_px(registration.homography, [uv])[0]
            color = band_color(t.get("band"), t.get("state", ""))
            cv2.circle(out, (int(px[0]), int(px[1])), 10, color, 2)
            raw_uv = t.get("raw_uv")
            if raw_uv is not None and raw_uv != uv:
                rpx = uv_to_camera_px(registration.homography, [raw_uv])[0]
                cv2.circle(out, (int(rpx[0]), int(rpx[1])), 4, (200, 200, 200), 1)
                cv2.line(out, (int(rpx[0]), int(rpx[1])), (int(px[0]), int(px[1])), (200, 200, 200), 1)
            label = f"{t['track_id']} {t['state']} {t.get('piece_class') or '?'}"
            if t.get("band"):
                label += f" [{t['band']}]"
            cv2.putText(out, label, (int(px[0]) + 12, int(px[1]) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            if sites:
                site, d = nearest_site(sites, uv)
                if site is not None:
                    spx = uv_to_camera_px(registration.homography, [site["board_uv"]])[0]
                    within = d <= site["tolerance_uv"]
                    cv2.line(out, (int(px[0]), int(px[1])), (int(spx[0]), int(spx[1])),
                             COLORS["pad"] if within else (90, 90, 90), 1)
                    cv2.putText(out, f"{site['id']} {'in' if within else 'out'} {d:.3f}uv",
                                (int(px[0]) + 12, int(px[1]) + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLORS["pad"], 1)
    y = 22
    for line in status_lines:
        cv2.putText(out, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
        cv2.putText(out, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLORS["text"], 1)
        y += 20
    cv2.putText(out, keys_hint, (12, out.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return out


def draw_warp_view(warped: np.ndarray | None, change_mask: np.ndarray | None, candidates, tracks: list[dict[str, Any]],
                   geometry: BoardGeometry, exclusion: np.ndarray | None, show_mask: bool) -> np.ndarray | None:
    if warped is None:
        return None
    out = warped.copy()
    if show_mask and change_mask is not None:
        tint = np.zeros_like(out)
        tint[..., 2] = change_mask
        out = cv2.addWeighted(out, 0.7, tint, 0.6, 0)
    if exclusion is not None:
        tint = np.zeros_like(out)
        tint[..., 0] = exclusion
        out = cv2.addWeighted(out, 1.0, tint, 0.35, 0)
    for c in candidates or []:
        x, y, w, h = c.bbox_warp_px
        cv2.rectangle(out, (x, y), (x + w, y + h), (180, 180, 180), 1)
        cx, cy = c.center_warp_px
        cv2.circle(out, (int(cx), int(cy)), 3, (180, 180, 180), -1)
    for t in tracks:
        uv = t.get("uv")
        if uv is None:
            continue
        px = geometry.uv_to_warp_px(uv)
        color = band_color(t.get("band"), t.get("state", ""))
        cv2.circle(out, (int(px[0]), int(px[1])), 8, color, 2)
        cv2.putText(out, t["track_id"], (int(px[0]) + 10, int(px[1]) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return out
