from __future__ import annotations

import json

import pytest

from perception.config import PerceptionConfig
from perception.events import (
    Appearance,
    BoardUV,
    ConfidenceBand,
    GeometryQuality,
    Lifecycle,
    ObservationSource,
    PhysicalObservation,
    PieceClass,
    make_event_id,
)


def _geometry() -> GeometryQuality:
    return GeometryQuality(markers_used=4, reprojection_rms_uv=0.002, reprojection_rms_px=1.1, registration_age_ms=30,
                           registration_held=False, position_jitter_uv=0.001, frames_observed=20, frames_stable=12,
                           area_mm2=2700.0, bbox_mm=(70.0, 40.0), elongation=1.75, touches_board_edge=False,
                           parallax_correction_mm=2.1, assumed_height_mm=13.0, camera_pose_approximate=True)


def test_event_id_is_deterministic_and_distinct_per_emission():
    a = make_event_id("s1", "t1", Lifecycle.PLACED, 1)
    b = make_event_id("s1", "t1", Lifecycle.PLACED, 1)
    c = make_event_id("s1", "t1", Lifecycle.PLACED, 2)
    d = make_event_id("s1", "t1", Lifecycle.MOVED, 1)
    e = make_event_id("s2", "t1", Lifecycle.PLACED, 1)
    assert a == b
    assert len({a, c, d, e}) == 4


def test_observation_round_trips_through_json():
    obs = PhysicalObservation(
        event_id="obs-t1-placed-1-abc", session_id="s", track_id="t1", piece_class=PieceClass.BRIDGE,
        lifecycle=Lifecycle.PLACED, board_uv=BoardUV(0.41, 0.52), detection_confidence=0.9,
        localization_confidence=0.8, confidence_band=ConfidenceBand.HIGH, observed_at_ms=1234,
        source=ObservationSource.RECORDING, orientation_deg=12.5, class_source="perceptron", class_confidence=0.9,
        frame_id=7, camera_px=(640.0, 360.0), previous_track_id=None, geometry=_geometry(),
        appearance=Appearance((27.0, 180.0, 200.0), 0.9, 0.0), frame_provenance="recording:x#7", reason="ok")
    data = json.loads(obs.to_json())
    assert data["piece_class"] == "bridge"
    assert data["source"] == "recording"
    assert data["board_uv"] == {"u": 0.41, "v": 0.52}
    back = PhysicalObservation.from_dict(data)
    assert back == obs


def test_unclassified_observation_serialises_null_class_not_a_guess():
    obs = PhysicalObservation(event_id="e", session_id="s", track_id="t2", piece_class=None, lifecycle=Lifecycle.CANDIDATE,
                              board_uv=None, detection_confidence=None, localization_confidence=None,
                              confidence_band=ConfidenceBand.REJECT, observed_at_ms=1, source=ObservationSource.LIVE_CAMERA)
    data = obs.as_dict()
    assert data["piece_class"] is None and data["board_uv"] is None and data["detection_confidence"] is None
    assert PhysicalObservation.from_dict(data).confidence_band is ConfidenceBand.REJECT


def test_config_env_and_file_overrides(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"tracker": {"stable_frames": 5}, "candidates": {"structure_gate": True}}))
    cfg = PerceptionConfig.load(path, env={"FLOODSHIFT_PERCEPTION_CAMERA_SOURCE": "3",
                                           "FLOODSHIFT_PERCEPTION_BOARD_MIN_MARKERS": "3",
                                           "FLOODSHIFT_PERCEPTION_CANDIDATES_SHADOW_SUPPRESSION": "false"})
    assert cfg.tracker.stable_frames == 5
    assert cfg.candidates.structure_gate is True
    assert cfg.camera.source == "3"
    assert cfg.board.min_markers == 3
    assert cfg.candidates.shadow_suppression is False


def test_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"tracker": {"not_a_key": 1}}))
    with pytest.raises(ValueError):
        PerceptionConfig.load(path, env={})
