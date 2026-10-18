"""Controlled observation inputs against the real reducer; not live-camera evidence."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.physical import PhysicalAdapter, inverse, load_registration, transform


@pytest.fixture
def api(monkeypatch):
    with TestClient(main.app) as client:
        # Test-only nonidentity mapping. No measured physical calibration is claimed.
        reg = {"ready": True, "print_to_world": [1, 0, .1, 0, 1, 0, 0, 0, 1]}
        adapter = PhysicalAdapter(reg)
        monkeypatch.setattr(main, "physical_adapter", adapter)
        monkeypatch.setattr(main, "perception_status", {})
        sites = {s["id"]: s for s in client.get("/scenario").json()["sites"]}
        for kind, site in [("disaster_start", "start_pad"), ("person", "people_east"), ("person", "people_west"),
                           ("shelter", "shelter_site_west"), ("hospital", "medical_site_west"), ("food_shelter", "food_site_west")]:
            result = client.post("/action", json={"action_id": uuid.uuid4().hex, "type": "place_token", "source": "manual",
                "token_type": kind, "token_id": site, "site_id": site, "board_uv": sites[site]["board_uv"],
                "expected_world_version": client.get("/world").json()["world_version"]}).json()
            assert result["accepted"], result
        client.post("/perception/status", json={"registration": {"valid": True, "registration_verified": True}})
        assert client.post("/perception/run", json={"session_id": "test-run", "state": "start"}).status_code == 200
        yield client, sites, adapter


def event(api, site="crossing_east", lifecycle="placed", **overrides):
    client, sites, adapter = api
    uv = sites[site]["board_uv"]
    return {"event_id": uuid.uuid4().hex, "session_id": "test-camera", "world_epoch": adapter.epoch,
            "track_id": "test-track-1", "piece_class": "bridge", "lifecycle": lifecycle,
            "board_uv": {"u": uv[0] - .1, "v": uv[1]}, "confidence_band": "high", "class_source": "perceptron",
            "observed_at_ms": int(time.time()*1000), "source": "recording",
            "frame_provenance": "test:controlled observation; not a real detection", **overrides}


def test_placement_move_rejected_move_correction_remove_and_route_consequences(api):
    client, sites, adapter = api
    before = client.get("/world").json()
    placed = client.post("/perception/physical", json=event(api)).json()
    assert placed["accepted"] and placed["applied"]
    token_id = placed["world_token_id"]
    connected = client.get("/world").json()
    assert connected["metrics"]["reachable_communities"] > before["metrics"]["reachable_communities"]
    assert any(r["reachable"] for r in connected["service_routes"])
    assert next(t for t in connected["tokens"] if t["id"] == token_id)["vision_source"] == "replay"
    moved = client.post("/perception/physical", json=event(api, "crossing_west", "moved")).json()
    assert moved["accepted"] and moved["world_token_id"] == token_id
    limited = client.get("/world").json()
    assert limited["metrics"]["reachable_communities"] < connected["metrics"]["reachable_communities"]
    rejected = client.post("/perception/physical", json=event(api, lifecycle="moved", board_uv={"u": .8, "v": .1})).json()
    assert not rejected["accepted"]
    assert adapter.bindings[("test-camera", "test-track-1")] == token_id
    assert client.get("/world").json() == limited
    corrected = client.post("/perception/physical", json=event(api, lifecycle="moved")).json()
    assert corrected["accepted"] and corrected["world_token_id"] == token_id
    removed = client.post("/perception/physical", json=event(api, lifecycle="removed", piece_class=None)).json()
    assert removed["accepted"] and removed["removed"]
    assert not any(t["id"] == token_id for t in client.get("/world").json()["tokens"])


def test_duplicate_observation_does_not_mutate_twice(api):
    client, _, _ = api
    payload = event(api)
    first = client.post("/perception/physical", json=payload).json()
    second = client.post("/perception/physical", json=payload).json()
    assert first["accepted"] and second["accepted"] and not second["applied"]
    assert second["world_version"] == first["world_version"]


def test_pending_and_failed_classification_never_create_routes(api):
    client, _, _ = api
    before = client.get("/world").json()
    for patch in [{"confidence_band": "review"}, {"piece_class": None}, {"lifecycle": "candidate"}]:
        result = client.post("/perception/physical", json=event(api, **patch)).json()
        assert not result["accepted"] and result["status"] == "pending"
        assert client.get("/world").json() == before


def test_rejected_placement_can_be_corrected(api):
    client, _, _ = api
    result = client.post("/perception/physical", json=event(api, board_uv={"u": .8, "v": .1})).json()
    assert not result["accepted"]
    assert client.post("/perception/physical", json=event(api)).json()["accepted"]


def test_pause_cutoff_and_reset_reject_queued_events(api):
    client, _, adapter = api
    pending = event(api)
    client.post("/perception/run", json={"session_id": "test-run", "state": "pause"})
    assert client.post("/perception/physical", json=pending).json()["rejection_reason"] == "mission_input_closed"
    client.post("/perception/run", json={"session_id": "test-run", "state": "resume"})
    assert client.post("/perception/physical", json=pending).json()["accepted"]
    final = client.post("/perception/run", json={"session_id": "test-run", "state": "close"}).json()["snapshot"]
    assert client.post("/perception/physical", json=event(api, lifecycle="removed")).json()["rejection_reason"] == "mission_input_closed"
    assert client.get("/world").json() == final
    client.post("/reset")
    assert client.post("/perception/physical", json=pending).json()["rejection_reason"] == "stale_world_epoch"
    assert adapter.bindings == {}


def test_backend_deadline_stops_input_without_frontend_close(api):
    client, _, adapter = api
    adapter.clock = lambda: adapter.opened_at + 70.01
    assert client.post("/perception/physical", json=event(api)).json()["rejection_reason"] == "mission_input_closed"


@pytest.mark.parametrize("condition,reason", [("mapping", "board_registration_required"), ("unmeasured", "camera_registration_required"), ("stale", "camera_status_stale")])
def test_real_registration_gates(api, condition, reason):
    client, _, adapter = api
    if condition == "mapping":
        adapter.registration = {"ready": False}
    elif condition == "unmeasured":
        main.perception_status["registration"]["registration_verified"] = False
    else:
        main.perception_status["received_at"] = 0
    assert client.post("/perception/physical", json=event(api)).json()["rejection_reason"] == reason


def test_websocket_carries_backend_rejection_and_accepted_snapshot(api):
    client, _, _ = api
    with client.websocket_connect("/ws") as ws:
        ws.receive_json(); ws.receive_json()
        result = client.post("/perception/physical", json=event(api)).json()
        feedback = ws.receive_json()
        snapshot = ws.receive_json()
        assert feedback["payload"]["physical_feedback"]["world_token_id"] == result["world_token_id"]
        assert snapshot["type"] == "world.snapshot" and snapshot["payload"]["world_version"] == result["world_version"]


def test_homography_roundtrip_and_unmeasured_repository_stays_locked():
    m = [1.1, .1, -.05, .03, .8, .1, .02, -.04, 1]
    assert transform(inverse(m), transform(m, [.32, .67])) == pytest.approx([.32, .67])
    reg = load_registration(main.REPO_ROOT / "perception/board_mapping.json", main.REPO_ROOT / "perception/board_registration.json", "nepal_rasuwa_hot_v1")
    assert not reg["ready"]


def test_mapping_fitter_checks_independent_measured_landmarks():
    from scripts.register_print_world import fit
    matrix = [1.1, .03, -.04, -.02, .85, .05, .02, .01, 1]
    positions = [[.1,.1],[.9,.1],[.9,.9],[.1,.9],[.3,.4],[.7,.6]]
    points = [{"label": f"TEST landmark {i}", "print_uv": p, "world_uv": transform(matrix, p)} for i,p in enumerate(positions)]
    fitted, quality = fit(points)
    assert fitted == pytest.approx(matrix) and quality["max_error_uv"] < 1e-10
    points[-1]["world_uv"][0] += .1
    with pytest.raises(ValueError, match="Validation error"):
        fit(points)


def test_measured_camera_footprints_mask_pieces_without_claiming_placement(api):
    client, _, adapter = api
    adapter.registration["board"] = {"width_mm": 600, "height_mm": 400}
    before = client.get("/world").json()
    result = client.post("/perception/physical", json=event(api, lifecycle="candidate", confidence_band="review",
        geometry={"bbox_mm": [70, 40]}, orientation_deg=90)).json()
    assert result["status"] == "pending" and len(result["print_footprint"]) == 4
    assert len(client.get("/projection/registration").json()["occlusions"]) == 1
    assert client.get("/world").json() == before
    client.post("/perception/physical", json=event(api, lifecycle="lost", confidence_band="review"))
    assert client.get("/projection/registration").json()["occlusions"] == {}
