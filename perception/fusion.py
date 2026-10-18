"""Lane C ClassifierPort for Lane B's single tracker and confidence pipeline.

No second tracker or lifecycle state machine. When the SDK omits confidence,
three distinct camera frames must agree; no model probability is invented.
"""
from dataclasses import replace
from queue import Queue, Empty, Full
import threading
import time

from .classifier import ClassifierConfig, PieceClassifier
from .events import ClassificationResult, ROIRequest
from .perceptron_adapter import PerceptronAdapter, PerceptronConfig


class PerceptronClassifierPort:
    def __init__(self, classifier=None):
        self.classifier = classifier or PieceClassifier(ClassifierConfig(cache_classifications=False, use_few_shot=False),
            adapter=PerceptronAdapter(PerceptronConfig(enable_caching=False)))
        self.requests = Queue(maxsize=8)
        self.results = Queue()
        self.votes = {}
        self._latencies_ms = []
        self._lat_lock = threading.Lock()
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._run, name="perceptron-classifier", daemon=True)
        self.thread.start()

    def submit(self, request: ROIRequest):
        try:
            self.requests.put_nowait(request)
        except Full:
            self.results.put(ClassificationResult(request.track_id, None, "perceptron", None, False,
                                                  request_id=request.request_id, evidence="classifier queue full"))

    def _run(self):
        while not self.closed.is_set():
            try:
                request = self.requests.get(timeout=0.1)
            except Empty:
                continue
            try:
                started = time.monotonic()
                result = self.classifier.classify_sync(request.track_id, request.crop_bgr)
                with self._lat_lock:
                    self._latencies_ms.append((time.monotonic() - started) * 1000.0)
                    self._latencies_ms = self._latencies_ms[-200:]
                key = (request.session_id, request.track_id)
                label, frames = self.votes.get(key, (None, set()))
                if request.reason in ("appearance_changed", "reacquired") or label != result.piece_class:
                    frames = set()
                if result.valid and result.class_source == "perceptron" and result.piece_class:
                    frames.add(request.frame_id)
                else:
                    frames = set()
                self.votes[key] = (result.piece_class, frames)
                valid = result.valid and result.class_source == "perceptron" and len(frames) >= 3 and (result.confidence is None or result.confidence >= .6)
                self.results.put(replace(result, valid=valid, request_id=request.request_id,
                                         agreement_frames=len(frames)))
                if not valid and self.closed.wait(0.25):
                    break
            except Exception as error:
                self.results.put(ClassificationResult(request.track_id, None, "perceptron", None, False,
                    request_id=request.request_id, evidence=f"classifier error: {type(error).__name__}"))

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.results.get_nowait())
            except Empty:
                return out

    def status(self):
        telemetry = self.classifier.get_telemetry()
        adapter = telemetry.get("perceptron", {})
        with self._lat_lock:
            lat = sorted(self._latencies_ms)
        return {"kind": "perceptron", "available": adapter.get("is_available", False),
                "queue_size": self.requests.qsize(), "consensus_required": 3,
                "latency_ms_p50": round(lat[len(lat) // 2], 1) if lat else None,
                "latency_ms_p95": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1) if lat else None,
                **telemetry}

    def close(self):
        self.closed.set()
        self.thread.join(timeout=1)
        self.classifier.shutdown()


def create_classifier():
    return PerceptronClassifierPort()
