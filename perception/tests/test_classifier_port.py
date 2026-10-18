"""SDK contract and fusion tests with controlled responses; no paid API calls."""
from types import SimpleNamespace
import time

import numpy as np
import pytest

from perception.classifier import ClassifierConfig, PieceClassifier
from perception.events import ClassificationResult, PieceClass, ROIRequest
from perception.fusion import PerceptronClassifierPort
from perception.perceptron_adapter import PerceptronAdapter, PerceptronConfig, PerceptronResponse, PerceptronStatus


@pytest.fixture
def classifier(monkeypatch):
    monkeypatch.delenv("PERCEPTRON_API_KEY", raising=False)
    adapter = PerceptronAdapter(PerceptronConfig(enable_caching=False))
    obj = PieceClassifier(ClassifierConfig(cache_classifications=False, use_few_shot=False), adapter)
    yield obj
    obj.shutdown()


def test_sdk_boxes_have_no_invented_confidence_and_use_configured_model(classifier):
    calls = []
    box = SimpleNamespace(mention="bridge", top_left=SimpleNamespace(x=10, y=20), bottom_right=SimpleNamespace(x=900, y=800))
    adapter = classifier._adapter
    adapter._client = SimpleNamespace(image=lambda data: data,
        detect=lambda media, **kwargs: calls.append(kwargs) or SimpleNamespace(boxes=[box]))
    adapter._status = PerceptronStatus.CONNECTED
    result = classifier.classify_sync("test-track", np.zeros((32, 48, 3), dtype=np.uint8))
    assert result.piece_class == PieceClass.BRIDGE and result.confidence is None
    assert calls[0]["model"] == adapter.config.model


def test_compile_only_ambiguous_unknown_and_missing_credentials_do_not_classify(classifier):
    for labels in [["bridge", "hospital"], ["bridge", "bridge"], ["dragon"], []]:
        r = classifier._process_response("test-track", PerceptronResponse(True, [{"class": label} for label in labels], {}, 1))
        assert not r.valid
    result = classifier.classify_sync("offline", np.zeros((32, 32, 3), dtype=np.uint8))
    assert not result.valid and result.piece_class is None and result.class_source == "perceptron"


@pytest.mark.parametrize("value", [None, "high", float("nan"), 9, -1, True])
def test_confidence_only_passes_through_reported_valid_numeric_values(classifier, value):
    assert classifier._parse_confidence(value) is None
    assert classifier._parse_confidence(.83) == .83


class ControlledClassifier:
    label = PieceClass.BRIDGE
    def classify_sync(self, track, crop):
        return ClassificationResult(track, self.label, "perceptron", None, True)
    def get_telemetry(self):
        return {"perceptron": {"is_available": True}}
    def shutdown(self):
        pass


def request(frame, session="test-session"):
    return ROIRequest(str(frame), session, "t1", frame, np.zeros((10, 10, 3), dtype=np.uint8),
                      (0, 0, 10, 10), None, None, 0, "retry_invalid_result")


def answer(port, req):
    port.submit(req)
    end = time.monotonic() + 2
    while time.monotonic() < end:
        results = port.poll()
        if results:
            return results[0]
        time.sleep(.01)
    pytest.fail("classifier worker did not return")


def test_consensus_requires_distinct_frames_and_resets_after_class_or_session_change():
    classifier = ControlledClassifier()
    port = PerceptronClassifierPort(classifier)
    try:
        assert not answer(port, request(1)).valid
        assert not answer(port, request(1)).valid
        assert not answer(port, request(2)).valid
        accepted = answer(port, request(3))
        assert accepted.valid and accepted.agreement_frames == 3 and accepted.confidence is None
        classifier.label = PieceClass.HOSPITAL
        assert not answer(port, request(4)).valid
        assert not answer(port, request(5, "new-session")).valid
        assert port.status()["available"]
    finally:
        port.close()
