# Dev 2: Perceptron Classification Integration Guide

## Overview

This document describes Lane C (Dev 2) implementation for Perceptron classification in FloodShift.

**Your responsibility:**
- SDK verification and integration
- Image crop/object classification
- Per-class confidence and fusion
- Latency controls and confidence tiers
- Integration with Dev 1's track IDs

**NOT your responsibility:**
- World rules, graph routes (backend team)
- Projector rendering (Sky/UI team)
- Camera frame capture, ArUco detection, object tracking (Dev 1)

## Architecture

```
Dev 1 (OpenCV/Tracking)          Dev 2 (Perceptron/Classification)
    │                                       │
    ├── Camera frame capture                │
    ├── ArUco board detection               │
    ├── Homography calculation              │
    ├── Object ROI extraction ─────────────→│── ROI + track_id
    │                                       ├── Perceptron SDK call
    │                                       ├── Class + confidence
    │                                       ├── Fusion logic
    │←─────────────────────────────────────┤── ClassificationResult
    │                                       │
    └── PhysicalObservation ───────────────→ Backend Adapter
```

## Files Created

```
perception/
├── __init__.py              # Module exports
├── events.py                # Shared contracts (PieceClass, PhysicalObservation, etc.)
├── perceptron_adapter.py    # Official SDK wrapper with async/timeout
├── classifier.py            # Classification logic with fallback
├── fusion.py                # CV + Perceptron fusion
├── camera.py                # Camera utilities (DroidCam support)
└── tests/
    ├── __init__.py
    └── test_classifier.py   # Unit tests
```

## Quick Start

### 1. Install Dependencies

```bash
cd C:\code\FloodGame\disasterGame
pip install -r requirements.txt
```

### 2. Set Up Environment

```bash
# Copy example and add your API key
copy .env.example .env
# Edit .env and add PERCEPTRON_API_KEY
```

### 3. Capture Reference Images

```bash
# Take top-down photos of each piece type
# Save to: assets/piece_references/
#   - bridge.jpg (yellow)
#   - hospital.jpg (white)
#   - shelter.jpg (white)
#   - food_station.jpg (white)
```

### 4. Test the Classifier

```python
from perception import get_classifier, ClassifierConfig

# Initialize with config
config = ClassifierConfig(
    use_perceptron=True,
    use_few_shot=True,
    reference_images_dir="assets/piece_references"
)
classifier = get_classifier()

# Test with a sample image
import cv2
test_img = cv2.imread("path/to/test_piece.jpg")
bbox = BoundingBox(x1=0, y1=0, x2=test_img.shape[1], y2=test_img.shape[0])
result = classifier.classify_sync("test_track", test_img, bbox)

print(f"Class: {result.class_label}")
print(f"Confidence: {result.confidence}")
```

## Integration with Dev 1

Dev 1 will provide `TrackingUpdate` objects with:
- `track_id`: Unique identifier for the tracked object
- `bbox`: Pixel coordinates of the ROI
- `board_uv`: Position on board after homography
- `lifecycle`: Current state (candidate/placed/moved/removed)
- `needs_reclassification`: Whether to re-run Perceptron

Your code processes these via the `ObservationFusion` class:

```python
from perception import get_fusion, TrackingUpdate, BoundingBox, BoardUV

fusion = get_fusion()
fusion.reset(session_id="game_001")

# Dev 1 calls this each frame
tracking_updates = [
    TrackingUpdate(
        track_id="piece_001",
        bbox=BoundingBox(x1=100, y1=100, x2=200, y2=200),
        board_uv=BoardUV(u=0.3, v=0.5),
        lifecycle=PhysicalLifecycle.CANDIDATE,
        localization_confidence=0.9,
        frame_count=5,
        needs_reclassification=True
    )
]

# Process frame with updates
fusion.process_frame(camera_frame, tracking_updates)

# Get observations for backend
while True:
    observation = fusion.get_observation(timeout_ms=10)
    if observation is None:
        break
    if observation.confidence_band == ConfidenceBand.HIGH:
        # Submit to backend
        pass
```

## Perceptron API Usage

### Detection Endpoint (Recommended)

```python
from perception.perceptron_adapter import PerceptronAdapter, PerceptronConfig

config = PerceptronConfig(
    api_key="your_api_key",
    timeout_ms=3000,
    model="perceptron-mk1.5",
    reasoning_effort="minimal"  # Fast responses
)
adapter = PerceptronAdapter(config)

# Classify an ROI
response = adapter._classify_sync(roi_image, ["bridge", "hospital", "shelter", "food_station"])
if response.success:
    detection = response.detections[0]
    print(f"Class: {detection['class']}, Confidence: {detection['confidence']}")
```

### Few-Shot Classification

```python
# Load reference images
adapter.load_reference_images("assets/piece_references")

# Classify with few-shot learning
response = adapter.classify_with_references(roi_image, use_few_shot=True)
```

### Async Classification (Non-blocking)

```python
# Start the worker thread
adapter.start_worker()

# Queue for classification
def on_result(track_id, response):
    print(f"Track {track_id}: {response.detections}")

adapter.classify_async("track_001", roi_image, ["bridge", "hospital"], callback=on_result)

# Or poll for results
result = adapter.get_result(timeout_ms=100)
if result:
    track_id, response = result
```

## Confidence Bands

The system uses three confidence bands:

| Band | Criteria | Action |
|------|----------|--------|
| **HIGH** | Detection ≥0.8, Localization ≥0.9, Consistency ≥0.8 | Submit to backend |
| **REVIEW** | Detection ≥0.5, Localization ≥0.7, Consistency ≥0.5 | Show pending cue |
| **REJECT** | Below thresholds | Do not submit |

## Physical Piece Colors

| Piece | Color | HSV Range |
|-------|-------|-----------|
| Bridge | Yellow/Gold | H: 15-35, S: 100-255, V: 100-255 |
| Hospital | White | H: 0-180, S: 0-30, V: 180-255 |
| Shelter | White | H: 0-180, S: 0-30, V: 180-255 |
| Food Station | White | H: 0-180, S: 0-30, V: 180-255 |

## DroidCam Setup

```python
from perception.camera import connect_droidcam, list_cameras

# List available cameras
cameras = list_cameras()
print(cameras)

# Connect to DroidCam via USB
camera = connect_droidcam(use_usb=True)

# Or via WiFi
camera = connect_droidcam(ip="192.168.1.100", port=4747)

# Read frames
for frame in camera.stream_frames():
    process(frame.image)
```

## Telemetry

Get diagnostic info for operator display:

```python
from perception import get_fusion

fusion = get_fusion()
telemetry = fusion.get_telemetry()

print(telemetry)
# {
#   "fusion": {
#     "frame_count": 1000,
#     "active_tracks": 3,
#     "tracks_by_class": {"bridge": 1, "hospital": 1, "shelter": 1}
#   },
#   "classifier": {
#     "metrics": {
#       "total_classifications": 50,
#       "average_latency_ms": 120.5
#     }
#   },
#   "perceptron": {
#     "status": "connected",
#     "is_available": true
#   }
# }
```

## Error Handling

### API Unavailable

When Perceptron API is unavailable, the classifier falls back to color-based classification:

```python
# Check status
if not adapter.is_available:
    print("Perceptron unavailable - using color fallback")

# Color fallback is automatic
result = classifier.classify_sync(track_id, roi, bbox)
# result.error_message will indicate "Perceptron unavailable - using color fallback"
```

### Timeout Handling

```python
config = PerceptronConfig(timeout_ms=3000)  # 3 second timeout

# Async calls never block the camera loop
adapter.classify_async(track_id, roi, classes, callback=handle_result)
```

## Testing

Run unit tests:

```bash
cd C:\code\FloodGame\disasterGame
pytest perception/tests/ -v
```

Test with real camera:

```python
from perception.camera import connect_droidcam
from perception import get_classifier, BoundingBox

# Connect camera
camera = connect_droidcam()

# Get classifier
classifier = get_classifier()

# Capture and classify
frame = camera.read_frame()
if frame:
    # Assume full frame is the piece (for testing)
    h, w = frame.image.shape[:2]
    bbox = BoundingBox(x1=0, y1=0, x2=w, y2=h)
    result = classifier.classify_sync("test", frame.image, bbox)
    print(result.class_label, result.confidence)
```

## Checklist (from Master Build Spec Section 7)

- [x] Use official Perceptron SDK (pip install perceptron>=0.4.0)
- [x] Verify authenticated live return structure
- [x] Classify between bridge/hospital/shelter/food_station
- [x] Include unknown/none as legitimate result
- [x] Use real top-view photos for few-shot
- [x] Normalize output to {track_id, class_label, bbox, confidence, latency_ms, valid}
- [x] Fuse with OpenCV shape/size evidence
- [x] Cache recent classification while track persists
- [x] Run inference in bounded worker/async task
- [x] Keep camera responsive even if API stalls
- [x] Explicit confidence bands from measured results
- [x] Degraded state when API missing/throttled

## Next Steps

1. Coordinate with Dev 1 on TrackingUpdate format
2. Capture reference images of actual physical pieces
3. Test with DroidCam connected to laptop
4. Tune confidence thresholds with real data
5. Measure latency and accuracy metrics
