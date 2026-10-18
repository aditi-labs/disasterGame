"""Seams added after merging remote main: Dev 2 classifier port, control API, status keys, guards."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import numpy as np
import pytest

from perception.camera import droidcam_url, list_cameras
from perception.fusion import PerceptronClassifierPort
from perception.config import PerceptionConfig
from perception.events import ClassificationResult, ConfidenceBand, Lifecycle, PhysicalLifecycle, PieceClass, ROIRequest
from perception.service import NullClassifier, PerceptionService, observe_url_is_legacy_gateway
from perception.tracker import PieceTracker

from .conftest import SyntheticBoard, camera_homography, make_registration, render_camera
from .test_service import BRIDGE, HOSPITAL, by_lifecycle, fast_config, feed
from .test_tracker import CFG as TRACKER_CFG, cand, run

def _roi(track_id="t1", request_id="r1") -> ROIRequest:
    return ROIRequest(request_id=request_id, session_id="s", track_id=track_id, frame_id=1,
                      crop_bgr=np.zeros((20, 30, 3), np.uint8), crop_bbox_warp_px=(0, 0, 30, 20), board_uv=None,
                      orientation_deg=None, observed_at_ms=0, reason="new_track")



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


# ---------------------------------------------------------------- lag / accuracy ideas

def test_prepare_roi_rotates_long_axis_horizontal_and_downscales():
    from perception.candidate_regions import prepare_roi
    import cv2
    canvas = np.zeros((400, 400, 3), np.uint8)
    box = cv2.boxPoints(((200, 200), (300, 100), 40.0))
    cv2.fillConvexPoly(canvas, box.astype(np.int32), (40, 220, 240))
    out = prepare_roi(canvas, 40.0, max_px=200, canonical_rotation=True)
    assert max(out.shape[:2]) == 200
    ys, xs = np.where(out[..., 2] > 200)
    assert (xs.max() - xs.min()) > 2.2 * (ys.max() - ys.min())   # long axis now horizontal
    same = prepare_roi(canvas, 40.0, max_px=0, canonical_rotation=False)
    assert same.shape == canvas.shape


def test_aruco_cadence_reuses_registration_between_detections_and_status_reports_timings(tmp_path):
    board = SyntheticBoard()
    reg = make_registration(tmp_path)
    cam = lambda img: render_camera(img, camera_homography(board.geometry))  # noqa: E731
    cfg = fast_config(tmp_path, reg)
    cfg.board.redetect_every_n_frames = 3
    cfg.board.adaptive_cadence = False
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 6)
    detections_before = svc.registrar.last_state
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 9, start_frame=7, t0=t)
    assert by_lifecycle(obs, Lifecycle.PLACED)
    st = svc.status()
    assert st["aruco_cadence"] == 3
    timing = st["timing"]
    assert timing["total"]["p95_ms"] is not None and timing["candidates"]["p50_ms"] is not None
    # two of every three frames skip ArUco, so its median cost is near zero
    assert timing["aruco"]["p50_ms"] < timing["total"]["p50_ms"]
    svc.stop()


def test_adaptive_cadence_backs_off_when_the_loop_is_slow(tmp_path):
    board = SyntheticBoard()
    reg = make_registration(tmp_path)
    cam = lambda img: render_camera(img, camera_homography(board.geometry))  # noqa: E731
    cfg = fast_config(tmp_path, reg)
    cfg.board.target_fps = 10000.0  # an impossible budget: every frame is "too slow"
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    feed(svc, [cam(board.empty)] * 65)
    assert svc.status()["aruco_cadence"] == 3  # bumped twice (frames 30 and 60), capped at the max
    assert any("ArUco every" in w for w in svc.warnings)
    svc.stop()


def test_fast_preset_sets_the_weak_laptop_knobs():
    from perception.service import build_parser, config_from_args
    cfg = config_from_args(build_parser().parse_args(["--fast"]))
    assert cfg.board.warp_px_per_mm == 1.0 and cfg.board.redetect_every_n_frames == 2
    assert cfg.service.show_warp is False and cfg.service.roi_max_px == 256


# ---------------------------------------------------------------- the single classifier port (perception.fusion)
class _SyncDev2:
    """Mimics PieceClassifier.classify_sync / get_telemetry / shutdown with scripted answers."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.shut = False

    def classify_sync(self, track_id, crop):
        self.calls += 1
        return self.answer(track_id)

    def get_telemetry(self):
        return {"perceptron": {"is_available": True}}

    def shutdown(self):
        self.shut = True


def _drain(port, n, timeout_s=3.0):
    out = []
    deadline = time.time() + timeout_s
    while len(out) < n and time.time() < deadline:
        out.extend(port.poll())
        time.sleep(0.01)
    return out


def test_port_needs_three_agreeing_frames_before_a_result_is_valid():
    port = PerceptronClassifierPort(_SyncDev2(lambda t: ClassificationResult(t, PieceClass.BRIDGE, "perceptron", None, True)))
    try:
        for i in range(3):
            r = _roi("t1", f"r{i}")
            r.frame_id = 10 + i
            port.submit(r)
        results = _drain(port, 3)
        assert [r.valid for r in results] == [False, False, True]
        assert results[-1].agreement_frames == 3 and results[-1].piece_class is PieceClass.BRIDGE
        assert results[-1].request_id == "r2"
        st = port.status()
        assert st["consensus_required"] == 3 and st["latency_ms_p50"] is not None and st["available"]
    finally:
        port.close()


def test_port_never_accepts_colour_fallback_classes():
    port = PerceptronClassifierPort(_SyncDev2(lambda t: ClassificationResult(t, PieceClass.HOSPITAL, "color_fallback", 0.85, True)))
    try:
        for i in range(4):
            r = _roi("t1", f"r{i}"); r.frame_id = i
            port.submit(r)
        results = _drain(port, 4)
        assert results and all(not r.valid for r in results)
        tr = PieceTracker(TRACKER_CFG)
        run(tr, [[cand(100, 100)]] * 3)
        tr.mark_classification_requested("t1", results[-1].request_id)
        tr.apply_classification(results[-1], 1)
        assert tr.tracks["t1"].classification.piece_class is None and tr.tracks["t1"].needs_classification
    finally:
        port.close()


def test_old_classifier_port_module_is_an_alias():
    import perception.classifier_port as alias
    assert alias.PerceptronClassifierPort is PerceptronClassifierPort
