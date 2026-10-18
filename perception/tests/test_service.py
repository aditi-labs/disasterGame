"""End-to-end pipeline tests on synthetic frames fed straight into the service (no camera, no window)."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from perception.camera import CameraWorker, RecordingSource, open_source
from perception.config import PerceptionConfig
from perception.events import ClassificationResult, ConfidenceBand, Lifecycle, ObservationSource, PieceClass, ROIRequest
from perception.service import NullClassifier, PerceptionService
from perception.sinks import CallbackSink, HttpSink, JsonlSink

from .conftest import SyntheticBoard, camera_homography, frame_from, make_registration, render_camera, write_frames_dir

BRIDGE = {"center_mm": (210.0, 150.0), "size_mm": (70.0, 40.0), "color_bgr": (40, 220, 240)}
HOSPITAL = {"center_mm": (120.0, 300.0), "size_mm": (55.0, 45.0), "color_bgr": (250, 250, 250)}


def fast_config(tmp_path, registration) -> PerceptionConfig:
    cfg = PerceptionConfig()
    cfg.board.registration_path = str(registration.path)
    cfg.candidates.reference_frames = 3
    cfg.tracker.stable_frames = 4
    cfg.tracker.stable_ms = 0
    cfg.tracker.occlusion_grace_frames = 3
    cfg.tracker.occlusion_grace_ms = 0
    cfg.tracker.lost_candidate_frames = 2
    cfg.service.debug_window = False
    cfg.service.reference_settle_ms = 0
    cfg.service.candidate_emit_interval_ms = 1000
    cfg.service.jsonl_path = str(tmp_path / "obs.jsonl")
    # The synthetic camera is a pure 2-D homography, not a physical pinhole, so a solved
    # "camera pose" is meaningless here; exact-UV assertions run without parallax correction.
    cfg.service.parallax_correction = "off"
    return cfg


def test_parallax_guard_never_applies_an_implausible_correction(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    cfg.service.parallax_correction = "approximate"
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 10, start_frame=6, t0=t)
    placed = by_lifecycle(obs, Lifecycle.PLACED)[-1]
    g = placed.geometry
    assert g.parallax_correction_mm is None or g.parallax_correction_mm <= cfg.service.parallax_max_correction_mm
    expected_uv = np.array(BRIDGE["center_mm"]) / 420.0
    # even with a fictional pose the reported UV is within the guard's bound of the plane hit
    assert np.linalg.norm((np.array([placed.board_uv.u, placed.board_uv.v]) - expected_uv) * 420.0) <= cfg.service.parallax_max_correction_mm + 2.5
    svc.stop()


class RecordingClassifier:
    """Answers every request with a fixed class, from a worker thread, after a delay (never blocks)."""

    def __init__(self, piece_class: PieceClass | None = PieceClass.BRIDGE, confidence=0.91, delay_s=0.0, valid=True):
        self.piece_class, self.confidence, self.delay_s, self.valid = piece_class, confidence, delay_s, valid
        self.requests: list[ROIRequest] = []
        self._results: list[ClassificationResult] = []
        self._lock = threading.Lock()

    def submit(self, request: ROIRequest) -> None:
        self.requests.append(request)
        assert request.crop_bgr.size > 0 and request.crop_bgr.ndim == 3

        def answer():
            if self.delay_s:
                time.sleep(self.delay_s)
            with self._lock:
                self._results.append(ClassificationResult(request.track_id, self.piece_class, "test_classifier",
                                                          self.confidence, self.valid, latency_ms=int(self.delay_s * 1000),
                                                          request_id=request.request_id))
        threading.Thread(target=answer, daemon=True).start()

    def poll(self):
        with self._lock:
            out, self._results = self._results, []
        return out

    def status(self):
        return {"kind": "test", "available": True}

    def close(self):
        pass


def feed(service: PerceptionService, images: list[np.ndarray], *, start_frame=1, t0=0, dt=33):
    obs = []
    t = t0
    for i, img in enumerate(images):
        t += dt
        obs.extend(service.process_frame(frame_from(img, start_frame + i, t)))
    return obs, t


def by_lifecycle(observations, lifecycle: Lifecycle):
    return [o for o in observations if o.lifecycle is lifecycle]


@pytest.fixture
def scene(tmp_path):
    board = SyntheticBoard()
    reg = make_registration(tmp_path)
    h = camera_homography(board.geometry)
    cam = lambda img: render_camera(img, h)  # noqa: E731
    return board, reg, cam


def test_place_classify_move_remove_end_to_end(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    classifier = RecordingClassifier(PieceClass.BRIDGE, 0.91)
    seen = []
    svc = PerceptionService(cfg, classifier=classifier, sinks=[CallbackSink(seen.append), JsonlSink(cfg.service.jsonl_path)])

    empty = cam(board.empty)
    obs, t = feed(svc, [empty] * 5)
    assert svc.detector.reference_ready and obs == []
    assert svc.status()["registration"]["valid"]

    with_bridge = cam(board.with_pieces([BRIDGE]))
    obs, t = feed(svc, [with_bridge] * 12, start_frame=6, t0=t)
    placed = by_lifecycle(obs, Lifecycle.PLACED)
    assert len(placed) >= 1
    first = placed[0]
    assert first.source is ObservationSource.RECORDING and first.frame_provenance.startswith("recording:")
    assert first.board_uv is not None
    expected_uv = np.array(BRIDGE["center_mm"]) / 420.0
    assert np.allclose([first.board_uv.u, first.board_uv.v], expected_uv, atol=0.006)
    assert first.geometry.markers_used == 4 and first.geometry.reprojection_rms_uv < 0.003
    assert first.appearance.yellow_fraction > 0.8
    # the classifier answered asynchronously; the final placed emission must be HIGH with the class
    final = placed[-1]
    assert final.piece_class is PieceClass.BRIDGE and final.class_source == "test_classifier"
    assert final.confidence_band is ConfidenceBand.HIGH, final.reason
    assert final.detection_confidence == 0.91 and final.localization_confidence > 0.6
    assert len({o.event_id for o in obs}) == len(obs)  # every emission has a distinct id
    assert len(classifier.requests) == 1

    # adapter accepts: bind the track; sliding the piece 50 mm (a hand pushing it) now yields MOVED
    svc.handle_adapter_feedback({"track_id": final.track_id, "accepted": True, "world_token_id": "world-bridge-1"})
    moved_piece = dict(BRIDGE, center_mm=(260.0, 150.0))
    slide = [cam(board.with_pieces([dict(BRIDGE, center_mm=(210.0 + 10.0 * k, 150.0))])) for k in range(1, 6)]
    obs, t = feed(svc, slide + [cam(board.with_pieces([moved_piece]))] * 10, start_frame=20, t0=t)
    moved = by_lifecycle(obs, Lifecycle.MOVED)
    assert len(moved) == 1 and moved[0].track_id == final.track_id
    assert np.allclose([moved[0].board_uv.u, moved[0].board_uv.v], np.array(moved_piece["center_mm"]) / 420.0, atol=0.006)
    assert moved[0].piece_class is PieceClass.BRIDGE

    # lift it: REMOVED after the occlusion grace
    obs, t = feed(svc, [empty] * 8, start_frame=30, t0=t)
    removed = by_lifecycle(obs, Lifecycle.REMOVED)
    assert len(removed) == 1 and removed[0].track_id == final.track_id
    assert svc.tracker.tracks == {}

    lines = (tmp_path / "obs.jsonl").read_text().strip().splitlines()
    assert len(lines) == len(seen) == svc.observations_emitted
    assert all(json.loads(line)["session_id"] == svc.session_id for line in lines)
    svc.stop()


def test_unclassified_piece_stays_review_and_never_high(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([HOSPITAL]))] * 10, start_frame=6, t0=t)
    placed = by_lifecycle(obs, Lifecycle.PLACED)
    assert len(placed) == 1
    assert placed[0].piece_class is None and placed[0].detection_confidence is None
    assert placed[0].confidence_band is ConfidenceBand.REVIEW and "class not verified" in placed[0].reason
    assert placed[0].appearance.bright_low_sat_fraction > 0.8
    assert all(o.confidence_band is not ConfidenceBand.HIGH for o in obs)
    # the operator identifies it by eye: re-emission carries source 'operator', not a model name
    assert svc.apply_operator_class(placed[0].track_id, "hospital")
    again = svc.request_reemit(placed[0].track_id)
    assert again.piece_class is PieceClass.HOSPITAL and again.class_source == "operator"
    assert again.confidence_band is ConfidenceBand.REVIEW  # no reported confidence -> still not HIGH
    svc.stop()


def test_rejection_then_corrected_placement_is_accepted_again(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    svc = PerceptionService(cfg, classifier=RecordingClassifier(PieceClass.BRIDGE), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 10, start_frame=6, t0=t)
    placed = by_lifecycle(obs, Lifecycle.PLACED)
    svc.handle_adapter_feedback({"track_id": placed[-1].track_id, "accepted": False, "rejection_reason": "outside_site"})
    assert svc.tracker.tracks[placed[-1].track_id].rejected_reason == "outside_site"
    # nudged ~22 mm (inside the association gate, so it is the same track sliding, not a lift)
    corrected = dict(BRIDGE, center_mm=(228.0, 162.0))
    obs, t = feed(svc, [cam(board.with_pieces([corrected]))] * 10, start_frame=16, t0=t)
    again = by_lifecycle(obs, Lifecycle.PLACED)
    assert len(again) >= 1 and again[0].track_id == placed[-1].track_id
    assert by_lifecycle(obs, Lifecycle.MOVED) == []
    assert np.allclose([again[0].board_uv.u, again[0].board_uv.v], np.array(corrected["center_mm"]) / 420.0, atol=0.006)
    svc.stop()


def test_marker_occlusion_does_not_jump_or_remove_the_piece(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    svc = PerceptionService(cfg, classifier=RecordingClassifier(PieceClass.BRIDGE), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 10, start_frame=6, t0=t)
    uv0 = by_lifecycle(obs, Lifecycle.PLACED)[-1].board_uv
    import cv2
    from perception.geometry import apply_homography
    from .conftest import MARKER_UVS
    h = camera_homography(board.geometry)
    frames = []
    for mid in (12, 13):
        img = cam(board.with_pieces([BRIDGE]))
        px = apply_homography(h, board.geometry.uv_to_warp_px(MARKER_UVS[mid]).reshape(1, 2))[0]
        cv2.circle(img, (int(px[0]), int(px[1])), 70, (60, 50, 45), -1)
        frames.extend([img] * 6)
    obs, t = feed(svc, frames, start_frame=16, t0=t)
    assert by_lifecycle(obs, Lifecycle.REMOVED) == [] and by_lifecycle(obs, Lifecycle.MOVED) == []
    view = svc.track_views[list(svc.tracker.tracks)[0]]
    assert abs(view.uv[0] - uv0.u) < 0.004 and abs(view.uv[1] - uv0.v) < 0.004
    assert svc.status()["registration"]["markers_used"] in ([10, 11, 12], [10, 11, 13])
    svc.stop()


def test_lost_board_registration_holds_then_blocks_without_fabricating(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    cfg.board.registration_grace_ms = 200
    svc = PerceptionService(cfg, classifier=RecordingClassifier(PieceClass.BRIDGE), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 10, start_frame=6, t0=t)
    assert by_lifecycle(obs, Lifecycle.PLACED)
    blank = np.full_like(cam(board.empty), 90)
    obs, t = feed(svc, [blank] * 30, start_frame=16, t0=t)
    assert obs == []  # no removal invented while the board itself cannot be seen
    status = svc.status()
    assert not status["registration"]["valid"]
    assert svc.tracker.tracks  # the track is still there, frozen
    svc.stop()


def test_two_pieces_and_reset_session(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE, HOSPITAL]))] * 10, start_frame=6, t0=t)
    placed = by_lifecycle(obs, Lifecycle.PLACED)
    assert sorted(o.track_id for o in placed) == ["t1", "t2"]
    old_session = svc.session_id
    svc.bind_world_token("t1", "tok")
    new_session = svc.reset_session()
    assert new_session != old_session and svc.tracker.tracks == {} and svc.track_views == {}
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE, HOSPITAL]))] * 10, start_frame=16, t0=t)
    placed = by_lifecycle(obs, Lifecycle.PLACED)
    assert sorted(o.track_id for o in placed) == ["t1", "t2"]
    assert all(o.session_id == new_session for o in placed)
    assert all(o.previous_track_id is None for o in placed)
    svc.stop()


def test_candidate_pending_observations_are_emitted_before_placement(tmp_path, scene):
    board, reg, cam = scene
    cfg = fast_config(tmp_path, reg)
    cfg.tracker.stable_frames = 30
    cfg.service.candidate_emit_interval_ms = 100
    svc = PerceptionService(cfg, classifier=NullClassifier(), sinks=[])
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 12, start_frame=6, t0=t, dt=40)
    cands = by_lifecycle(obs, Lifecycle.CANDIDATE)
    assert 3 <= len(cands) <= 6
    assert by_lifecycle(obs, Lifecycle.PLACED) == []
    assert all(o.confidence_band is not ConfidenceBand.HIGH for o in cands)
    assert svc.clear_pending() == 1
    svc.stop()


def test_recording_source_replays_frames_with_recording_provenance(tmp_path, scene):
    board, reg, cam = scene
    frames_dir = write_frames_dir(tmp_path / "frames", [cam(board.empty)] * 4 + [cam(board.with_pieces([BRIDGE]))] * 10)
    source = open_source(str(frames_dir), recording_fps=200)
    assert source.is_recording
    worker = CameraWorker(source).start()
    frames = []
    deadline = time.time() + 5
    while time.time() < deadline and not worker.ended:
        f = worker.latest()
        if f is not None:
            frames.append(f)
        else:
            time.sleep(0.002)
    worker.stop()
    assert len(frames) >= 10 and frames[0].provenance.startswith("recording:")
    health = worker.health()
    assert health.frames_total == 14 and "recording:" in health.source


def test_http_sink_never_blocks_when_backend_is_down_and_reports_failures():
    sink = HttpSink("http://127.0.0.1:9/observe", timeout_s=0.2, queue_size=4)
    from perception.events import PhysicalObservation
    obs = PhysicalObservation(event_id="e", session_id="s", track_id="t", piece_class=None, lifecycle=Lifecycle.CANDIDATE,
                              board_uv=None, detection_confidence=None, localization_confidence=None,
                              confidence_band=ConfidenceBand.REJECT, observed_at_ms=1, source=ObservationSource.LIVE_CAMERA)
    t0 = time.perf_counter()
    for _ in range(50):
        sink.emit(obs)
    assert time.perf_counter() - t0 < 0.1
    time.sleep(0.6)
    st = sink.status()
    assert st["failed"] >= 1 and st["dropped"] >= 1 and st["last_error"]
    sink.close()


class _Handler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        _Handler.received.append(payload)
        body = json.dumps({"accepted": True, "world_token_id": "tok-42", "track_id": payload["track_id"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


def test_http_sink_round_trip_feeds_adapter_response_back_into_bindings(tmp_path, scene):
    board, reg, cam = scene
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/observe"
    cfg = fast_config(tmp_path, reg)
    svc = PerceptionService(cfg, classifier=RecordingClassifier(PieceClass.BRIDGE), sinks=[])
    svc.sink.add(HttpSink(url, timeout_s=1.0, on_response=lambda p, r: svc.handle_adapter_feedback({**r, "track_id": p["track_id"]})))
    obs, t = feed(svc, [cam(board.empty)] * 5)
    obs, t = feed(svc, [cam(board.with_pieces([BRIDGE]))] * 10, start_frame=6, t0=t)
    deadline = time.time() + 3
    while time.time() < deadline and not svc.tracker.tracks["t1"].bound:
        time.sleep(0.02)
    assert svc.tracker.tracks["t1"].world_token_id == "tok-42"
    assert _Handler.received and _Handler.received[0]["lifecycle"] in ("candidate", "placed")
    svc.stop()
    server.shutdown()
