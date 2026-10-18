"""
FloodShift Piece Classifier
============================
Classifies physical game pieces using Perceptron SDK.

ACTUAL PHYSICAL TOKENS (verified by viewing photos):
- YELLOW bridge piece - elongated with railings
- PINK cross on WHITE base - hospital
- WHITE base with BLUE circles - food station
- White shelter piece (if available)

Reference: FLOODSHIFT_MASTER_BUILD_SPEC Section 7 (Lane C)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable

import numpy as np

from .events import (
    PieceClass,
    ClassificationResult,
    BoundingBox,
    ConfidenceBand,
    map_label_to_class,
    PERCEPTRON_LABEL_MAP
)
from .perceptron_adapter import (
    PerceptronAdapter,
    PerceptronConfig,
    PerceptronResponse,
    PerceptronStatus,
    get_adapter
)

logger = logging.getLogger(__name__)


# Physical piece characteristics for validation
# ACTUAL TOKEN COLORS - verified by viewing the real photos
PIECE_CHARACTERISTICS = {
    PieceClass.BRIDGE: {
        "color_range_hsv": [(20, 100, 100), (40, 255, 255)],  # YELLOW range
        "min_aspect_ratio": 1.5,  # Bridge is elongated
        "max_aspect_ratio": 5.0,
        "description": "YELLOW elongated bridge piece with railings"
    },
    PieceClass.HOSPITAL: {
        "color_range_hsv": [(140, 50, 100), (170, 255, 255)],  # PINK/MAGENTA range
        "min_aspect_ratio": 0.7,
        "max_aspect_ratio": 1.5,
        "description": "PINK cross on WHITE base - hospital"
    },
    PieceClass.SHELTER: {
        "color_range_hsv": [(0, 0, 180), (180, 30, 255)],  # White range
        "min_aspect_ratio": 0.6,
        "max_aspect_ratio": 1.8,
        "description": "White shelter/house piece with roof"
    },
    PieceClass.FOOD_STATION: {
        "color_range_hsv": [(100, 100, 100), (130, 255, 255)],  # BLUE range (has blue circles)
        "min_aspect_ratio": 0.8,
        "max_aspect_ratio": 1.5,
        "description": "WHITE base with BLUE circles - food station"
    }
}


@dataclass
class ClassifierConfig:
    """Configuration for the classifier."""
    # Perceptron settings
    use_perceptron: bool = True
    perceptron_timeout_ms: int = 5000

    # Few-shot settings
    use_few_shot: bool = True
    reference_images_dir: Optional[str] = None

    # Confidence thresholds
    high_confidence_threshold: float = 0.8
    review_confidence_threshold: float = 0.5

    # Color validation (use OpenCV checks alongside Perceptron)
    validate_color: bool = True

    # Caching
    cache_classifications: bool = True
    cache_ttl_frames: int = 30  # Cache for 30 frames (~1 second at 30fps)


@dataclass
class ClassificationMetrics:
    """Metrics for classifier performance tracking."""
    total_classifications: int = 0
    successful_classifications: int = 0
    failed_classifications: int = 0
    cached_hits: int = 0
    perceptron_calls: int = 0
    fallback_classifications: int = 0
    average_latency_ms: float = 0.0
    latency_samples: list[float] = field(default_factory=list)

    # Per-class metrics
    class_counts: dict[str, int] = field(default_factory=dict)
    class_confidence_sum: dict[str, float] = field(default_factory=dict)

    def record_classification(
        self,
        piece_class: PieceClass | None,
        confidence: float | None,
        latency_ms: float,
        from_cache: bool = False,
        from_perceptron: bool = True
    ):
        """Record a classification for metrics."""
        self.total_classifications += 1
        self.successful_classifications += 1

        if from_cache:
            self.cached_hits += 1
        elif from_perceptron:
            self.perceptron_calls += 1
        else:
            self.fallback_classifications += 1

        # Update latency (only for non-cached)
        if not from_cache:
            self.latency_samples.append(latency_ms)
            if len(self.latency_samples) > 100:
                self.latency_samples = self.latency_samples[-100:]
            self.average_latency_ms = sum(self.latency_samples) / len(self.latency_samples)

        # Update class counts
        if piece_class:
            class_name = piece_class.value
            self.class_counts[class_name] = self.class_counts.get(class_name, 0) + 1
            if confidence is not None:
                self.class_confidence_sum[class_name] = self.class_confidence_sum.get(class_name, 0.0) + confidence

    def record_failure(self, latency_ms: float):
        """Record a failed classification."""
        self.total_classifications += 1
        self.failed_classifications += 1
        self.perceptron_calls += 1
        self.latency_samples.append(latency_ms)

    def to_dict(self) -> dict:
        """Convert to dictionary for telemetry."""
        return {
            "total_classifications": self.total_classifications,
            "successful_classifications": self.successful_classifications,
            "failed_classifications": self.failed_classifications,
            "cached_hits": self.cached_hits,
            "perceptron_calls": self.perceptron_calls,
            "fallback_classifications": self.fallback_classifications,
            "average_latency_ms": round(self.average_latency_ms, 2),
            "class_counts": self.class_counts,
            "success_rate": (
                self.successful_classifications / self.total_classifications
                if self.total_classifications > 0 else 0.0
            ),
        }


class PieceClassifier:
    """
    Classifier for physical game pieces.

    Uses Perceptron SDK for primary classification with fallback
    to color-based heuristics when API is unavailable.

    Thread-safe for use with async tracking pipeline.
    """

    # Target classes for detection
    TARGET_CLASSES = ["bridge", "hospital", "shelter", "food_station"]

    def __init__(
        self,
        config: Optional[ClassifierConfig] = None,
        adapter: Optional[PerceptronAdapter] = None
    ):
        self.config = config or ClassifierConfig()
        self._adapter = adapter or get_adapter()
        self._metrics = ClassificationMetrics()
        self._classification_cache: dict[str, tuple[ClassificationResult, int]] = {}
        self._frame_count = 0
        self._callbacks: list[Callable[[str, ClassificationResult], None]] = []

        # Load reference images if configured
        if self.config.reference_images_dir:
            self._adapter.load_reference_images(self.config.reference_images_dir)

        # Start the adapter worker
        if self.config.use_perceptron:
            self._adapter.start_worker()

    def shutdown(self):
        """Shutdown the classifier and cleanup resources."""
        self._adapter.stop_worker()

    def register_callback(self, callback: Callable[[str, ClassificationResult], None]):
        """Register a callback for classification results."""
        self._callbacks.append(callback)

    def increment_frame(self):
        """Called each frame to manage cache expiry."""
        self._frame_count += 1
        self._cleanup_cache()

    def _cleanup_cache(self):
        """Remove expired cache entries."""
        if not self.config.cache_classifications:
            return

        expired = []
        for track_id, (_, frame) in self._classification_cache.items():
            if self._frame_count - frame > self.config.cache_ttl_frames:
                expired.append(track_id)

        for track_id in expired:
            del self._classification_cache[track_id]

    def get_cached_classification(self, track_id: str) -> Optional[ClassificationResult]:
        """Get cached classification for a track if available and not expired."""
        if not self.config.cache_classifications:
            return None

        if track_id in self._classification_cache:
            result, frame = self._classification_cache[track_id]
            if self._frame_count - frame <= self.config.cache_ttl_frames:
                return result
        return None

    def classify_async(
        self,
        track_id: str,
        roi_image: np.ndarray,
        callback: Optional[Callable[[str, ClassificationResult], None]] = None
    ):
        """
        Queue an ROI for async classification.

        Non-blocking - result delivered via callback or poll get_results().
        """
        # Check cache first
        cached = self.get_cached_classification(track_id)
        if cached is not None:
            self._metrics.record_classification(
                cached.piece_class,
                cached.confidence,
                0.0,
                from_cache=True
            )
            if callback:
                callback(track_id, cached)
            return

        # Queue for Perceptron classification
        def on_result(req_id: str, response: PerceptronResponse):
            result = self._process_response(req_id, response)
            self._cache_result(req_id, result)

            # Notify callbacks
            if callback:
                callback(req_id, result)
            for cb in self._callbacks:
                cb(req_id, result)

        self._adapter.classify_async(
            track_id,
            roi_image,
            self.TARGET_CLASSES,
            callback=on_result
        )

    def classify_sync(
        self,
        track_id: str,
        roi_image: np.ndarray
    ) -> ClassificationResult:
        """
        Synchronous classification (blocking).

        Use this only when you need immediate results and can afford to wait.
        For real-time tracking, use classify_async instead.
        """
        start_time = time.time()

        # Check cache first
        cached = self.get_cached_classification(track_id)
        if cached is not None:
            self._metrics.record_classification(
                cached.piece_class,
                cached.confidence,
                0.0,
                from_cache=True
            )
            return cached

        # Try Perceptron classification
        if self.config.use_perceptron and self._adapter.is_available:
            if self.config.use_few_shot and self._adapter._reference_images:
                response = self._adapter.classify_with_references(roi_image)
            else:
                response = self._adapter._classify_sync(roi_image, self.TARGET_CLASSES)

            result = self._process_response(track_id, response)
            # Fall back to color if Perceptron failed
            if not result.valid and self.config.validate_color:
                result = self._classify_by_color(track_id, roi_image)
        else:
            # Perceptron unavailable - use color-based fallback
            result = self._classify_by_color(track_id, roi_image)

        self._cache_result(track_id, result)

        latency_ms = (time.time() - start_time) * 1000
        if result.valid:
            self._metrics.record_classification(
                result.piece_class,
                result.confidence,
                latency_ms,
                from_cache=False,
                from_perceptron=self._adapter.is_available
            )
        else:
            self._metrics.record_failure(latency_ms)

        return result

    def _process_response(
        self,
        track_id: str,
        response: PerceptronResponse
    ) -> ClassificationResult:
        """Process Perceptron response into ClassificationResult."""
        if not response.success or not response.detections:
            return ClassificationResult(
                track_id=track_id,
                piece_class=None,
                class_source="perceptron",
                confidence=None,
                valid=False,
                latency_ms=int(response.latency_ms),
                evidence=response.error_message or "No detections"
            )

        # Get the first/best detection
        labels = {map_label_to_class(d.get("class")) for d in response.detections}
        if None in labels or len(labels) != 1 or len(response.detections) != 1:
            return ClassificationResult(track_id, None, "perceptron", None, False,
                                        evidence="ambiguous or unknown piece classes")
        detection = response.detections[0]
        raw_class = detection.get("class", "unknown")
        piece_class = map_label_to_class(raw_class)

        # Parse confidence
        confidence_str = detection.get("confidence")
        confidence = self._parse_confidence(confidence_str)

        return ClassificationResult(
            track_id=track_id,
            piece_class=piece_class,
            class_source="perceptron",
            confidence=confidence,
            valid=piece_class is not None,
            latency_ms=int(response.latency_ms),
            evidence=detection.get("reasoning")
        )

    def _parse_confidence(self, confidence_value) -> float | None:
        """Parse confidence value from Perceptron response."""
        if isinstance(confidence_value, (int, float)) and not isinstance(confidence_value, bool):
            import math
            n = float(confidence_value)
            return n if math.isfinite(n) and 0 <= n <= 1 else None

        return None

    def _cache_result(self, track_id: str, result: ClassificationResult):
        """Cache a classification result."""
        if self.config.cache_classifications and result.valid:
            self._classification_cache[track_id] = (result, self._frame_count)

    def _classify_by_color(
        self,
        track_id: str,
        roi_image: np.ndarray
    ) -> ClassificationResult:
        """
        Fallback color-based classification.

        ACTUAL TOKEN COLORS (verified by viewing real photos):
        - YELLOW pieces (bridge) - yellow with railings
        - PINK pieces (hospital) - pink cross on white base
        - BLUE+WHITE pieces (food_station) - white base with blue circles

        This is less accurate than Perceptron but works offline.
        """
        try:
            import cv2

            # Convert to HSV
            hsv = cv2.cvtColor(roi_image, cv2.COLOR_BGR2HSV)

            # Check for YELLOW (bridge)
            yellow_mask = cv2.inRange(
                hsv,
                np.array([20, 100, 100]),
                np.array([40, 255, 255])
            )
            yellow_ratio = np.sum(yellow_mask > 0) / yellow_mask.size

            # Check for PINK/MAGENTA (hospital)
            pink_mask = cv2.inRange(
                hsv,
                np.array([140, 50, 100]),
                np.array([170, 255, 255])
            )
            pink_ratio = np.sum(pink_mask > 0) / pink_mask.size

            # Check for BLUE (food_station has blue circles)
            blue_mask = cv2.inRange(
                hsv,
                np.array([100, 100, 100]),
                np.array([130, 255, 255])
            )
            blue_ratio = np.sum(blue_mask > 0) / blue_mask.size

            # Check for WHITE (shelter or part of other tokens)
            white_mask = cv2.inRange(
                hsv,
                np.array([0, 0, 180]),
                np.array([180, 30, 255])
            )
            white_ratio = np.sum(white_mask > 0) / white_mask.size

            # Determine class based on dominant color
            color_scores = {
                "yellow": yellow_ratio,
                "pink": pink_ratio,
                "blue": blue_ratio,
                "white": white_ratio
            }
            dominant_color = max(color_scores, key=color_scores.get)
            dominant_ratio = color_scores[dominant_color]

            if dominant_ratio < 0.10:
                return ClassificationResult(
                    track_id=track_id,
                    piece_class=None,
                    class_source="color_fallback",
                    confidence=0.2,
                    valid=True,
                    evidence="Color-based: no dominant color detected"
                )

            if dominant_color == "yellow":
                return ClassificationResult(
                    track_id=track_id,
                    piece_class=PieceClass.BRIDGE,
                    class_source="color_fallback",
                    confidence=min(0.85, dominant_ratio + 0.4),
                    valid=True,
                    evidence="Color-based: YELLOW = bridge"
                )
            elif dominant_color == "pink":
                return ClassificationResult(
                    track_id=track_id,
                    piece_class=PieceClass.HOSPITAL,
                    class_source="color_fallback",
                    confidence=min(0.85, dominant_ratio + 0.4),
                    valid=True,
                    evidence="Color-based: PINK = hospital"
                )
            elif dominant_color == "blue":
                return ClassificationResult(
                    track_id=track_id,
                    piece_class=PieceClass.FOOD_STATION,
                    class_source="color_fallback",
                    confidence=min(0.85, dominant_ratio + 0.4),
                    valid=True,
                    evidence="Color-based: BLUE = food_station"
                )
            elif dominant_color == "white":
                if blue_ratio > 0.05:
                    return ClassificationResult(
                        track_id=track_id,
                        piece_class=PieceClass.FOOD_STATION,
                        class_source="color_fallback",
                        confidence=min(0.7, dominant_ratio + 0.3),
                        valid=True,
                        evidence="Color-based: WHITE+BLUE = food_station"
                    )
                return ClassificationResult(
                    track_id=track_id,
                    piece_class=PieceClass.SHELTER,
                    class_source="color_fallback",
                    confidence=min(0.7, dominant_ratio + 0.3),
                    valid=True,
                    evidence="Color-based: WHITE = shelter"
                )
            else:
                return ClassificationResult(
                    track_id=track_id,
                    piece_class=None,
                    class_source="color_fallback",
                    confidence=0.2,
                    valid=True,
                    evidence="Color-based: no clear match"
                )

        except Exception as e:
            logger.error(f"Color classification failed: {e}")
            return ClassificationResult(
                track_id=track_id,
                piece_class=None,
                class_source="color_fallback",
                confidence=None,
                valid=False,
                evidence=f"Color classification failed: {e}"
            )

    def get_confidence_band(self, confidence: Optional[float]) -> ConfidenceBand:
        """Determine confidence band from numeric confidence."""
        if confidence is None:
            return ConfidenceBand.REJECT

        if confidence >= self.config.high_confidence_threshold:
            return ConfidenceBand.HIGH
        elif confidence >= self.config.review_confidence_threshold:
            return ConfidenceBand.REVIEW
        else:
            return ConfidenceBand.REJECT

    def get_metrics(self) -> ClassificationMetrics:
        """Get current classification metrics."""
        return self._metrics

    def get_telemetry(self) -> dict:
        """Get full telemetry for operator display."""
        return {
            "classifier": {
                "config": {
                    "use_perceptron": self.config.use_perceptron,
                    "use_few_shot": self.config.use_few_shot,
                    "high_confidence_threshold": self.config.high_confidence_threshold,
                    "review_confidence_threshold": self.config.review_confidence_threshold,
                },
                "metrics": self._metrics.to_dict(),
                "cache_size": len(self._classification_cache),
                "frame_count": self._frame_count,
            },
            "perceptron": self._adapter.get_telemetry()
        }


# Singleton instance
_classifier_instance: Optional[PieceClassifier] = None


def get_classifier() -> PieceClassifier:
    """Get or create the shared classifier instance."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = PieceClassifier()
    return _classifier_instance


def init_classifier(config: ClassifierConfig) -> PieceClassifier:
    """Initialize the shared classifier with custom config."""
    global _classifier_instance
    _classifier_instance = PieceClassifier(config)
    return _classifier_instance


# =============================================================================
# ClassifierPort adapter for perception service integration
# =============================================================================

class PerceptronClassifierPort:
    """
    Adapter that implements ClassifierPort protocol for the perception service.

    Wraps PieceClassifier to provide the submit/poll interface expected by
    perception.service.PerceptionService.
    """

    def __init__(self):
        from dotenv import load_dotenv
        load_dotenv()

        self._classifier = get_classifier()
        self._pending_results: list[ClassificationResult] = []
        self._submitted = 0
        self._classified = 0

    def submit(self, request) -> None:
        """Submit an ROI for classification. Non-blocking."""
        self._submitted += 1

        # Extract image from request
        crop_bgr = request.crop_bgr
        track_id = request.track_id

        # Run classification (sync for now, could be made async)
        result = self._classifier.classify_sync(track_id, crop_bgr)

        if result.valid:
            self._classified += 1
            self._pending_results.append(result)

    def poll(self) -> list:
        """Return pending classification results."""
        results = self._pending_results
        self._pending_results = []
        return results

    def status(self) -> dict:
        """Return classifier status for operator display."""
        return {
            "kind": "perceptron",
            "available": self._classifier._adapter.is_available,
            "submitted": self._submitted,
            "classified": self._classified,
            "perceptron_status": self._classifier._adapter.status.value,
        }

    def close(self) -> None:
        """Cleanup resources."""
        self._classifier.shutdown()


def create_classifier():
    """Factory function for perception service integration.

    Usage:
        python -m perception.service --classifier perception.classifier:create_classifier
    """
    return PerceptronClassifierPort()
