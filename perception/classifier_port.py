"""Lane B <-> Lane C seam: drive Dev 2's classifier through the one tracker lifecycle.

Spec section 1 gives Lane B the track IDs, lifecycle and emission, and Lane C the
class evidence.  Spec 6.6 forbids overlapping tracker stacks.  This port therefore
wraps ``perception.classifier.PieceClassifier`` (Dev 2) in the
:class:`perception.service.ClassifierPort` interface so that *only*
``perception.service`` emits ``PhysicalObservation`` events, with Dev 2's class
results attached to Dev 1's tracks.

Honesty rules enforced here (spec 5 and 7):

* A result from the colour fallback (``class_source != "perceptron"``) is kept as a
  labelled hint but its confidence is reported as ``None``: a colour rule is not a
  measured recognition confidence, so such a track can never reach the HIGH band on
  its own.  The operator can still confirm it (``apply_operator_class``).
* A valid-but-unknown answer (no class) is passed through with ``piece_class=None``;
  the tracker keeps asking rather than freezing.
* Nothing here blocks: Dev 2's adapter runs its own worker thread and calls back.

Use::

    python -m perception.service --classifier perception.classifier_port:create_classifier
"""
from __future__ import annotations

import threading
from typing import Any

from .events import ClassificationResult, ROIRequest

MODEL_SOURCES = {"perceptron"}


class PerceptronClassifierPort:
    def __init__(self, classifier=None, *, trust_non_model_confidence: bool = False):
        if classifier is None:
            from .classifier import get_classifier  # Dev 2 module; imported lazily
            classifier = get_classifier()
        self.classifier = classifier
        self.trust_non_model_confidence = trust_non_model_confidence
        self._lock = threading.Lock()
        self._results: list[ClassificationResult] = []
        self._pending: dict[str, str] = {}  # track_id -> request_id of the latest request
        self.submitted = 0
        self.received = 0
        self.downgraded_fallback = 0

    # -- ClassifierPort
    def submit(self, request: ROIRequest) -> None:
        self.submitted += 1
        with self._lock:
            self._pending[request.track_id] = request.request_id

        def on_result(track_id: str, result: ClassificationResult) -> None:
            with self._lock:
                request_id = self._pending.pop(track_id, request.request_id)
                self._results.append(self._normalise(result, request_id))
                self.received += 1

        self.classifier.classify_async(request.track_id, request.crop_bgr, callback=on_result)

    def poll(self) -> list[ClassificationResult]:
        with self._lock:
            out, self._results = self._results, []
        return out

    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {"kind": "perceptron_port", "submitted": self.submitted, "received": self.received,
                                "fallback_results_downgraded": self.downgraded_fallback}
        adapter = getattr(self.classifier, "_adapter", None)
        available = bool(getattr(adapter, "is_available", False))
        info["available"] = available
        try:
            if adapter is not None and hasattr(adapter, "get_telemetry"):
                info["perceptron"] = adapter.get_telemetry()
            elif adapter is not None and hasattr(adapter, "status"):
                st = adapter.status
                info["perceptron"] = {"status": getattr(st, "value", str(st))}
        except Exception as exc:  # telemetry must never break the loop
            info["perceptron"] = {"error": str(exc)[:120]}
        if not available:
            info["note"] = "Perceptron unavailable: colour-fallback classes are hints only (confidence withheld)"
        return info

    def close(self) -> None:
        shutdown = getattr(self.classifier, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                pass

    # -- internals
    def _normalise(self, result: ClassificationResult, request_id: str) -> ClassificationResult:
        confidence = result.confidence
        if result.class_source not in MODEL_SOURCES and not self.trust_non_model_confidence and confidence is not None:
            confidence = None
            self.downgraded_fallback += 1
        return ClassificationResult(
            track_id=result.track_id,
            piece_class=result.piece_class if result.valid else None,
            class_source=result.class_source,
            confidence=confidence,
            valid=bool(result.valid),
            latency_ms=result.latency_ms,
            evidence=result.evidence,
            request_id=request_id,
        )


def create_classifier() -> PerceptronClassifierPort:
    """Factory for ``--classifier perception.classifier_port:create_classifier``."""
    return PerceptronClassifierPort()
