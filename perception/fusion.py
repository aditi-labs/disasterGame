"""
FloodShift Classification Fusion
=================================
Fuses OpenCV tracking (Dev 1) with Perceptron classification (Dev 2)
to produce stable, high-confidence physical observations.

The fusion module:
1. Receives tracking updates from Dev 1 (track_id, bbox, board_uv, lifecycle)
2. Triggers classification when needed (new track, appearance change)
3. Combines geometric + semantic evidence for confidence bands
4. Emits stable PhysicalObservation events for the backend adapter

Reference: FLOODSHIFT_MASTER_BUILD_SPEC Section 7 (Lane C)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable
from collections import defaultdict
from queue import Queue, Empty
import threading

import numpy as np

from .events import (
    PieceClass,
    PhysicalLifecycle,
    ConfidenceBand,
    BoardUV,
    BoundingBox,
    PhysicalObservation,
    TrackingUpdate,
    ClassificationResult,
)
from .classifier import PieceClassifier, ClassifierConfig, get_classifier

logger = logging.getLogger(__name__)


@dataclass
class FusionConfig:
    """Configuration for the fusion module."""
    # Stability requirements
    min_stable_frames: int = 5  # Frames before emitting PLACED
    min_classification_agreement: int = 3  # Consistent class results needed

    # Confidence thresholds for bands
    high_detection_threshold: float = 0.8
    high_localization_threshold: float = 0.9
    review_detection_threshold: float = 0.5
    review_localization_threshold: float = 0.7

    # Reclassification triggers
    reclassify_on_move: bool = True
    reclassify_interval_frames: int = 60  # Re-check every ~2 seconds
    appearance_change_threshold: float = 0.3  # Trigger if ROI changes significantly

    # Position stability
    position_jitter_threshold: float = 0.02  # Board UV units
    velocity_threshold: float = 0.1  # Board UV/second

    # Timeouts
    lost_timeout_frames: int = 30  # Mark as LOST after this many frames
    removed_confirm_frames: int = 15  # Confirm REMOVED after this many


@dataclass
class TrackedPiece:
    """Internal state for a tracked physical piece."""
    track_id: str
    first_seen_frame: int
    last_seen_frame: int

    # Position history for stability
    position_history: list[BoardUV] = field(default_factory=list)
    current_position: Optional[BoardUV] = None
    is_stable: bool = False

    # Classification state
    current_class: Optional[PieceClass] = None
    classification_history: list[PieceClass] = field(default_factory=list)
    classification_confidence: float = 0.0
    last_classification_frame: int = 0
    pending_classification: bool = False

    # Lifecycle
    lifecycle: PhysicalLifecycle = PhysicalLifecycle.CANDIDATE
    lifecycle_frame: int = 0

    # Localization confidence (from Dev 1)
    localization_confidence: float = 0.0

    # Emitted events
    last_emitted_lifecycle: Optional[PhysicalLifecycle] = None
    emitted_event_ids: set = field(default_factory=set)

    def get_position_stability(self, threshold: float) -> float:
        """Calculate position stability (0-1) based on recent history."""
        if len(self.position_history) < 3:
            return 0.0

        recent = self.position_history[-5:]
        if len(recent) < 2:
            return 0.0

        # Calculate variance
        us = [p.u for p in recent]
        vs = [p.v for p in recent]
        u_var = np.var(us)
        v_var = np.var(vs)

        max_var = threshold ** 2
        stability = 1.0 - min(1.0, (u_var + v_var) / (2 * max_var))
        return stability

    def get_classification_consistency(self) -> float:
        """Calculate classification consistency (0-1)."""
        if len(self.classification_history) < 2:
            return 0.0

        recent = self.classification_history[-5:]
        if not recent:
            return 0.0

        # Count most common class
        from collections import Counter
        counts = Counter(recent)
        most_common_count = counts.most_common(1)[0][1]
        return most_common_count / len(recent)


class ObservationFusion:
    """
    Fuses tracking and classification into stable observations.

    Thread-safe for use in async pipeline.
    """

    def __init__(
        self,
        config: Optional[FusionConfig] = None,
        classifier: Optional[PieceClassifier] = None,
        session_id: str = ""
    ):
        self.config = config or FusionConfig()
        self._classifier = classifier or get_classifier()
        self.session_id = session_id

        # Track state
        self._tracks: dict[str, TrackedPiece] = {}
        self._frame_count = 0

        # Output queue for observations
        self._observation_queue: Queue[PhysicalObservation] = Queue()

        # Callbacks for observation events
        self._callbacks: list[Callable[[PhysicalObservation], None]] = []

        # Lock for thread safety
        self._lock = threading.Lock()

        # Register with classifier for async results
        self._classifier.register_callback(self._on_classification_result)

    def reset(self, new_session_id: str = ""):
        """Reset all tracking state for new session."""
        with self._lock:
            self._tracks.clear()
            self._frame_count = 0
            self.session_id = new_session_id

            # Clear queues
            while not self._observation_queue.empty():
                try:
                    self._observation_queue.get_nowait()
                except Empty:
                    break

        logger.info(f"Fusion reset for session: {new_session_id}")

    def register_callback(self, callback: Callable[[PhysicalObservation], None]):
        """Register a callback for observation events."""
        self._callbacks.append(callback)

    def process_frame(self, frame: np.ndarray, tracking_updates: list[TrackingUpdate]):
        """
        Process a new frame with tracking updates from Dev 1.

        Args:
            frame: Full camera frame (for ROI extraction)
            tracking_updates: List of tracking updates from Dev 1
        """
        with self._lock:
            self._frame_count += 1
            self._classifier.increment_frame()

            # Track IDs seen this frame
            seen_tracks = set()

            for update in tracking_updates:
                seen_tracks.add(update.track_id)
                self._process_tracking_update(frame, update)

            # Handle tracks not seen this frame
            for track_id, piece in list(self._tracks.items()):
                if track_id not in seen_tracks:
                    self._handle_missing_track(piece)

    def _process_tracking_update(self, frame: np.ndarray, update: TrackingUpdate):
        """Process a single tracking update."""
        track_id = update.track_id

        # Get or create tracked piece
        if track_id not in self._tracks:
            piece = TrackedPiece(
                track_id=track_id,
                first_seen_frame=self._frame_count,
                last_seen_frame=self._frame_count
            )
            self._tracks[track_id] = piece
            logger.debug(f"New track: {track_id}")
        else:
            piece = self._tracks[track_id]

        # Update tracking info
        piece.last_seen_frame = self._frame_count
        piece.localization_confidence = update.localization_confidence

        # Update position
        if update.board_uv:
            piece.position_history.append(update.board_uv)
            if len(piece.position_history) > 30:
                piece.position_history = piece.position_history[-30:]
            piece.current_position = update.board_uv

        # Check position stability
        piece.is_stable = (
            piece.get_position_stability(self.config.position_jitter_threshold) > 0.8
            and piece.last_seen_frame - piece.first_seen_frame >= self.config.min_stable_frames
        )

        # Determine if classification needed
        needs_classification = self._needs_classification(piece, update)

        if needs_classification and not piece.pending_classification:
            # Extract ROI and queue for classification
            roi = self._extract_roi(frame, update.bbox)
            if roi is not None:
                piece.pending_classification = True
                self._classifier.classify_async(
                    track_id,
                    roi,
                    update.bbox
                )

        # Update lifecycle based on tracking state
        self._update_lifecycle(piece, update)

        # Emit observation if state changed significantly
        self._maybe_emit_observation(piece)

    def _needs_classification(self, piece: TrackedPiece, update: TrackingUpdate) -> bool:
        """Determine if this track needs (re)classification."""
        # Always classify new tracks
        if piece.current_class is None:
            return True

        # Explicit request from tracker
        if update.needs_reclassification:
            return True

        # Periodic reclassification
        frames_since_last = self._frame_count - piece.last_classification_frame
        if frames_since_last >= self.config.reclassify_interval_frames:
            return True

        # On movement (if configured)
        if self.config.reclassify_on_move and piece.lifecycle == PhysicalLifecycle.MOVED:
            return True

        return False

    def _extract_roi(self, frame: np.ndarray, bbox: BoundingBox) -> Optional[np.ndarray]:
        """Extract ROI from frame for classification."""
        try:
            h, w = frame.shape[:2]

            # Clamp to frame bounds with padding
            pad = 5
            x1 = max(0, bbox.x1 - pad)
            y1 = max(0, bbox.y1 - pad)
            x2 = min(w, bbox.x2 + pad)
            y2 = min(h, bbox.y2 + pad)

            if x2 <= x1 or y2 <= y1:
                return None

            return frame[y1:y2, x1:x2].copy()
        except Exception as e:
            logger.error(f"ROI extraction failed: {e}")
            return None

    def _on_classification_result(self, track_id: str, result: ClassificationResult):
        """Callback when classification completes."""
        with self._lock:
            if track_id not in self._tracks:
                return

            piece = self._tracks[track_id]
            piece.pending_classification = False
            piece.last_classification_frame = self._frame_count

            if result.valid and result.class_label:
                # Update classification history
                piece.classification_history.append(result.class_label)
                if len(piece.classification_history) > 10:
                    piece.classification_history = piece.classification_history[-10:]

                # Update current class if consistent
                consistency = piece.get_classification_consistency()
                if consistency >= 0.6:  # 60% agreement
                    piece.current_class = result.class_label
                    piece.classification_confidence = result.confidence or 0.5

                logger.debug(
                    f"Classification for {track_id}: {result.class_label.value} "
                    f"(conf={result.confidence}, consistency={consistency:.2f})"
                )

            # Possibly emit updated observation
            self._maybe_emit_observation(piece)

    def _update_lifecycle(self, piece: TrackedPiece, update: TrackingUpdate):
        """Update piece lifecycle based on tracking state."""
        old_lifecycle = piece.lifecycle

        if update.lifecycle == PhysicalLifecycle.REMOVED:
            piece.lifecycle = PhysicalLifecycle.REMOVED
        elif update.lifecycle == PhysicalLifecycle.MOVED:
            if piece.lifecycle == PhysicalLifecycle.PLACED:
                piece.lifecycle = PhysicalLifecycle.MOVED
        elif piece.lifecycle == PhysicalLifecycle.CANDIDATE:
            # Transition to PLACED if stable enough
            if piece.is_stable and piece.current_class is not None:
                if piece.get_classification_consistency() >= 0.6:
                    piece.lifecycle = PhysicalLifecycle.PLACED

        if piece.lifecycle != old_lifecycle:
            piece.lifecycle_frame = self._frame_count
            logger.info(f"Track {piece.track_id} lifecycle: {old_lifecycle.value} -> {piece.lifecycle.value}")

    def _handle_missing_track(self, piece: TrackedPiece):
        """Handle a track that wasn't seen this frame."""
        frames_missing = self._frame_count - piece.last_seen_frame

        if piece.lifecycle == PhysicalLifecycle.REMOVED:
            # Already removed, just clean up after delay
            if frames_missing >= self.config.removed_confirm_frames:
                self._emit_removed_observation(piece)
                del self._tracks[piece.track_id]
                return

        if frames_missing >= self.config.lost_timeout_frames:
            # Mark as lost
            if piece.lifecycle != PhysicalLifecycle.LOST:
                piece.lifecycle = PhysicalLifecycle.LOST
                piece.lifecycle_frame = self._frame_count
                self._maybe_emit_observation(piece)

    def _maybe_emit_observation(self, piece: TrackedPiece):
        """Emit observation if significant state change."""
        # Don't emit for candidates without classification
        if piece.lifecycle == PhysicalLifecycle.CANDIDATE and piece.current_class is None:
            return

        # Check if we should emit
        should_emit = (
            piece.last_emitted_lifecycle != piece.lifecycle
            or piece.lifecycle == PhysicalLifecycle.MOVED
        )

        if not should_emit:
            return

        observation = self._create_observation(piece)
        piece.last_emitted_lifecycle = piece.lifecycle
        piece.emitted_event_ids.add(observation.event_id)

        # Queue and notify
        self._observation_queue.put(observation)
        for callback in self._callbacks:
            try:
                callback(observation)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def _emit_removed_observation(self, piece: TrackedPiece):
        """Emit final REMOVED observation."""
        observation = self._create_observation(piece)
        observation.lifecycle = PhysicalLifecycle.REMOVED

        self._observation_queue.put(observation)
        for callback in self._callbacks:
            try:
                callback(observation)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def _create_observation(self, piece: TrackedPiece) -> PhysicalObservation:
        """Create a PhysicalObservation from tracked piece state."""
        # Calculate confidence band
        confidence_band = self._calculate_confidence_band(piece)

        return PhysicalObservation(
            session_id=self.session_id,
            track_id=piece.track_id,
            piece_class=piece.current_class,
            lifecycle=piece.lifecycle,
            board_uv=piece.current_position,
            detection_confidence=piece.classification_confidence,
            localization_confidence=piece.localization_confidence,
            confidence_band=confidence_band,
            source="live_camera"
        )

    def _calculate_confidence_band(self, piece: TrackedPiece) -> ConfidenceBand:
        """Calculate confidence band from combined evidence."""
        detection_conf = piece.classification_confidence
        localization_conf = piece.localization_confidence
        classification_consistency = piece.get_classification_consistency()
        position_stability = piece.get_position_stability(self.config.position_jitter_threshold)

        # HIGH: All metrics above thresholds
        if (detection_conf >= self.config.high_detection_threshold
            and localization_conf >= self.config.high_localization_threshold
            and classification_consistency >= 0.8
            and position_stability >= 0.8):
            return ConfidenceBand.HIGH

        # REVIEW: At least some confidence
        if (detection_conf >= self.config.review_detection_threshold
            and localization_conf >= self.config.review_localization_threshold
            and classification_consistency >= 0.5):
            return ConfidenceBand.REVIEW

        # REJECT: Low confidence
        return ConfidenceBand.REJECT

    def get_observation(self, timeout_ms: float = 100) -> Optional[PhysicalObservation]:
        """Get next observation from queue (non-blocking)."""
        try:
            return self._observation_queue.get(timeout=timeout_ms / 1000)
        except Empty:
            return None

    def get_all_tracks(self) -> dict[str, dict]:
        """Get current state of all tracked pieces."""
        with self._lock:
            return {
                track_id: {
                    "track_id": piece.track_id,
                    "lifecycle": piece.lifecycle.value,
                    "class": piece.current_class.value if piece.current_class else None,
                    "position": {
                        "u": piece.current_position.u,
                        "v": piece.current_position.v
                    } if piece.current_position else None,
                    "is_stable": piece.is_stable,
                    "classification_confidence": piece.classification_confidence,
                    "localization_confidence": piece.localization_confidence,
                    "frames_seen": piece.last_seen_frame - piece.first_seen_frame,
                    "pending_classification": piece.pending_classification,
                }
                for track_id, piece in self._tracks.items()
            }

    def get_telemetry(self) -> dict:
        """Get telemetry for operator display."""
        with self._lock:
            tracks_by_lifecycle = defaultdict(int)
            tracks_by_class = defaultdict(int)

            for piece in self._tracks.values():
                tracks_by_lifecycle[piece.lifecycle.value] += 1
                if piece.current_class:
                    tracks_by_class[piece.current_class.value] += 1

            return {
                "fusion": {
                    "frame_count": self._frame_count,
                    "session_id": self.session_id,
                    "active_tracks": len(self._tracks),
                    "pending_observations": self._observation_queue.qsize(),
                    "tracks_by_lifecycle": dict(tracks_by_lifecycle),
                    "tracks_by_class": dict(tracks_by_class),
                },
                "classifier": self._classifier.get_telemetry()
            }


# Singleton instance
_fusion_instance: Optional[ObservationFusion] = None


def get_fusion() -> ObservationFusion:
    """Get or create the shared fusion instance."""
    global _fusion_instance
    if _fusion_instance is None:
        _fusion_instance = ObservationFusion()
    return _fusion_instance


def init_fusion(
    config: FusionConfig,
    classifier: Optional[PieceClassifier] = None,
    session_id: str = ""
) -> ObservationFusion:
    """Initialize the shared fusion instance."""
    global _fusion_instance
    _fusion_instance = ObservationFusion(config, classifier, session_id)
    return _fusion_instance
