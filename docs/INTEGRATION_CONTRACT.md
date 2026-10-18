# Integration contract

The retained `WorldService` remains authoritative for placement rules, inventory, graph routes, capacity, flood stages, score and snapshots. The physical adapter translates observations; it does not compute gameplay consequences. Scenario data and the world/simulation/planning implementation are unchanged.

| Endpoint | Behavior |
| --- | --- |
| `GET /scenario`, `GET /world` | Existing scenario geometry and schema-2 accepted world snapshot |
| `POST /action`, `POST /reset` | Existing versioned actions and authoritative reset; accepted changes broadcast snapshots |
| `POST /plan/suggest` | Existing real ghost suggestion; no scripted recommendation |
| `GET /projection/registration` | Validated measured print/world mapping, its inverse, print dimensions and marker metadata; `ready:false` until measurements exist |
| `POST /perception/physical` | New `PhysicalEvent` input matching camera lifecycle fields, plus `world_epoch`; returns acceptance/binding/rejection feedback |
| `POST /perception/run` | `{session_id,state}` where state is `start`, `pause`, `resume` or `close`; close returns the final authoritative snapshot |
| `GET/POST /perception/status` | Camera service telemetry; responses include backend-owned `integration` with epoch, run, input gate and alignment readiness |
| `POST /perception/observe` | Retained legacy `ObjectObservation` placement interface; the new service uses `/perception/physical` |
| `WS /ws` | Existing `world.snapshot`, `vision.status`, warning and narration envelopes |

`backend/physical.py` validates the camera payload without importing OpenCV into the server. The input retains `event_id`, `session_id`, `track_id`, `piece_class`, lifecycle, print-frame `{u,v}`, confidence band, reported confidence, timestamp, class source, live/recorded provenance and backend epoch. The service obtains the epoch from status responses; it never guesses it.

Measured mapping converts print UV into world UV. `food_station` maps to the retained `food_shelter` token type. The server reads the current world version and calls the existing reducer under its mutation lock. Recording input uses `replay` provenance; live Perceptron input uses `physical_perceptron`. Pending or unverified observations cannot mutate the world.

Feedback includes `accepted`, `applied`, `world_token_id`, `removed`, `rejection_reason`, `world_version`, world `board_uv`, track/session/event IDs and epoch. Accepted event IDs are idempotent for the bounded retry cache; they do not mutate twice. Accepted order is also tracked by timestamp. A rejected move retains its binding and previous accepted location; subsequent correction can retry with a fresh event. A class change cannot silently convert an accepted piece into a different resource.

`vision.status.payload.physical_feedback` carries this response to both UI windows. Pending feedback creates only an outline; a rejection creates a localized reason cue. Accepted halos, routes, populations and facility consequences still come from diffs of `world.snapshot`, never from an acknowledgment alone. Camera feedback is applied on the camera processing thread. Reset changes the backend epoch, clears bindings and causes the service to reset its tracks after status acknowledgment. Old queued events are rejected.

Physical input requires measured mapping, fresh verified camera registration, no held/degraded registration, a HIGH observation band, valid coordinates, a fresh observation and an open backend run. A changed detector session requires reset. Backend monotonic time closes input after 70 mission seconds; pause banks elapsed time. UI actions also close at 70 seconds. Finalization closes the physical gate and captures the snapshot under the same mutation lock. Results remain SYNCING until finalization succeeds; the exact snapshot is shared with the projector and used in run exports.

Digital START resets the world, places the scenario's actual START input and both real population records, then opens the backend run and starts the 75-second narrative clock. The UI sends the one-time 50-second surge with a stable action ID. The HOT bundle now has a second, illustrative stage (`hazard.json` `stages[2]`, built by `scripts/geodata/build_hot_scenario.py`) that also closes the hillside road between the refuge and field-care pads; if a bundle has no further stage the request is rejected with `last_stage` and the projector shows FLOOD UPDATE UNAVAILABLE.

Every snapshot carries `mission` (backend/world/mission.py), a pure function of state: the isolated villages, each village's lifeline to the depot, the crossing chosen by the existing ghost planner (`best_suggestion(..., 'access')`), reducer previews of each service site, the best remaining placement, and `baseline` (the same stage with no response pieces, for the final before/after reveal). The UI highlights only these previews; it never decides success. Matsya's Guidance is the existing `ghost_suggestion` (`/plan/suggest` with `goal_id: "access"`).

OpenCV retains the existing single tracker, candidate detector and ArUco registration. `perception.fusion:create_classifier` now implements its `submit/poll/status/close` port instead of maintaining a second tracker. It uses the official SDK with a request timeout and bounded worker queue. Missing confidence stays `None`; three agreeing distinct-frame classifications can support local consensus without inventing a model probability. Missing/failed/ambiguous classifications stay pending. There is no automatic color substitution in the game classifier path.

`perception/board_mapping.json` is deliberately UNMEASURED. The loader also requires measured marker registration and matching scenario identity. `scripts/register_print_world.py` fits real landmark pairs and checks independent held-out pairs. The same server mapping is used by the physical adapter and inverse projector transform. Marker keep-outs remain in print space and draw last; pixel keystone follows the map transform. See [physical setup](PHYSICAL_INTEGRATION.md).

Both windows read real WebSocket state. Same-origin `BroadcastChannel("floodshift.game.v1")` carries clock/sync/final-state, projector commands/health, pending-clear and short manual rejection cues. It is same-browser only. One operator window owns the clock; O toggles tools without remounting it. A page reload loses the local clock. Projector extrapolation stops after three seconds without a heartbeat and shows a warning.

The source map is HOT/OSM geometry. No Mapbox configuration exists in this checkout; no replacement geography is invented. Hardware still needs actual marker/paper measurements, landmark registration, projector-on classification tests and a reviewed second flood stage. Software tests use labelled controlled inputs and do not claim a physical demo.
