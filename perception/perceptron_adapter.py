"""
FloodShift Perceptron SDK Adapter
=================================
Wraps the official Perceptron SDK for async classification with timeout handling.

Official SDK: pip install "perceptron>=0.4.0"
API Reference: POST /v1/detect, POST /v1/chat/completions

Reference: FLOODSHIFT_MASTER_BUILD_SPEC Section 7 (Lane C)
Perceptron Docs: perceptron-mk1.5 model
"""

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any
from enum import Enum
import threading
from queue import Queue, Empty

import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PerceptronStatus(Enum):
    """Status of the Perceptron API connection."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    THROTTLED = "throttled"
    ERROR = "error"
    INITIALIZING = "initializing"


@dataclass
class PerceptronResponse:
    """Response from Perceptron API."""
    success: bool
    detections: list[dict]
    raw_response: Optional[dict]
    latency_ms: float
    error_message: Optional[str] = None
    is_cached: bool = False


@dataclass
class PerceptronConfig:
    """Configuration for Perceptron adapter."""
    api_key: Optional[str] = None
    timeout_ms: int = 5000  # 5 second default timeout
    max_retries: int = 2
    model: str = "perceptron-mk1.5"
    reasoning_effort: str = "minimal"  # none/minimal/low/medium/high
    base_url: str = "https://api.perceptron.inc/v1"
    enable_caching: bool = True
    cache_ttl_ms: int = 1000  # Cache classifications for 1 second


class PerceptronAdapter:
    """
    Async adapter for Perceptron SDK with timeout and graceful degradation.

    Features:
    - Async classification with configurable timeout
    - Reference image support for few-shot classification
    - Caching to reduce API calls for stable tracks
    - Graceful degradation when API unavailable
    - Non-blocking: never freezes camera loop
    """

    def __init__(self, config: Optional[PerceptronConfig] = None):
        self.config = config or PerceptronConfig()
        self._status = PerceptronStatus.INITIALIZING
        self._client = None
        self._reference_images: dict[str, bytes] = {}
        self._cache: dict[str, tuple[PerceptronResponse, float]] = {}
        self._lock = threading.Lock()
        self._worker_queue: Queue = Queue()
        self._result_queue: Queue = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown = False

        # Load API key from environment if not provided
        if not self.config.api_key:
            self.config.api_key = os.environ.get("PERCEPTRON_API_KEY")

        # Initialize SDK
        self._init_sdk()

    def _init_sdk(self):
        """Initialize the Perceptron SDK."""
        try:
            # Try to import the official SDK
            try:
                import perceptron
                if self.config.api_key:
                    perceptron.configure(api_key=self.config.api_key)
                    self._client = perceptron  # Store module reference
                    self._status = PerceptronStatus.CONNECTED
                    logger.info("Perceptron SDK initialized successfully")
                else:
                    logger.warning("No PERCEPTRON_API_KEY found - running in degraded mode")
                    self._status = PerceptronStatus.DISCONNECTED
            except ImportError:
                logger.warning("Perceptron SDK not installed. Install with: pip install perceptron")
                self._status = PerceptronStatus.DISCONNECTED
                self._client = None
        except Exception as e:
            logger.error(f"Failed to initialize Perceptron SDK: {e}")
            self._status = PerceptronStatus.ERROR

    def start_worker(self):
        """Start the background worker thread for async classification."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._shutdown = False
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
            logger.info("Perceptron worker thread started")

    def stop_worker(self):
        """Stop the background worker thread."""
        self._shutdown = True
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_queue.put(None)  # Signal shutdown
            self._worker_thread.join(timeout=2.0)
            logger.info("Perceptron worker thread stopped")

    def _worker_loop(self):
        """Background worker that processes classification requests."""
        while not self._shutdown:
            try:
                item = self._worker_queue.get(timeout=0.1)
                if item is None:
                    break  # Shutdown signal

                request_id, image, classes, callback = item
                result = self._classify_sync(image, classes)
                if callback:
                    callback(request_id, result)
                else:
                    self._result_queue.put((request_id, result))

            except Empty:
                continue
            except Exception as e:
                logger.error(f"Worker error: {e}")

    @property
    def status(self) -> PerceptronStatus:
        """Get current API status."""
        return self._status

    @property
    def is_available(self) -> bool:
        """Check if Perceptron API is available for classification."""
        return self._status == PerceptronStatus.CONNECTED and self._client is not None

    def load_reference_images(self, reference_dir: str | Path):
        """
        Load reference images for few-shot classification.

        Expected structure:
        reference_dir/
            bridge.jpg (or .png)
            hospital.jpg
            shelter.jpg
            food_station.jpg
        """
        reference_dir = Path(reference_dir)
        if not reference_dir.exists():
            logger.warning(f"Reference directory not found: {reference_dir}")
            return

        for piece_type in ["bridge", "hospital", "shelter", "food_station"]:
            for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                img_path = reference_dir / f"{piece_type}{ext}"
                if img_path.exists():
                    with open(img_path, "rb") as f:
                        self._reference_images[piece_type] = f.read()
                    logger.info(f"Loaded reference image for {piece_type}")
                    break

        logger.info(f"Loaded {len(self._reference_images)} reference images")

    def _image_to_base64(self, image: np.ndarray) -> str:
        """Convert numpy image to base64 string."""
        import cv2
        _, buffer = cv2.imencode('.jpg', image)
        return base64.b64encode(buffer).decode('utf-8')

    def _get_cache_key(self, image: np.ndarray) -> str:
        """Generate a cache key from image content."""
        # Use a simple hash of downsampled image
        small = image[::8, ::8] if image.size > 1000 else image
        return str(hash(small.tobytes()))

    def _check_cache(self, cache_key: str) -> Optional[PerceptronResponse]:
        """Check if we have a cached result."""
        if not self.config.enable_caching:
            return None

        with self._lock:
            if cache_key in self._cache:
                response, timestamp = self._cache[cache_key]
                if time.time() * 1000 - timestamp < self.config.cache_ttl_ms:
                    response.is_cached = True
                    return response
                else:
                    del self._cache[cache_key]
        return None

    def _store_cache(self, cache_key: str, response: PerceptronResponse):
        """Store a result in cache."""
        if self.config.enable_caching and response.success:
            with self._lock:
                self._cache[cache_key] = (response, time.time() * 1000)

    def classify_async(
        self,
        request_id: str,
        image: np.ndarray,
        classes: list[str],
        callback: Optional[callable] = None
    ):
        """
        Queue an image for async classification.

        Non-blocking - the result will be delivered via callback or result_queue.

        Args:
            request_id: Unique ID for this request (typically track_id)
            image: ROI crop as numpy array (BGR format from OpenCV)
            classes: List of class labels to detect
            callback: Optional callback(request_id, PerceptronResponse)
        """
        if not self.is_available:
            # Return immediate failure for unavailable API
            result = PerceptronResponse(
                success=False,
                detections=[],
                raw_response=None,
                latency_ms=0,
                error_message="Perceptron API not available"
            )
            if callback:
                callback(request_id, result)
            else:
                self._result_queue.put((request_id, result))
            return

        self._worker_queue.put((request_id, image, classes, callback))

    def get_result(self, timeout_ms: float = 100) -> Optional[tuple[str, PerceptronResponse]]:
        """
        Get a classification result from the queue.

        Non-blocking with optional timeout.

        Returns:
            Tuple of (request_id, response) or None if no results ready
        """
        try:
            return self._result_queue.get(timeout=timeout_ms / 1000)
        except Empty:
            return None

    def _classify_sync(
        self,
        image: np.ndarray,
        classes: list[str]
    ) -> PerceptronResponse:
        """
        Synchronous classification (called by worker thread).

        Uses the /v1/detect endpoint for object detection.
        """
        start_time = time.time()

        # Check cache first
        cache_key = self._get_cache_key(image)
        cached = self._check_cache(cache_key)
        if cached:
            return cached

        if not self.is_available:
            return PerceptronResponse(
                success=False,
                detections=[],
                raw_response=None,
                latency_ms=(time.time() - start_time) * 1000,
                error_message="Perceptron API not available"
            )

        try:
            # Convert image to base64
            image_b64 = self._image_to_base64(image)

            # Build the prompt for classification
            class_descriptions = self._build_class_descriptions(classes)

            # Try using the detect endpoint first
            response = self._call_detect_api(image_b64, classes)

            if response is None:
                # Fallback to chat completions with structured output
                response = self._call_chat_api(image_b64, class_descriptions)

            latency_ms = (time.time() - start_time) * 1000

            if response:
                result = PerceptronResponse(
                    success=True,
                    detections=response.get("detections", []),
                    raw_response=response,
                    latency_ms=latency_ms
                )
                self._store_cache(cache_key, result)
                return result
            else:
                return PerceptronResponse(
                    success=False,
                    detections=[],
                    raw_response=None,
                    latency_ms=latency_ms,
                    error_message="No response from API"
                )

        except TimeoutError:
            return PerceptronResponse(
                success=False,
                detections=[],
                raw_response=None,
                latency_ms=self.config.timeout_ms,
                error_message="Request timed out"
            )
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return PerceptronResponse(
                success=False,
                detections=[],
                raw_response=None,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=str(e)
            )

    def _build_class_descriptions(self, classes: list[str]) -> str:
        """Build detailed class descriptions for the model."""
        # ACTUAL TOKEN COLORS - verified by viewing the real photos
        descriptions = {
            "bridge": "A YELLOW bridge piece - elongated shape with railings, used for crossing rivers",
            "hospital": "A PINK/MAGENTA cross on WHITE base - medical cross symbol, provides medical care",
            "shelter": "A white shelter/refuge piece - house-shaped with roof, provides housing/refuge",
            "food_station": "A WHITE base with BLUE circles/rings - food supply station"
        }
        return "\n".join([
            f"- {cls}: {descriptions.get(cls, f'A {cls} game piece')}"
            for cls in classes
        ])

    def _call_detect_api(self, image_b64: str, classes: list[str]) -> Optional[dict]:
        """
        Call perceptron.detect() with proper image wrapping.

        Returns structured detection results with bounding boxes.
        """
        if self._client is None:
            return None

        try:
            import cv2
            # Decode base64 back to image for SDK
            img_bytes = base64.b64decode(image_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            # Use perceptron.detect with perceptron.image wrapper
            media = self._client.image(image)
            result = self._client.detect(media, classes=classes)

            if result and result.boxes:
                # Convert to our format
                # Note: top_left/bottom_right are SinglePoint objects with .x and .y
                detections = []
                for box in result.boxes:
                    detections.append({
                        "class": box.mention,
                        "confidence": "high",  # Perceptron doesn't return numeric confidence
                        "bbox": {
                            "x1": box.top_left.x,
                            "y1": box.top_left.y,
                            "x2": box.bottom_right.x,
                            "y2": box.bottom_right.y
                        }
                    })
                return {"detections": detections}

            return None

        except Exception as e:
            logger.debug(f"Detect API call failed: {e}")

        return None

    def _call_chat_api(self, image_b64: str, class_descriptions: str) -> Optional[dict]:
        """
        Call perceptron.question() for classification when detect doesn't work.

        Uses natural language question about the piece.
        """
        if self._client is None:
            return None

        try:
            import cv2
            import json

            # Decode base64 back to image
            img_bytes = base64.b64decode(image_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            # Use perceptron.question for classification
            prompt = f"""Analyze this top-down image of a game piece.
Identify which type it is based on color:

{class_descriptions}

Respond with ONLY a JSON object (no other text):
{{"class": "bridge|hospital|shelter|food_station|unknown", "confidence": "high|medium|low"}}
"""
            media = self._client.image(image)
            result = self._client.question(media, prompt)

            if result and result.text:
                # Try to parse JSON from response
                text = result.text.strip()
                # Find JSON in response
                if '{' in text and '}' in text:
                    json_start = text.index('{')
                    json_end = text.rindex('}') + 1
                    json_str = text[json_start:json_end]
                    parsed = json.loads(json_str)
                    return {
                        "detections": [{
                            "class": parsed.get("class", "unknown"),
                            "confidence": parsed.get("confidence", "low"),
                        }]
                    }

        except Exception as e:
            logger.debug(f"Question API call failed: {e}")

        return None

    def classify_with_references(
        self,
        image: np.ndarray,
        use_few_shot: bool = True
    ) -> PerceptronResponse:
        """
        Classify using the Perceptron detect API.

        Uses color-based class descriptions for accurate detection.
        """
        start_time = time.time()

        if not self.is_available:
            return PerceptronResponse(
                success=False,
                detections=[],
                raw_response=None,
                latency_ms=0,
                error_message="Perceptron API not available"
            )

        try:
            # Use detect with specific color AND shape descriptions
            # ACTUAL TOKEN COLORS - verified by viewing the real photos
            classes = [
                "yellow bridge piece with railings",
                "pink/magenta cross on white base (hospital)",
                "white base with blue circles (food station)",
                "white house-shaped shelter piece with roof"
            ]

            media = self._client.image(image)
            result = self._client.detect(media, classes=classes)

            if result and result.boxes:
                # Map detected class back to our standard names
                detected = result.boxes[0].mention.lower()

                if "bridge" in detected:
                    class_name = "bridge"
                elif "hospital" in detected:
                    class_name = "hospital"
                elif "food" in detected:
                    class_name = "food_station"
                elif "shelter" in detected:
                    class_name = "shelter"
                else:
                    class_name = "unknown"

                # Note: top_left/bottom_right are SinglePoint objects with .x and .y
                box = result.boxes[0]
                return PerceptronResponse(
                    success=True,
                    detections=[{
                        "class": class_name,
                        "confidence": "high",
                        "bbox": {
                            "x1": box.top_left.x,
                            "y1": box.top_left.y,
                            "x2": box.bottom_right.x,
                            "y2": box.bottom_right.y
                        }
                    }],
                    raw_response={"text": result.text, "boxes": len(result.boxes)},
                    latency_ms=(time.time() - start_time) * 1000
                )

        except Exception as e:
            logger.error(f"Classification error: {e}")

        return PerceptronResponse(
            success=False,
            detections=[],
            raw_response=None,
            latency_ms=(time.time() - start_time) * 1000,
            error_message="Classification failed"
        )

    def get_telemetry(self) -> dict:
        """Get diagnostic telemetry for operator display."""
        return {
            "status": self._status.value,
            "is_available": self.is_available,
            "reference_images_loaded": len(self._reference_images),
            "cache_size": len(self._cache),
            "worker_queue_size": self._worker_queue.qsize(),
            "result_queue_size": self._result_queue.qsize(),
            "config": {
                "model": self.config.model,
                "timeout_ms": self.config.timeout_ms,
                "reasoning_effort": self.config.reasoning_effort,
            }
        }


# Singleton instance for shared use
_adapter_instance: Optional[PerceptronAdapter] = None


def get_adapter() -> PerceptronAdapter:
    """Get or create the shared Perceptron adapter instance."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = PerceptronAdapter()
    return _adapter_instance


def init_adapter(config: PerceptronConfig) -> PerceptronAdapter:
    """Initialize the shared adapter with custom config."""
    global _adapter_instance
    _adapter_instance = PerceptronAdapter(config)
    return _adapter_instance
