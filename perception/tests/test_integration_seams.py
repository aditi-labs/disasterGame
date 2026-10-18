"""Seams added after merging remote main: Dev 2 classifier port, control API, status keys, guards."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from perception.camera import droidcam_url, list_cameras
from perception.classifier_port import PerceptronClassifierPort
from perception.config import PerceptionConfig
from perception.events import ClassificationResult, ConfidenceBand, Lifecycle, PhysicalLifecycle, PieceClass, ROIRequest
from perception.service import NullClassifier, PerceptionService, observe_url_is_legacy_gateway
from perception.tracker import PieceTracker

from .conftest import SyntheticBoard, camera_homography, make_registration, render_camera
from .test_service import BRIDGE, HOSPITAL, by_lifecycle, fast_config, feed
from .test_tracker import CFG as TRACKER_CFG, cand, run


class FakeDev2Classifier:
    """Mimics perception.classifier.PieceClassifier.classify_async(track_id, roi, callback)."""

    def __init__(self, result_factory):
        self.result_factory = result_factory
        self.calls = 0
        self._adapter = type("A", (), {"is_available": False, "get_telemetry": lambda self: {"status": "disconnected"}})()

    def classify_async(self, track_id, roi_image, callback=None):
        self.calls += 1
        assert roi_image.ndim == 3
        callback(track_id, self.result_factory(track_id))

    def shutdown(self):
        self.shut = True


def _roi(track_id="t1", request_id="r1") -> ROIRequest:
    return ROIRequest(request_id=request_id, session_id="s", track_id=track_id, frame_id=1,
                      crop_bgr=np.zeros((20, 30, 3), np.uint8), crop_bbox_warp_px=(0, 0, 30, 20), board_uv=None,
                      orientation_deg=None, observed_at_ms=0, reason="new_track")


def test_spec_lifecycle_alias_exists_for_lane_c():
    assert PhysicalLifecycle is Lifecycle


def test_port_passes_model_results_through_with_request_id():
    fake = FakeDev2Classifier(lambda t: ClassificationResult(t, PieceClass.BRIDGE, "perceptron", 0.93, True, latency_ms=400))
    port = PerceptronClassifierPort(fake)
    port.submit(_roi())
    out = port.poll()
    assert len(out) == 1 and out[0].piece_class is PieceClass.BRIDGE and out[0].confidence == 0.93
    assert out[0].request_id == "r1" and out[0].class_source == "perceptron"
    assert port.poll() == []
    port.close()
    assert fake.shut


def test_port_withholds_confidence_from_colour_fallback_so_it_cannot_be_high():
    fake = FakeDev2Classifier(lambda t: ClassificationResult(t, PieceClass.HOSPITAL, "color_fallback", 0.85, True,
                                                              evidence="Color-based: PINK = hospital"))
    port = PerceptronClassifierPort(fake)
    port.submit(_roi())
    res = port.poll()[0]
    assert res.piece_class is PieceClass.HOSPITAL and res.class_source == "color_fallback"
    assert res.confidence is None and port.downgraded_fallback == 1
    assert port.status()["available"] is False and "hint" in port.status()["note"]
    # through the tracker + scorer this stays REVIEW: a colour rule is not recognition confidence
    tr = PieceTracker(TRACKER_CFG)
    run(tr, [[cand(100, 100)]] * 3)
    tr.mark_classification_requested("t1", "r1")
    assert tr.apply_classification(res, 1)
    assert tr.tracks["t1"].classification.piece_class is PieceClass.HOSPITAL
    assert tr.tracks["t1"].classification.confidence is None


def test_port_unknown_class_keeps_tracker_asking():
    fake = FakeDev2Classifier(lambda t: ClassificationResult(t, None, "perceptron", None, True, evidence="no detections"))
    port = PerceptronClassifierPort(fake)
    port.submit(_roi())
    res = port.poll()[0]
    tr = PieceTracker(TRACKER_CFG)
    run(tr, [[cand(100, 100)]] * 3)
    tr.mark_classification_requested("t1", "r1")
    tr.apply_classification(res, 1)
    t = tr.tracks["t1"]
    assert t.needs_classification and t.classification_reason == "retry_unknown_class"
    assert t.classification.piece_class is None


def test_service_with_dev2_port_reaches_high_only_for_model_results(tmp_path):
    board = SyntheticBoard()
    reg = make_registration(tmp_path)
    cam = lambda img: render_camera(img, camera_homography(board.geometry))  # noqa: E731
    cfg = fast_config(tmp_path, reg)
    fake = FakeDev2Classifier(lambda t: ClassificationResult(t, PieceClass.BRIDGE, "perceptron", 0.9, True))
    svc = PerceptionService(cfg, classifier=PerceptronClassifierPort(fake), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 10, start_frame=6, t0=t)
    placed = by_lifecycle(obs, Lifecycle.PLACED)
    assert placed[-1].confidence_band is ConfidenceBand.HIGH and placed[-1].class_source == "perceptron"
    assert svc.status()["perceptron"] == "degraded"  # fake adapter reports unavailable
    svc.stop()


def test_observe_url_guard_refuses_the_legacy_gateway_endpoint():
    assert observe_url_is_legacy_gateway("http://localhost:8000/perception/observe")
    assert observe_url_is_legacy_gateway("http://localhost:8000/perception/observe/")
    assert not observe_url_is_legacy_gateway("http://localhost:8000/adapter/observe")
    assert not observe_url_is_legacy_gateway(None)
    from perception.service import main
    assert main(["--observe-url", "http://localhost:8000/perception/observe", "--no-window"]) == 2


def test_status_has_honest_flat_keys_for_the_gateway(tmp_path):
    board = SyntheticBoard()
    reg = make_registration(tmp_path)
    cam = lambda img: render_camera(img, camera_homography(board.geometry))  # noqa: E731
    cfg = fast_config(tmp_path, reg)
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    st = svc.status()
    assert st["calibration"] == "uncalibrated" and st["perceptron"] == "not_connected" and st["objects_tracked"] == 0
    feed(svc, [cam(board.empty)] * 3)
    st = svc.status()
    assert st["calibration"] == "valid_unmeasured"  # photo/synthetic registration is never called "calibrated"
    assert st["mode"] == "recording"
    svc.stop()


def test_control_api_queues_and_applies_commands_on_the_next_frame(tmp_path):
    board = SyntheticBoard()
    reg = make_registration(tmp_path)
    cam = lambda img: render_camera(img, camera_homography(board.geometry))  # noqa: E731
    cfg = fast_config(tmp_path, reg)
    cfg.service.control_port = 0  # ephemeral
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    base = f"http://{svc.control.host}:{svc.control.port}"

    def post(path, payload=None):
        req = urllib.request.Request(base + path, data=json.dumps(payload or {}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, json.loads(r.read())

    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE, HOSPITAL]))] * 10, start_frame=6, t0=t)
    assert sorted(svc.tracker.tracks) == ["t1", "t2"]
    old_session = svc.session_id

    code, body = post("/control/feedback", {"track_id": "t1", "accepted": True, "world_token_id": "tok-1"})
    assert code == 202 and body["queued"]
    assert svc.tracker.tracks["t1"].world_token_id is None  # not yet: applied on the next frame
    feed(svc, [cam(board.with_pieces([BRIDGE, HOSPITAL]))], start_frame=16, t0=t)
    assert svc.tracker.tracks["t1"].world_token_id == "tok-1"

    code, body = post("/control/operator_class", {"track_id": "t2", "piece_class": "hospital"})
    feed(svc, [cam(board.with_pieces([BRIDGE, HOSPITAL]))], start_frame=17, t0=t + 33)
    assert svc.tracker.tracks["t2"].classification.piece_class is PieceClass.HOSPITAL
    assert svc.tracker.tracks["t2"].classification.class_source == "operator"

    with urllib.request.urlopen(base + "/status", timeout=2) as r:
        status = json.loads(r.read())
    assert status["session_id"] == old_session and status["control"]["applied"] == 2

    post("/control/reset")
    feed(svc, [cam(board.empty)], start_frame=18, t0=t + 66)
    assert svc.session_id != old_session and svc.tracker.tracks == {}

    with pytest.raises(urllib.error.HTTPError) as exc:
        post("/control/bogus")
    assert exc.value.code == 404
    req = urllib.request.Request(base + "/control/pause", data=b"not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=2)
    assert exc.value.code == 400
    svc.stop()


def test_droidcam_helpers():
    assert droidcam_url("192.168.1.20") == "http://192.168.1.20:4747/video"
    assert droidcam_url("10.0.0.5", 4848) == "http://10.0.0.5:4848/video"
    cams = list_cameras(max_index=0)
    assert cams == []
