# Integration contract

Verified against `backend/main.py`, `backend/contracts.py`, `backend/world/geometry.py` and the live HOT world on 2026-10-18. Python contracts are authoritative; UI mirrors live in `apps/game/src/types/`.

| Endpoint | Current behavior |
| --- | --- |
| `GET /health` | `status`, `world_version`, `vision_mode`, `perceptron_status`, `gemini_status`. Camera readiness is not implied by a healthy world |
| `GET /scenario` | Static UV geometry: `scenario_id`, `data_label`, `aspect_ratio`, `board`, `roads`, `sites`, `rivers`, `labels`, `hazard_zones`, `flood_corridors`, `stage_count`, hazard provenance |
| `GET /world` | Schema 2 authoritative snapshot |
| `POST /action` | Apply a versioned `WorldAction`; returns `accepted`, `action_id`, `world_version`, `rejection_reason`. Accepted actions broadcast a snapshot |
| `POST /reset` | Empty JSON body. Gateway obtains current version under its lock; returns `reset`, `world_version`, and broadcasts on acceptance |
| `POST /plan/suggest` | Body `{"goal_id":"needs_served"}`. Returns `has_suggestion`, `suggestion`, `world_version`, `rejection_reason`. The accepted ghost is also in the next snapshot |
| `WS /ws` | JSON envelopes `server.hello`, `world.snapshot`, `vision.status`, `warning`, narration. `ping` receives plain text `pong` |
| `GET/POST /perception/status` | Status dictionary owned/reported by the separate perception service; the UI polls every 2 seconds |
| `POST /perception/observe` | Current observation adapter broadcasts every observation and converts confirmed observations to `place_token` only |

An actual manual bridge request has this shape. Read the current `world_version` immediately before sending; do not copy the example version into a running game.

```json
{
  "action_id": "operator-generated-unique-id",
  "type": "place_token",
  "source": "manual",
  "token_type": "bridge",
  "token_id": "operator-generated-piece-id",
  "site_id": "crossing_east",
  "board_uv": [0.50042078, 0.440123655],
  "expected_world_version": 4,
  "timestamp_utc": "2026-10-18T00:00:00Z"
}
```

`move_token` uses the accepted `token_id`, destination `site_id` and `board_uv`; `remove_token` uses the accepted `token_id`; `advance_stage` needs no token. Backend sources are `manual`, `physical_perceptron`, `physical_local_cv`, `replay`. UI logs additionally distinguish `operator_manual`, `game_setup`, `game_clock`; these are local provenance labels, not new backend source values. Placed tokens report `vision_source` as `manual`, `perceptron`, `local_cv` or `replay`.

The UI retries a `stale_version` rejection once after reading `/world`, preserving the action ID. Accepted IDs cannot mutate twice; duplicate accepted IDs are rejected as `duplicate`, rather than replaying the original acknowledgment. Other rejections are displayed without changing state. Network errors are not treated as acceptance.

Snapshot inputs used by the UI:

- `scenario_id`, `branch_id`, `world_version`, `phase`, `simulation_stage`, `schema_version` identify state. A new socket can recover a restarted server with a lower version; older deliveries within the same connection are discarded.
- `tokens`, `token_inventory`, `budget_remaining_model`, `facilities` define accepted pieces and capacity. Facility position comes from its token or real site; an unpositioned facility is omitted from the map.
- `edges[].blocked` supplies closures. `service_routes[].reachable`, `edge_ids`, `board_uv`, `population_id`, `facility_id`, `service` supply actual routes. React does not route.
- `population_demand[].people_model`, `need_food/medical/refuge`, optional `unmet_*`, `headcount_known`, `depot_reachable` supply population cues. Depot access is distinct from service capacity.
- `metrics` supplies reachable populations and capacity-bounded unmet needs. `game` supplies score, objectives, baseline comparison and unresolved outcomes. Missing score/baseline fields are omitted; no fictional rescue total is displayed.
- `sites[].edge_id`, `resource_cost`, `capacity_model` and `population_demand[].depot_reachable` are the additive fields from `1a1406f`, pending shared review. Pad highlights are hints based on available snapshot fields; the backend also enforces approval, exposure, supply and all other rules.

Digital START explicitly performs `/reset`, places `disaster_start` at `start_pad`, then places each existing population node as a `person` input. All must be acknowledged before the mission clock starts. There is no person-piece requirement. A failed partial setup keeps the clock idle and asks the operator to reset/retry.

Clock boundaries are 10/30/50/70/75 seconds of monotonic elapsed time. Pausing suspends scheduled events, while manual corrections remain available. The timed surge uses a stable `surge-<session_id>` action ID plus a per-run dispatch guard. Only an accepted backend snapshot changes flooding. Current stage 1 is already the final stage, so the timed advance returns `last_stage`.

At 70 seconds, UI placement/move/remove input closes. Results remain visibly `SYNCING` while a UI action is in flight, an acknowledged version has not arrived, the world socket is unhealthy, or the projector loses the operator clock. Results use the latest confirmed snapshot. This is a frontend barrier; there is no server-side timed input lock for camera events. Coordinated physical finalization belongs in shared integration.

Both windows use real WebSockets for world state. Same-origin `BroadcastChannel("floodshift.game.v1")` carries only clock/sync state, projector commands/health, pending-clear and short operator rejection cues. It is not cross-device synchronization. The projector extrapolates a fresh clock locally, then freezes after 3 seconds without an operator heartbeat and shows a connection warning. It does not rewind a stale countdown.

Lane B from `origin/main` at `cc38a00` is now merged. Its status uses nested `camera` (`connected`, `source`, `fps_measured`, `last_frame_age_ms`), `registration` (`valid`, `held`, `degraded`, `registration_verified`, `markers_used`, RMS fields), and `classifier` (`kind`, `available`). The UI consumes these fields and remains compatible with the gateway's legacy strings. A valid photo-estimated homography is labelled VALID · UNMEASURED, not CALIBRATED; held/degraded registration also stays a warning. An available local classifier is not labelled Perceptron.

The camera-to-world integration remains incomplete. The retained gateway's `ObjectObservation` includes `event_id`, `frame_id`, `token_id`, `object_type`, `class_source`, `board_uv`, `vision_status`, optional box, rotation, stability, provenance and latency. It has no confidence or placed/moved/lifted lifecycle field, and `/perception/observe` converts confirmed observations only to placement. The incoming `perception/events.py` instead emits `PhysicalObservation` with `session_id`, `track_id`, `piece_class`, lifecycle, confidence band and print-frame `{u,v}` coordinates. **Do not point its raw HTTP sink directly at the legacy `/perception/observe` endpoint.**

The shared adapter still needs to transform print UV into world UV using reviewed print bounds, map `food_station` to `food_shelter`, distinguish camera tracks from accepted world token IDs, translate placed/moved/removed actions, return binding/rejection feedback, and gate on measured registration and confidence. No transform, class result or successful physical action is invented by this merge. The UI opens reported camera-calibration status because no camera-calibration control endpoint exists; the actual Lane B calibration CLI is documented in BOARD_REGISTRATION.

The marker source is now `perception/board_registration.json`: photo-verified TL 10, TR 11, BR 13, BL 12, with unmeasured centres and paper size. Its print frame differs from the square world extent. Physical projection and reticles are held at BOARD REGISTRATION REQUIRED until a measured mapping is implemented; screen rehearsal remains available through M / `?mode=screen`. A saved projector pixel adjustment does not set alignment verified or claim CALIBRATED.

`CLEAR PENDING DETECTION` clears UI candidate outlines only. Reset clears world state and UI caches; neither operation clears the external perception service's track mapping. That mapping must be reset by its owner. No camera readiness or confidence is fabricated.
