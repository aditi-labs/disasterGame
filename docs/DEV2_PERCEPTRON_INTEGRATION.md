# Perceptron integration

The active integration is `perception.fusion:create_classifier`, a ClassifierPort consumed by the existing `PerceptionService`. The earlier parallel fusion tracker and its incompatible `PhysicalLifecycle`/`TrackingUpdate` assumptions have been removed. The OpenCV service owns identity, motion, occlusion and lifecycle; the classifier owns ROI class evidence.

Install the root `requirements.txt` and set `PERCEPTRON_API_KEY` in the repository `.env` or service environment. Start the connected services with `scripts/start_all.ps1 -WithPerception`, or use the explicit camera command in [PHYSICAL_INTEGRATION](PHYSICAL_INTEGRATION.md).

The port accepts `ROIRequest`, runs classification outside the camera loop, and returns `ClassificationResult` with the original track/request IDs. Its queue is bounded. Three distinct camera frames must agree; frame or SDK result caching cannot manufacture that count. Session/class changes reset agreement. Request IDs prevent late answers from applying to a new track after reset.

The SDK wrapper uses JPEG media bytes, `detect(...).boxes`, configured model/reasoning and SDK request timeout. It does not synthesize `confidence="high"` for a returned box. Missing numeric confidence stays absent; local agreement and existing measured geometric/stability gates decide the band. Unknown classes, mixed classes, partial/failed responses and missing credentials do not produce a valid piece. The game path does not automatically substitute color heuristics for Perceptron.

Unannotated reference photographs remain in `assets/piece_references/` for inspection and future measured classifier work; they are not presented as SDK few-shot examples. The available photographs cover bridge, hospital and food station. No shelter reference is checked in. SDK behavior was checked against installed 0.4.0 and the [official package documentation](https://pypi.org/project/perceptron/).

The service sends `PhysicalObservation` to `/perception/physical` with the backend epoch obtained from status responses. Accepted feedback binds camera tracks to world tokens. Rejected moves preserve the existing binding, removals clear it only on confirmation, and reset invalidates stale queued events. All world consequences still pass through the retained reducer.

`perception/tests/test_classifier_port.py` uses controlled SDK responses; it verifies parsing, missing confidence, unknown/mixed responses, distinct-frame agreement and class/session changes without paid API calls. Existing synthetic-image OpenCV tests and actual board-photo tests remain. They do not establish live Perceptron accuracy or end-to-end latency. Record and measure those on the real board with projector lighting before claiming hardware readiness.
