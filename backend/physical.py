"""Physical lifecycle adapter. Routing, budgets and acceptance stay in WorldService."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, Field


class PhysicalEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    track_id: str = Field(min_length=1, max_length=200)
    world_epoch: str | None = None
    piece_class: Literal["bridge", "hospital", "shelter", "food_station"] | None = None
    lifecycle: Literal["candidate", "placed", "moved", "removed", "lost"]
    board_uv: dict[str, float] | None = None
    confidence_band: Literal["high", "review", "reject"]
    detection_confidence: float | None = None
    localization_confidence: float | None = None
    class_source: str | None = None
    observed_at_ms: int
    source: Literal["live_camera", "recording"]
    previous_track_id: str | None = None
    frame_provenance: str | None = None
    geometry: dict | None = None
    orientation_deg: float | None = Field(default=None, allow_inf_nan=False)


class RunCommand(BaseModel):
    session_id: str
    state: Literal["start", "pause", "resume", "close"]


def transform(matrix, uv):
    u, v = uv
    w = matrix[6] * u + matrix[7] * v + matrix[8]
    if not math.isfinite(w) or abs(w) < 1e-10:
        raise ValueError("invalid mapping")
    out = [(matrix[0] * u + matrix[1] * v + matrix[2]) / w,
           (matrix[3] * u + matrix[4] * v + matrix[5]) / w]
    if not all(math.isfinite(n) for n in out):
        raise ValueError("invalid mapping")
    return out


def inverse(m):
    a, b, c, d, e, f, g, h, i = m
    adj = [e*i-f*h, c*h-b*i, b*f-c*e, f*g-d*i, a*i-c*g, c*d-a*f,
           d*h-e*g, b*g-a*h, a*e-b*d]
    det = a*adj[0] + b*adj[3] + c*adj[6]
    if abs(det) < 1e-10:
        raise ValueError("singular print/world mapping")
    return [n / det for n in adj]


def load_registration(mapping_path: Path, markers_path: Path, scenario_id: str):
    """A measured matrix is supplied by hardware calibration, never inferred here."""
    result = {"ready": False, "reason": "BOARD REGISTRATION REQUIRED", "scenario_id": scenario_id}
    try:
        markers = json.loads(markers_path.read_text(encoding="utf-8"))
        result.update(board=markers["board"], markers=markers["markers"], marker_size_mm=markers["aruco"]["marker_size_mm"])
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        if mapping.get("status") != "MEASURED" or mapping.get("scenario_id") != scenario_id:
            return result
        if markers.get("status") != "MEASURED" or not all(m.get("verified") for m in markers["markers"]):
            return result
        if markers["board"].get("scenario_id") != scenario_id or not markers["aruco"].get("marker_size_mm"):
            return result
        if any(not math.isfinite(float(markers["board"][k])) or markers["board"][k] <= 0 for k in ("width_mm", "height_mm")):
            return result
        if len(markers["markers"]) != 4 or len({m["id"] for m in markers["markers"]}) != 4:
            return result
        if any(len(m["center_uv"]) != 2 or not all(math.isfinite(n) and 0 <= n <= 1 for n in m["center_uv"]) for m in markers["markers"]):
            return result
        if not mapping.get("measured_by") or not mapping.get("measured_on") or not mapping.get("source"):
            return result
        matrix = [float(n) for n in mapping["print_to_world"]]
        if len(matrix) != 9 or not all(math.isfinite(n) for n in matrix):
            return result
        inv = inverse(matrix)
        # No projective horizon may cross the board.
        corners = [(0, 0), (1, 0), (1, 1), (0, 1)]
        weights = [matrix[6]*u + matrix[7]*v + matrix[8] for u, v in corners]
        if min(weights) <= 0 <= max(weights):
            return result
        result.update(ready=True, reason=None, print_to_world=matrix, world_to_print=inv,
                      measurement={k: mapping[k] for k in ("measured_by", "measured_on", "source")})
    except (OSError, KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    return result


class PhysicalAdapter:
    def __init__(self, registration, clock=time.monotonic):
        self.registration = registration
        self.clock = clock
        self.reset()

    def reset(self):
        import uuid
        self.epoch = uuid.uuid4().hex
        self.run_id = None
        self.state = "closed"
        self.banked = 0.0
        self.opened_at = None
        self.detector_session = None
        self.bindings = {}
        self.occlusions = {}
        self.last_time = {}
        self.last_pose_time = {}
        self.accepted = OrderedDict()

    def elapsed(self):
        return self.banked + (self.clock() - self.opened_at if self.opened_at is not None else 0)

    def is_open(self):
        return self.state == "running" and self.elapsed() < 70

    def control(self, command):
        if command.state == "start":
            if self.run_id and self.run_id != command.session_id:
                raise ValueError("reset_required")
            if self.run_id is None:
                self.run_id = command.session_id
                self.state, self.opened_at = "running", self.clock()
        elif command.session_id != self.run_id:
            raise ValueError("wrong_run")
        elif command.state == "close":
            self.banked, self.opened_at, self.state = self.elapsed(), None, "closed"
        elif command.state == "pause" and self.is_open():
            self.banked, self.opened_at, self.state = self.elapsed(), None, "paused"
        elif command.state == "resume" and self.state == "paused" and self.elapsed() < 70:
            self.state, self.opened_at = "running", self.clock()
        return self.status()

    def status(self):
        return {"world_epoch": self.epoch, "run_id": self.run_id, "state": self.state,
                "input_open": self.is_open(), "elapsed_seconds": self.elapsed(),
                "alignment_ready": self.registration.get("ready", False)}

    def observe(self, event: PhysicalEvent, world, telemetry):
        snapshot = world.snapshot()
        key = (event.session_id, event.track_id)
        result = {"track_id": event.track_id, "session_id": event.session_id, "event_id": event.event_id,
                  "world_epoch": self.epoch, "accepted": False, "applied": False,
                  "removed": False, "world_token_id": self.bindings.get(key),
                  "world_version": snapshot["world_version"], "board_uv": None,
                  "piece_class": event.piece_class, "status": "rejected", "rejection_reason": None}

        def reject(reason, pending=False):
            result.update(rejection_reason=reason, status="pending" if pending else "rejected")
            return result

        if event.world_epoch != self.epoch:
            return reject("stale_world_epoch")
        cache_key = (event.session_id, event.event_id)
        if cache_key in self.accepted:
            return {**self.accepted[cache_key], "applied": False}
        if not self.registration.get("ready"):
            return reject("board_registration_required")
        if event.board_uv is not None:
            try:
                result["board_uv"] = transform(self.registration["print_to_world"],
                                                [event.board_uv["u"], event.board_uv["v"]])
            except (ValueError, KeyError):
                return reject("invalid_position")
        if abs(time.time() * 1000 - event.observed_at_ms) > 5000 or event.observed_at_ms < self.last_pose_time.get(key, -1):
            return reject("stale_observation")
        self.last_pose_time[key] = event.observed_at_ms
        # Camera-measured piece footprints are optical keep-outs, not world actions.
        footprint_key = f"{event.session_id}:{event.track_id}"
        result.update(footprint_key=footprint_key)
        if event.lifecycle in ("removed", "lost"):
            self.occlusions.pop(footprint_key, None)
            result["print_footprint"] = []
        elif event.geometry and event.board_uv and self.registration.get("board"):
            bbox = event.geometry.get("bbox_mm")
            board = self.registration["board"]
            if bbox and len(bbox) == 2 and all(isinstance(n, (int,float)) and math.isfinite(n) and 0 < n < max(board["width_mm"], board["height_mm"]) for n in bbox):
                angle = math.radians(event.orientation_deg or 0)
                u, v = event.board_uv["u"], event.board_uv["v"]
                polygon = [[u+(x*math.cos(angle)-y*math.sin(angle))/board["width_mm"],
                            v+(x*math.sin(angle)+y*math.cos(angle))/board["height_mm"]]
                           for x,y in [(-bbox[0]/2-6,-bbox[1]/2-6),(bbox[0]/2+6,-bbox[1]/2-6),
                                       (bbox[0]/2+6,bbox[1]/2+6),(-bbox[0]/2-6,bbox[1]/2+6)]]
                if all(math.isfinite(n) for p in polygon for n in p):
                    self.occlusions[footprint_key] = polygon
                    result["print_footprint"] = polygon
        if not self.is_open():
            return reject("mission_input_closed")
        reg = telemetry.get("registration") or {}
        if time.time() - telemetry.get("received_at", 0) > 3:
            return reject("camera_status_stale")
        if not isinstance(reg, dict) or reg.get("valid") is not True or reg.get("registration_verified") is not True or reg.get("held") or reg.get("degraded"):
            return reject("camera_registration_required")
        # Held telemetry cannot authorize old queued observations indefinitely.
        if self.detector_session and self.detector_session != event.session_id:
            return reject("detector_session_changed_reset_required")
        if event.observed_at_ms < self.last_time.get(key, -1):
            return reject("stale_observation")
        if event.lifecycle in ("candidate", "lost") or event.confidence_band != "high":
            return reject("detection_pending" if event.lifecycle != "lost" else "track_lost", pending=True)
        if result["board_uv"] is None or not all(0 <= n <= 1 for n in result["board_uv"]):
            return reject("outside_board")
        token_id = self.bindings.get(key)
        token = next((t for t in snapshot["tokens"] if t["id"] == token_id), None)
        if token is None:
            self.bindings.pop(key, None)
        source = "replay" if event.source == "recording" else "physical_perceptron" if event.class_source == "perceptron" else "physical_local_cv"
        if event.lifecycle == "removed":
            if token is None:
                result.update(accepted=True, removed=True, status="removed", world_token_id=None)
                return result
            kind = "remove_token"
            piece = token["type"]
        else:
            if not event.piece_class or event.class_source not in ("perceptron", "local_cv", "color_fallback"):
                return reject("class_not_verified", pending=True)
            piece = "food_shelter" if event.piece_class == "food_station" else event.piece_class
            if token is not None and token["type"] != piece:
                return reject("piece_class_changed_remove_first")
            kind = "move_token" if token is not None else "place_token"
            if token is None:
                token_id = "physical-" + hashlib.sha256(f"{self.epoch}:{key}".encode()).hexdigest()[:20]
        action = {"action_id": "physical-" + hashlib.sha256(f"{self.epoch}:{cache_key}".encode()).hexdigest(),
                  "type": kind, "source": source, "token_type": piece, "token_id": token_id,
                  "board_uv": result["board_uv"], "expected_world_version": snapshot["world_version"]}
        applied = world.apply(action)
        result.update(accepted=applied["accepted"], applied=applied["accepted"], world_version=applied["world_version"],
                      rejection_reason=applied.get("reason"), action_id=action["action_id"])
        if applied["accepted"]:
            self.detector_session = event.session_id
            self.last_time[key] = event.observed_at_ms
            result.update(world_token_id=token_id, status="removed" if kind == "remove_token" else "accepted", removed=kind == "remove_token")
            if kind == "remove_token":
                self.bindings.pop(key, None)
            else:
                self.bindings[key] = token_id
            self.accepted[cache_key] = dict(result)
            if len(self.accepted) > 4096:
                self.accepted.popitem(last=False)
        return result
