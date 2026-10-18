"""FLOODSHIFT perception service.

Lane B (Detection Dev 1): Camera ingest, ArUco board registration,
camera-to-board geometry, physical piece candidate proposals, persistent
track IDs with a place/move/remove lifecycle, and typed observations.

Lane C (Detection Dev 2): Perceptron SDK integration, piece classification,
confidence fusion, and class recognition.

Source of truth: FLOODSHIFT_MASTER_BUILD_SPEC (2).md, sections 3, 5, 6 and 7.

This package owns ONLY what the camera actually observes. It never mutates
world state, never computes routes, and never fabricates a pad or a score.
"""

__all__ = [
    # Dev 1 - OpenCV/Tracking
    "camera",
    "board_aruco",
    "geometry",
    "candidate_regions",
    "tracker",
    "events",
    "service",
    # Dev 2 - Perceptron/Classification
    "perceptron_adapter",
    "classifier",
    "fusion",
]

__version__ = "0.1.0"
