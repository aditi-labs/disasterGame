"""Honest confidence scoring (spec 5, "Recommended acceptance rule").

``localization_confidence`` is a *local geometric quality* score built from measured
quantities: board reprojection error, whether the registration is held, track
position jitter, and distance from the board edge.  It is not a probability from
any model and is labelled as such in the observation's ``reason`` field.

``detection_confidence`` is Dev 2's reported value passed through, or ``None`` when
no classifier result exists.  Perception never invents a model confidence.

Bands:

* HIGH   - still for the required frames, class known with sufficient confidence,
           good localisation, inside the board.
* REVIEW - observable but class unknown / uncertain, or localisation mediocre.
* REJECT - no board registration, outside the board, or registration degraded
           beyond use.
"""
from __future__ import annotations

from dataclasses import dataclass

from .board_aruco import RegistrationState
from .config import ConfidenceConfig
from .events import BoardUV, ConfidenceBand, GeometryQuality, Lifecycle
from .tracker import Track


def _ramp(value: float, good: float, bad: float) -> float:
    """1.0 at/below ``good``, 0.0 at/above ``bad``, linear between."""
    if value <= good:
        return 1.0
    if value >= bad:
        return 0.0
    return 1.0 - (value - good) / (bad - good)


@dataclass(frozen=True)
class Scored:
    localization: float | None
    detection: float | None
    band: ConfidenceBand
    reason: str


def score(track: Track, lifecycle: Lifecycle, uv: BoardUV | None, registration: RegistrationState,
          geometry: GeometryQuality, cfg: ConfidenceConfig, *, board_mm: tuple[float, float]) -> Scored:
    # --- hard rejects
    if not registration.valid or registration.homography is None or uv is None:
        return Scored(None, None, ConfidenceBand.REJECT, "no board registration")
    if lifecycle in (Lifecycle.REMOVED, Lifecycle.LOST):
        # Removal carries the last known position; its band reflects only geometry.
        pass
    if not uv.inside_board:
        return Scored(0.0, None, ConfidenceBand.REJECT, "outside board")

    # --- localisation quality from measured parts
    rms = registration.rms_uv if registration.rms_uv is not None else cfg.bad_reprojection_rms_uv
    q_reproj = _ramp(rms, cfg.good_reprojection_rms_uv, cfg.bad_reprojection_rms_uv)
    jitter_mm = geometry.position_jitter_uv * max(board_mm)
    q_jitter = _ramp(jitter_mm, cfg.good_jitter_mm, cfg.bad_jitter_mm)
    edge_mm = min(uv.u, 1 - uv.u) * board_mm[0], min(uv.v, 1 - uv.v) * board_mm[1]
    q_edge = _ramp(-min(edge_mm), -15.0, -2.0)  # within 2 mm of the edge -> 0, >15 mm -> 1
    q_hold = 0.6 if registration.held else 1.0
    q_kind = 0.5 if registration.transform_kind == "affine" else 1.0
    localization = round(q_reproj * 0.45 + q_jitter * 0.35 + q_edge * 0.20, 3) * q_hold * q_kind
    localization = round(max(0.0, min(1.0, localization)), 3)

    cls = track.classification
    detection = cls.confidence if cls.valid and cls.piece_class is not None else None

    if lifecycle in (Lifecycle.REMOVED, Lifecycle.LOST):
        band = ConfidenceBand.HIGH if localization >= cfg.review_band_min_localization else ConfidenceBand.REVIEW
        return Scored(localization, detection, band, "removal: geometry only")

    if registration.degraded and not registration.held and registration.transform_kind == "none":
        return Scored(localization, detection, ConfidenceBand.REJECT, "registration unusable")

    if localization < cfg.review_band_min_localization:
        return Scored(localization, detection, ConfidenceBand.REVIEW,
                      f"localisation quality {localization:.2f} below {cfg.review_band_min_localization}")
    if not cls.valid or cls.piece_class is None:
        return Scored(localization, detection, ConfidenceBand.REVIEW, "class not verified")
    if detection is None:
        # Classifier reported a class but no confidence value: never pretend it is high.
        return Scored(localization, None, ConfidenceBand.REVIEW, "class without reported confidence")
    if detection < cfg.high_band_min_class_confidence:
        return Scored(localization, detection, ConfidenceBand.REVIEW,
                      f"class confidence {detection:.2f} below {cfg.high_band_min_class_confidence}")
    if localization < cfg.high_band_min_localization:
        return Scored(localization, detection, ConfidenceBand.REVIEW,
                      f"localisation quality {localization:.2f} below {cfg.high_band_min_localization}")
    return Scored(localization, detection, ConfidenceBand.HIGH, "stable, classified, localised")
