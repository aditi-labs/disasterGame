"""FLOODSHIFT perception service (Lane B, Detection Dev 1).

Fresh OpenCV implementation of camera ingest, ArUco board registration,
camera-to-board geometry, physical piece candidate proposals, persistent
track IDs with a place/move/remove lifecycle, and typed observations.

Source of truth: FLOODSHIFT_MASTER_BUILD_SPEC (2).md, sections 3, 5 and 6.

This package owns ONLY what the camera actually observes. It never mutates
world state, never computes routes, and never fabricates a class, a pad or a
score. Classification of a region into a piece class belongs to Lane C
(Detection Dev 2) and arrives through :class:`perception.service.ClassifierPort`.
"""

__all__ = [
    "camera",
    "board_aruco",
    "geometry",
    "candidate_regions",
    "tracker",
    "events",
    "service",
]

__version__ = "0.1.0"
