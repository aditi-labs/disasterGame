"""Typed observation contract shared by Lane B (tracking) and Lane C (classification).

Implements the ``PhysicalObservation`` schema design from spec section 5.  It is a
*proposal* for the shared contract; the backend adapter (shared integration lane)
maps it onto the real ``/perception/observe`` / ``/action`` payloads.  Nothing in
this module talks to the world.

Rules enforced here (spec 5, "Important integrity rules"):

* ``event_id`` is a stable idempotency key, deterministic per
  (session, track, lifecycle, emission counter).
* ``track_id`` values are camera track identities; they are **not** world token IDs.
* ``board_uv`` is ``None`` whenever the board is not registered; a missing
  registration can only yield the ``reject`` band.
* ``source`` says where the frame came from (live camera or an identified recording).
  A recording is never labelled as live.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any, Mapping


class PieceClass(str, Enum):
    """The four physical piece classes of the 75-second game (spec section 5)."""

    BRIDGE = "bridge"
    SHELTER = "shelter"
    HOSPITAL = "hospital"
    FOOD_STATION = "food_station"


class Lifecycle(str, Enum):
    CANDIDATE = "candidate"   # seen, not yet stable: pending outline only
    PLACED = "placed"         # stable at a position; emitted once per stable placement
    MOVED = "moved"           # same track, stable again at a new position
    REMOVED = "removed"       # track absent longer than the occlusion grace period
    LOST = "lost"             # track vanished before it was ever stable


#: Spec section 5 calls this type ``PhysicalLifecycle``; Lane C code imports it under that name.
PhysicalLifecycle = Lifecycle


class ConfidenceBand(str, Enum):
    HIGH = "high"
    REVIEW = "review"
    REJECT = "reject"


class ObservationSource(str, Enum):
    LIVE_CAMERA = "live_camera"
    RECORDING = "recording"   # authentic recorded camera input replayed for a test


@dataclass(frozen=True)
class BoardUV:
    u: float
    v: float

    def as_dict(self) -> dict[str, float]:
        return {"u": float(self.u), "v": float(self.v)}

    @property
    def inside_board(self) -> bool:
        return 0.0 <= self.u <= 1.0 and 0.0 <= self.v <= 1.0


@dataclass(frozen=True)
class GeometryQuality:
    """Measured geometric evidence behind one observation.

    These are local measurements, not model probabilities.  They are what
    ``localization_confidence`` is derived from, exposed so the operator HUD and
    Dev 2's fusion can see *why* a value is what it is.
    """

    markers_used: int                   # board markers that produced the homography
    reprojection_rms_uv: float | None   # RMS error of marker corners in UV
    reprojection_rms_px: float | None   # the same error expressed in camera pixels
    registration_age_ms: int            # time since the homography was last re-solved
    registration_held: bool             # True when a held (grace) homography was used
    position_jitter_uv: float           # std of the track centre over the stability window
    frames_observed: int                # frames in which the track was matched
    frames_stable: int                  # consecutive frames below the move gate
    area_mm2: float | None              # footprint area on the board plane
    bbox_mm: tuple[float, float] | None  # oriented bounding box (long, short) in mm
    elongation: float | None            # long / short side of the oriented box
    touches_board_edge: bool            # contour clipped by the board boundary
    parallax_correction_mm: float | None = None  # how far the footprint was moved from the plane hit
    assumed_height_mm: float | None = None       # piece height used for that correction
    camera_pose_approximate: bool | None = None  # True when the pose came from guessed intrinsics

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.bbox_mm is not None:
            d["bbox_mm"] = [float(self.bbox_mm[0]), float(self.bbox_mm[1])]
        return d


@dataclass(frozen=True)
class Appearance:
    """Colour statistics of the candidate region (board-plane crop), for Dev 2 fusion.

    Hue is OpenCV's 0..180 scale.  Reported, not interpreted: perception does not
    decide that "yellow means bridge".
    """

    mean_hsv: tuple[float, float, float]
    yellow_fraction: float      # fraction of pixels in a broad yellow hue band
    bright_low_sat_fraction: float  # fraction of bright, low-saturation (white-ish) pixels

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean_hsv": [float(x) for x in self.mean_hsv],
            "yellow_fraction": float(self.yellow_fraction),
            "bright_low_sat_fraction": float(self.bright_low_sat_fraction),
        }


@dataclass(frozen=True)
class PhysicalObservation:
    """One lifecycle event for one physical track (spec section 5)."""

    event_id: str
    session_id: str
    track_id: str
    piece_class: PieceClass | None
    lifecycle: Lifecycle
    board_uv: BoardUV | None
    detection_confidence: float | None
    localization_confidence: float | None
    confidence_band: ConfidenceBand
    observed_at_ms: int
    source: ObservationSource
    orientation_deg: float | None = None
    # --- extensions beyond the minimal schema (all measured, all optional) ---
    class_source: str | None = None             # e.g. "perceptron", "operator"; None when unclassified
    class_confidence: float | None = None       # Dev 2's reported value, passed through untouched
    frame_id: int | None = None
    camera_px: tuple[float, float] | None = None  # raw image-plane centre, for raw-vs-snapped debug
    previous_track_id: str | None = None        # set when a new track appears where one was just removed
    geometry: GeometryQuality | None = None
    appearance: Appearance | None = None
    frame_provenance: str | None = None         # "live:<device>" or "recording:<path>#<frame>"
    reason: str | None = None                   # why the band is review/reject, human readable

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "track_id": self.track_id,
            "piece_class": self.piece_class.value if self.piece_class else None,
            "lifecycle": self.lifecycle.value,
            "board_uv": self.board_uv.as_dict() if self.board_uv else None,
            "orientation_deg": None if self.orientation_deg is None else float(self.orientation_deg),
            "detection_confidence": _opt_float(self.detection_confidence),
            "localization_confidence": _opt_float(self.localization_confidence),
            "confidence_band": self.confidence_band.value,
            "observed_at_ms": int(self.observed_at_ms),
            "source": self.source.value,
            "class_source": self.class_source,
            "class_confidence": _opt_float(self.class_confidence),
            "frame_id": self.frame_id,
            "camera_px": None if self.camera_px is None else [float(self.camera_px[0]), float(self.camera_px[1])],
            "previous_track_id": self.previous_track_id,
            "geometry": self.geometry.as_dict() if self.geometry else None,
            "appearance": self.appearance.as_dict() if self.appearance else None,
            "frame_provenance": self.frame_provenance,
            "reason": self.reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "PhysicalObservation":
        uv = data.get("board_uv")
        geom = data.get("geometry")
        app = data.get("appearance")
        return PhysicalObservation(
            event_id=str(data["event_id"]),
            session_id=str(data["session_id"]),
            track_id=str(data["track_id"]),
            piece_class=PieceClass(data["piece_class"]) if data.get("piece_class") else None,
            lifecycle=Lifecycle(data["lifecycle"]),
            board_uv=BoardUV(float(uv["u"]), float(uv["v"])) if uv else None,
            detection_confidence=_opt_float(data.get("detection_confidence")),
            localization_confidence=_opt_float(data.get("localization_confidence")),
            confidence_band=ConfidenceBand(data["confidence_band"]),
            observed_at_ms=int(data["observed_at_ms"]),
            source=ObservationSource(data.get("source", "live_camera")),
            orientation_deg=_opt_float(data.get("orientation_deg")),
            class_source=data.get("class_source"),
            class_confidence=_opt_float(data.get("class_confidence")),
            frame_id=data.get("frame_id"),
            camera_px=tuple(data["camera_px"]) if data.get("camera_px") else None,
            previous_track_id=data.get("previous_track_id"),
            geometry=GeometryQuality(**{**geom, "bbox_mm": tuple(geom["bbox_mm"]) if geom.get("bbox_mm") else None})
            if geom else None,
            appearance=Appearance(mean_hsv=tuple(app["mean_hsv"]),
                                  yellow_fraction=app["yellow_fraction"],
                                  bright_low_sat_fraction=app["bright_low_sat_fraction"]) if app else None,
            frame_provenance=data.get("frame_provenance"),
            reason=data.get("reason"),
        )


@dataclass(frozen=True)
class ClassificationResult:
    """What Lane C hands back for a track (spec 7.4, normalised).

    ``valid=False`` means "no usable answer" (timeout, compile-only SDK response,
    empty result).  An invalid result never sets a class.
    """

    track_id: str
    piece_class: PieceClass | None
    class_source: str
    confidence: float | None
    valid: bool
    latency_ms: int | None = None
    evidence: str | None = None
    request_id: str | None = None


@dataclass
class ROIRequest:
    """A crop handed to the classifier for one unresolved/changed track (spec 6.7)."""

    request_id: str
    session_id: str
    track_id: str
    frame_id: int
    crop_bgr: Any                      # numpy array, board-plane crop (perspective corrected)
    crop_bbox_warp_px: tuple[int, int, int, int]
    board_uv: BoardUV | None
    orientation_deg: float | None
    observed_at_ms: int
    reason: str                        # "new_track" | "moved" | "appearance_changed" | "operator"
    frame_provenance: str | None = None


@dataclass
class CameraHealth:
    """Camera status for the operator status line (spec 6.1 and 9 operator UI)."""

    connected: bool
    source: str
    width: int | None
    height: int | None
    fps_measured: float
    last_frame_age_ms: int | None
    frames_total: int
    reconnects: int
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_ms() -> int:
    return int(time.time() * 1000)


def make_event_id(session_id: str, track_id: str, lifecycle: Lifecycle, emission_index: int) -> str:
    """Deterministic idempotency key: identical inputs always give the same ID."""
    raw = f"{session_id}|{track_id}|{lifecycle.value}|{emission_index}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"obs-{track_id}-{lifecycle.value}-{emission_index}-{digest}"


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


# =============================================================================
# Dev 2 additions (Perceptron classification support)
# =============================================================================

@dataclass
class BoundingBox:
    """Bounding box in pixel coordinates (for ROI extraction)."""
    x1: int  # Left
    y1: int  # Top
    x2: int  # Right
    y2: int  # Bottom

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def area(self) -> int:
        return self.width * self.height


# Mapping from raw Perceptron labels to PieceClass
PERCEPTRON_LABEL_MAP: dict[str, PieceClass] = {
    # Primary labels
    "bridge": PieceClass.BRIDGE,
    "hospital": PieceClass.HOSPITAL,
    "shelter": PieceClass.SHELTER,
    "food_station": PieceClass.FOOD_STATION,
    "food station": PieceClass.FOOD_STATION,
    "food": PieceClass.FOOD_STATION,

    # Alternative labels the model might return
    "crossing": PieceClass.BRIDGE,
    "overpass": PieceClass.BRIDGE,
    "medical": PieceClass.HOSPITAL,
    "clinic": PieceClass.HOSPITAL,
    "refuge": PieceClass.SHELTER,
    "housing": PieceClass.SHELTER,
    "supply": PieceClass.FOOD_STATION,
    "supplies": PieceClass.FOOD_STATION,
}


def map_label_to_class(raw_label: str | None) -> PieceClass | None:
    """Map a raw label from Perceptron to a PieceClass.

    Case-insensitive matching with fallback to None for unknown.
    """
    if not raw_label:
        return None

    normalized = raw_label.lower().strip()
    return PERCEPTRON_LABEL_MAP.get(normalized)
