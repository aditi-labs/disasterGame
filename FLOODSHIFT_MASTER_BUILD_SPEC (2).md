# FLOODSHIFT — MASTER BUILD SPEC

**Version:** 1.0 — fresh-repository handoff  
**Date:** 2026-10-18  
**Mode:** 75-second live physical-AI disaster-response game  
**Location:** Shyaphru Bensi, Rasuwa, Nepal  
**Primary track:** DubHacks Chef's Choice  
**Original source repo (reference):** https://github.com/aditi-labs/floodshift-  
**Status:** Implementation plan, **not** a claim that the new repository, projector, Perceptron SDK integration, or hardware have been validated.

> **Critical corrections / locked decisions**
>
> 1. **The real map data and database already exist in the current repository.** Import and preserve them. Do not invent replacement graph nodes, population records, flood shapes, service capacities, coordinates, or results.
> 2. **The current Mapbox map is the canonical visual map.** Reuse its styling, projection/bounds, and geospatial references; don't redraw a pretend town or migrate to another map provider.
> 3. **ArUco markers are already physically present on the map.** Reuse and validate their measured IDs/locations; do not make printing new markers a prerequisite. The earlier audit had said a particular exported `map_print.svg` lacked markers, but the current physical-board status takes precedence; inspect the actual board and camera feed.
> 4. **Fresh repository / fresh OpenCV + Perceptron code.** Rebuild physical observation, detection, and tracking as a clean isolated component. Reuse the existing authoritative world simulation, rules, graph, environmental changes, score, and projection logic where valuable.
> 5. **No synthetic demo world or fake successes.** Every gameplay state, geometry, route, hazard, capacity, and metric comes from the existing real dataset/database and the live backend. Real camera/video recordings of the actual hardware may be used as reproducible input for tests, clearly identified as recordings.
> 6. **Three concurrent lanes:** (A) game/projector UI owned by Sky; (B) OpenCV calibration + tracking owned by Detection Dev 1; (C) Perceptron classification + confidence/fusion owned by Detection Dev 2. Existing backend/world code is a **shared retained foundation**, not a fourth competing implementation.
> 7. **75 seconds refers to interactive gameplay, not the entire presentation.** Prologue/pitch can happen separately. A missed detection must not freeze story progression.

---

## 0. North star and grading priorities

**Player promise:** A community is threatened by a flood. In 75 seconds, the player places physical emergency infrastructure on a real mapped Himalayan settlement; the projected map responds with actual accessibility, service, and flood consequences from the existing simulation.

**The signature judge moment:** a printed physical bridge is placed at a valid crossing → overhead camera produces a *confirmed physical observation* → existing backend validates a bridge action → NetworkX-based reachability recomputes → projector lights up a genuinely restored route → population/service-access indicators and score update from the returned live snapshot.

**Chef's Choice grading lens (provided earlier by team):**

| Criterion | Weight | What this build must prove |
|---|---:|---|
| Functionality / execution | 30% | Camera-to-action-to-backend-to-projector succeeds repeatedly; reset/reposition/rejections behave correctly; no fake output |
| Track applicability | 30% | Clear integrated physical-AI and culturally framed end-to-end experience; directly demonstrate whatever current Chef's Choice track definition requires |
| Design / UX | 20% | Polished, readable, projection-safe atmosphere; immediate action feedback; understandable without tutorial |
| Creativity | 20% | Physical map + real flood/routing + unfolding Manu–Matsya-inspired narrative, with consequences instead of a passive dashboard |

Do not trade a working bridge-to-map reaction for decorative extras. Track interpretation must be cross-checked with current official event guidance before submission.

### Story and cultural framing

**Mythic framing:** Manu and Matsya carry the themes of warning, rescue, responsibility, and safeguarding life through a great flood. Use the team's existing dark, limited-glow, landscape storyboard as an optional **separate prologue** (the previously defined five beats: fish asks Manu for help; Manu cares for growing fish; Manu builds the boat; Manu, family, Vedas and seven sages on the boat tied to the fish amid waves; safe descent/revelation). It is not a factual account of the modern Nepal scenario.

**Game transition:** "The flood was once a story of survival. Today, the choices are yours." Cut/fade into the actual **Mapbox map of Shyaphru Bensi**. The modern hazard scenario is represented as a simulation informed by existing real geospatial/flood/population inputs, not a claim that a specific historic flood is happening live.

**Don't add a 30-second cinematic inside the 75-second game.** If the prologue is included, play it *before* the game clock starts, controlled by the operator. In-game copy should be small and crisp. Matsya may appear as a subtle fish/horn motif or guiding pulse, not a character animation occupying the map.

---

## 1. Split of ownership and boundaries

| Lane | Owner | Owns | Explicitly does NOT own | Deliverable |
|---|---|---|---|---|
| **A — Player game / operator / projection UI** | **Sky** | 75-second phase clock, narrative, Mapbox/physical overlay, map cues, citizen visualizations, buttons, HUD, results, projector calibration UX, snapshot adapter, manual correction UX | Camera frame capture, ML classifications, centroid tracking, authoritative routing/score | Running `/projector` + `/operator`, cinematic 75-sec interactive experience using real snapshots |
| **B — OpenCV camera, ArUco, tracking** | **Detection Dev 1** | Camera ingest, undistortion as needed, ArUco read/board transform, object candidate ROIs, physical object track IDs, enter/move/leave state machine, confidence of geometry, debouncing | Mapbox UI, flood logic, service access, Perceptron SDK implementation | Stable live observations aligned to board UV, move/remove/reposition with reproducible camera tests |
| **C — Perceptron recognition + fusion** | **Detection Dev 2** | SDK verification, image crop/object classification, per-class scores if available, class fusion and rejection, latency controls, confidence tiers, integration with lane B track IDs | World rules, graph routes, projector rendering, full-frame synchronous inference | Correct labels for bridge/shelter/hospital/food with calibrated confidence, fallback/status telemetry |
| **Shared retained foundation** | **Existing backend (integrated, coordinated ownership)** | WorldService, scenario database, rules, inventory, budgets, graph edges/nodes, flood geography/stages, capacity/reachability, bridge ghost suggestion, scoring, authoritative actions and snapshots | Detecting physical pixels or projecting speculative visual results | One source of truth; bridge/place/move/remove actions accepted/rejected deterministically |

**File ownership rule:** UI developer owns `apps/game/**` and UI adapter types; detection devs own their subpackages and tests. Edits to retained `backend/world/**`, `simulation/**`, `planning/**`, and public contracts must be reviewed together before merging. Do not repeat previous cross-lane edits without integration sign-off.

### Separate the two kinds of “tracking”

- **Physical tracking (new):** camera finds a printed token across frames and assigns persistent track ID, class, confidence, board pose; reports placed/moved/lifted.
- **World entity tracking (retained):** existing game state records each accepted piece/token, location, budget and impacts. `move_token`/`remove_token` must modify this authoritative state. Camera never directly edits graph nodes or paints routes.

This separation prevents the old board/world drift bug.

---

## 2. What stays, what moves, what fades

### Retain/reuse from the current repository

| Current evidence from supplied review | Treatment in new repo | Verification needed |
|---|---|---|
| Real HOT/OSM scenario bundle `nepal_rasuwa_hot_v1` + associated existing database | **Copy/link without fabricated replacements**, use as default single game scenario | Confirm exact paths, schema, contents, license and seeded DB state |
| Mapbox map/assets/config (confirmed by team) | **Retain** as canonical map; copy style/token env setup, layers and bounds | Inspect actual Mapbox usage and map-to-board alignment |
| Physical map with existing ArUco tags (confirmed by team) | **Retain**; detect real printed marker IDs | Verify dictionary, IDs, orientation, corners and occlusion tolerance live |
| `backend/world/rules.py` | **Retain**; scenario action validity and rejection reasons | Start-first rule must be reconciled with digital START, not bypassed silently |
| `reachability.measure()` / NetworkX routes, service capacities, unmet needs | **Retain**; source of projected service-route states | Confirm exact returned path geometry and coordinate frame |
| `planning/ghost_bridge.py` | **Retain**, optional assist/hint | Ensure selected bridge zone genuinely improves objective |
| `WorldService`, `/action`, `/world`, `/scenario`, `/reset`, `/ws` | **Retain** + small adapter if necessary | Verify endpoint signatures and version semantics in actual checkout |
| `game.py` on `sky` branch | **Retain** after cross-branch integration; compare to no-response baseline | Ensure `snapshot.game` truly available in chosen new-repo baseline |
| `service_routes[].board_uv`, flood corridors, `worldReactions.ts` on `sky` branch | **Retain/adapt** for world-to-projector visualization | Confirm field names/types by inspecting source; no assumptions |
| Woodblock-style flood art and camera-safe palette | **Retain/refine** | Ensure projected colors don't trigger camera classifier |
| Existing `/projector` fullscreen `F`, overlay-only `M`, affine `C` behavior | **Port** with calibrated Mapbox/board overlay | Physical projector still needs first hardware test |
| Session persistence / SQLite support | **Retain if already used** | Choose one existing scenario/session/data source; no alternate mock store |
| Existing Gemini narration with text fallback | **Optional**, outside deterministic core loop | Never block gameplay on model latency |

**Review caveat:** source code and live database were not independently accessible in this handoff. Paths above are from the supplied code audit; **verify file names, endpoint payloads, committed branch, and real database records before writing integration adapters**. The supplied review says `sky` commits `de98fba`, `5524335`, `e662b58` introduced dependencies across UI/backend, so port coherent revisions, not UI-only fragments.

### Fade/remove from the 75-second player journey

- Prevention mode (`/prevention/*`): not active in relief flow; **keep dormant or don't port to game UI**.
- Save/Load/Compare A/B branching: hide from player; can remain in diagnostics if low effort.
- Person piece as input: remove from timed action set; use actual existing population records as **projected groups**, not invented people objects.
- Physical START piece: make digital START create the required authoritative game-start state using the existing action contract. Do **not** simply disable backend validation globally.
- Debug panels, test checklist, raw Perceptron boxes, event log and open-ended Gemini chat: **operator-only**, never projected onto map.
- LP evacuation reasoning bundle: **not required** for main 75 seconds unless already integrated cleanly. Do not claim actual “evacuated people” if only service access is computed.
- Four simultaneous service missions, open map editing, custom terrain, new data acquisition, alternate geographic scenarios: no.
- Multiple redundant CV trackers (`tracker.py` CSRT, old `pipeline.py`, `fusion.py`, `board_watcher.py`): **reference only**, fresh implementation owns live CV behavior.

---

## 3. One shared live-data architecture

```text
             REAL PHYSICAL TABLETOP
             printed Mapbox-aligned Nepal map
             existing board ArUco markers
                       |
                 overhead camera
                       |
     +-----------------------------------+
     | NEW perception service            |
     | B: OpenCV frame + marker pose     |
     | B: track object ROI/ID/movement   |
     | C: Perceptron classify ROI async  |
     | B+C: fuse + stabilize/confidence  |
     +-----------------------------------+
                       |
        PhysicalObservation [track_id, class,
         board_uv, lifecycle, confidence]
                       |
     +-----------------------------------+
     | Thin observation/action adapter   |
     | dedup + match accepted world token|
     | validate world version            |
     | calls existing /action or         |
     | /perception/observe as supported  |
     +-----------------------------------+
                       |
     +-----------------------------------+
     | RETAINED AUTHORITATIVE BACKEND    |
     | real DB / HOT+OSM Nepal scenario  |
     | rules + inventory + budget        |
     | WorldService + flood stage        |
     | graph routing + unmet needs       |
     | score + snapshot + WebSocket      |
     +-----------------------------------+
                       |
                world.snapshot
                       |
     +-----------------------------------+
     | SKY'S UI                          |
     | Operator: mission controls/debug  |
     | Projector: canonical Mapbox map   |
     | flood/route/need/population cues  |
     | visual outcomes from actual state |
     +-----------------------------------+
                       |
                PHYSICAL PROJECTION
```

### Non-negotiable source-of-truth rules

1. `WorldService` and current DB/scenario own **all** domain state: coordinates, sites, roads, weights, population, demand, budgets, inventory, service availability, flood and score.
2. Perception owns **only what camera actually observes**: detected candidate, identity, location, timestamp, track lifecycle and confidence. It must not fabricate population counts or a route.
3. Projector draws only the last **accepted authoritative world snapshot**. A detected-but-unaccepted object gets an outline/pending cue, **never** a successful green service route.
4. Operator manual correction must call the **same** authoritative backend world action and be visibly identified as manual in logs/diagnostics; it is a physical I/O fallback, not a simulated world.
5. If DB/server is missing, fail clearly: `LIVE DATA UNAVAILABLE` on operator and a neutral hold-state on projector. Do not use demo JSON placeholders, mocked endpoints, or “pretend success” animations.
6. Mapbox style/token and other secrets belong in `.env` / environment; never commit live API credentials or expose Perceptron key in browser JS.
7. Every game run records scenario ID, dataset/version or DB fingerprint, server world version, timestamp, and event provenance to support real-data testing.

---

## 4. Proposed new-repo shape (adjust to existing stack; do not rewrite the core)

```text
floodshift-game/
  README.md
  FLOODSHIFT_MASTER_BUILD_SPEC.md
  .env.example                      # variables only, no secrets
  docs/
    LIVE_DATA_INVENTORY.md           # verified file paths / DB tables / Mapbox layers
    BOARD_REGISTRATION.md            # real ArUco IDs and measured board positions
    INTEGRATION_CONTRACT.md           # final payload shapes confirmed from code
    RUN_OF_SHOW.md                    # operator 75-sec instructions
    TEST_EVIDENCE.md                  # measured hardware results, not claims
  assets/
    inherited/                        # canonical map, art, scenario references
    live_captures/                    # actual board frames: gitignored if large/private
  perception/
    camera.py                         # Dev 1: capture and camera health
    board_aruco.py                    # Dev 1: existing markers -> calibration transform
    geometry.py                       # Dev 1: image(px)->board UV
    candidate_regions.py             # Dev 1: object proposals
    tracker.py                        # Dev 1: IDs + place/move/remove transitions
    perceptron_adapter.py            # Dev 2: official SDK + timeout
    classifier.py                     # Dev 2: labels + score normalization
    fusion.py                         # Dev 2: classification + tracking consensus
    events.py                         # jointly agreed typed observation contract
    service.py                        # process runner + output queue
    tests/                             # use captured real frames and source scenario
  backend/
    ...                                # port existing world core, keep source paths where possible
    integrations/
      perception_bridge.py            # observations -> existing authorized world actions
      game_session.py                 # timer/mode controls if authoritative coordination needed
  apps/
    game/
      ...                              # reuse existing frontend stack
      routes/operator/                # Sky: controls and diagnostics
      routes/projector/               # Sky: Mapbox + projection view
      game/clock.ts                    # 75-second phase state machine
      game/story.ts                    # copy strings, beat timing, no fake scenario values
      game/worldAdapter.ts             # real snapshot -> visible layers
      game/reactions.ts                # snapshot diff visual cues
      game/overlays/                   # flood, blocked roads, services, routes, populations
      game/results.ts                  # real score/needs output
  scripts/
    start_all.*                        # backend+perception+frontend launched in known order
    live_smoke_test.*                  # checks real server, DB, camera, marker, projector
```

**Do not assume this proposed tree exists yet.** Names and extensions should follow existing Vite/React/Python conventions when imported. Prefer copying tested core modules to rewriting them. New UI is built around their actual contracts.

---

## 5. Shared observation contract (proposal; confirm against `/perception/observe`)

The below is a **schema design**, not sample game data and not a claim the old endpoint accepts these keys. Write a typed adapter to the actual existing API rather than changing routing logic to match this proposal.

```ts
type PieceClass = 'bridge' | 'shelter' | 'hospital' | 'food_station';
type PhysicalLifecycle = 'candidate' | 'placed' | 'moved' | 'removed' | 'lost';
type ConfidenceBand = 'high' | 'review' | 'reject';

type PhysicalObservation = {
  event_id: string;             // stable idempotency key
  session_id: string;           // current mission run
  track_id: string;             // stable within observed lifetime
  piece_class: PieceClass | null;
  lifecycle: PhysicalLifecycle;
  board_uv: {u: number; v: number} | null; // 0..1 after ArUco homography
  orientation_deg?: number;     // optional; not mandatory to accept bridge
  detection_confidence: number | null;     // calibrated 0..1 if supplied/derived
  localization_confidence: number | null;  // calibrated 0..1 if measurable
  confidence_band: ConfidenceBand;
  observed_at_ms: number;
  source: 'live_camera';
};
```

### Observation → accepted action lifecycle

```text
camera candidate spotted
   -> stable position/class confidence across frames?
      NO: pending outline only / keep observing
      YES: emit placed + event_id once
           -> current world version + actual rules checked
              REJECT: display rejection code/retry cue; DO NOT burn location permanently
              ACCEPT: bind physical track_id -> authoritative world token ID
                      receive updated world.snapshot via /ws
                      projector displays committed consequences

physical piece moves -> same track ID -> moved action once when stable enough
physical piece lifted -> delayed removed action after occlusion grace period
physical piece reappears -> restore or re-place consistently with world state
run reset -> clear observation caches, world-token bindings and stale events
```

#### Important integrity rules

- Track IDs are not token IDs. Store `track_id -> accepted_world_token_id` mapping for each active game session.
- Duplicate event IDs do nothing; stale world versions must be retried by re-reading and reconciling, never silently discarded or double-applied.
- A backend rejection does not enter a forever-blocked `_sent_positions` list. Allow corrected placement or physical removal/retry.
- Removing an object must follow existing world removal semantics (including budget/inventory) rather than mutate JSON or delete a route in frontend.
- If object temporarily occludes a map marker, keep last validated homography for a short bounded grace interval and show camera health; don't jump board coordinates.
- If object class can't be verified, do not auto-commit. The operator can authorize a manual world action using the same live location/pad.
- Calibration failure blocks automated placement but **does not** make the frontend display fake results.

### Recommended acceptance rule (tunable with real camera trials)

- **HIGH:** stable location for several frames + correct class with high measured/available recognition confidence + position inside an actual allowed backend site; submit.
- **REVIEW:** detectable object but uncertain class, position, or classification; show pending cue, request more frames/operator review.
- **REJECT:** outside map, missing board registration, invalid class, contradicted temporal evidence; do not submit.
- Do not claim SDK supplies probabilities unless confirmed. If it does not, make the score reflect *local fusion quality* (agreement, stability, geometry) and label it honestly, rather than inventing Perceptron model confidence.
- Starting numeric thresholds must be tuned against **recorded live setup frames**, not guessed to maximize a fake success rate. Save measured precision/recall and latency.

### Suggested physical source tests

- Hold each existing physical piece on a verified pad, then remove it; observe class, board UV, timing, event count.
- Move same piece between two valid pads and a flood-exposed pad; verify move vs remove+place semantics consistently.
- Insert an invalid bridge, wait for rejection, reposition: backend should then accept the same track.
- Lift and replace repeatedly; no stale suppression, no score farming.
- Occlude some ArUco markers with a hand/piece; coordinates must not jump catastrophically.
- Run with real projector turned on; check overlay color and dynamic shadows cause no extra piece detections.
- Unplug camera / expire Perceptron timeout; operator gets honest degraded state and can still drive the world with manual inputs.

---

## 6. Lane B — OpenCV / ArUco / physical tracking: Dev 1

**Goal:** robust physical location and lifecycle detection even when Perceptron is slow/unavailable.

### Rebuild only these components

1. Enumerate available camera indices instead of hardcoding `1`; validate actual working device and resolution. Report status to operator.
2. Read existing map's ArUco markers via OpenCV `cv2.aruco.ArucoDetector` (or equivalent installed version); confirm dictionary and IDs **from current physical map**, not just the old audit's tentative IDs 10–13.
3. Detect corner pixel coordinates and match them against their known *actual board positions*. Compute homography (camera pixels ↔ board UV), ideally using multiple marker corners; record reprojection error. Board markers are physical calibration references, **not** playable objects.
4. Use camera intrinsics/undistortion if perspective or lens distortion materially affects alignment; keep camera-to-board and projector-to-board transforms as separate calibrated transforms.
5. Find piece candidates with background-aware change detection / contour ROI / region proposals while excluding known projected patterns and physical board markers. Do not rely solely on a yellow-bridge filter. Use top-down board warp to reduce perspective/size variance.
6. Assign persistent track IDs using nearest-neighbor or IoU association with a gating threshold, temporal filters, and explicit appearance/loss/move transitions. Choose a simple stable tracker instead of maintaining three overlapping stacks.
7. Produce thumbnails/ROIs for Dev 2's Perceptron classifier; perform class inference only on changed/unresolved tracks rather than every frame.
8. Emit stable observations to a queue/nonblocking bridge; do not block capture with network or SDK calls.
9. Track *actual piece center/contact footprint*, not blob shadow centroid, before snapping only as allowed by existing world rules. Display raw vs snapped in operator debug.
10. Reset safely: background/reference capture when board state is known; reset track mapping and pending flags per session, without restarting hardware unnecessarily.

**Specific legacy bugs to eliminate:** rejected-spot permanent suppression, place-only actions (no move/remove), perspective/centroid error, marker occlusion collision, camera default 1, synchronous Perceptron freezing frames, duplicate/unused tracker stacks.

**Dev 1 done when:** stable board UV and lifecycle events can be demonstrated from the **actual physical printed board** and actual camera feed, with projector both off and on, without sending any fake world mutations.

---

## 7. Lane C — Perceptron classification + fusion: Dev 2

**Goal:** reliably assign one of the existing physical piece classes while reporting uncertainty, not hallucinating class or identity.

### First: validate the official SDK and API version

- Official Python SDK: https://github.com/perceptron-ai-inc/perceptron
- Official Perceptron MCP reference: https://github.com/perceptron-ai-inc/mcp-server
- Official OpenCV ArUco board docs: https://docs.opencv.org/4.13.0/db/da9/tutorial_aruco_board_detection.html
- Use current documented package/API; SDK quick start shows `from perceptron import detect` and `detect(image, classes=[...])`. **Verify actual authenticated live return structure**; SDK may return compile-only requests without credentials. Never treat those as detections.

### Pipeline

1. Consume actual camera crop + mask/box + Dev 1 track ID.
2. Classify between `bridge`, `hospital`, `shelter`, `food_station` with explicit per-class visual descriptions and actual physical top-view photos. Include `unknown/none` as legitimate result.
3. Use existing STL dimensions and hardware photos; bridge has a known `photo_top.jpg` in the prior review, capture equivalent real top views for other pieces. For similar-looking pieces, tag-assisted classification **may** be used if pieces have readable unique tags; avoid conflating board anchor ArUco IDs with piece IDs.
4. Normalize output into `{track_id, class_label, bbox, evidence, model_confidence_if_available, latency_ms, valid}`; robustly parse empty, partial and unexpected responses.
5. Fuse semantic class evidence with stable OpenCV shape/size/orientation evidence and real board placement constraints; do not let a valid pad *invent* a class if model is unsure.
6. Cache recent classification while track persists; reclassify after a substantial appearance shift/reacquisition or if contradictory evidence arrives.
7. Run inference in a bounded worker/async task. Keep camera and tracker responsive even if API call stalls; configure timeout and queue size.
8. Use explicit confidence bands from measured results. Track `false_positives`, `false_negatives`, `unknown_rate`, `classification_latency`, `end_to_end_commit_latency`, and p95 where feasible.
9. Provide a degraded classification state when API is missing, throttled, or down; manual mode is operator-activated, never a fabricated classifier result.

### Open-source/available repos to reuse *selectively*

- **OpenCV ArUco board** implementation: board detection/calibration, marker corner quality, homography. Prefer official APIs and examples.
- **Perceptron official Python SDK:** class-grounded crop classification / structured detections. Prefer over handwritten undocumented HTTP.
- **Optional association algorithm** (e.g. ByteTrack-inspired simple matching) only if it is actually necessary for multiple moving pieces and fast enough. In a tabletop with few mostly stationary tokens, simpler deterministic tracking is usually safer.

**Dev 2 done when:** bridge, shelter, hospital and food station classifications are measured on real recorded/live top-down frames, confidence quality is visible, unknown objects don't auto-place, and long Perceptron calls never freeze the camera loop.

---

## 8. Shared retained-backend integration: actual data, actual consequences

### Asset inventory before modifying anything

Create `docs/LIVE_DATA_INVENTORY.md` from the actual old repository checkout:

- Source branch/commit selected, current DB file/service and schema identifier, scenario IDs.
- Existing geographic/Mapbox style, layer IDs, center, zoom, bounds, printed map extents, existing camera/projector calibration values.
- Real marker dictionary/IDs/coordinates measured on the **current** board.
- Existing population features and sizes, residential polygons or population points, road graph, crossing edges, service candidate pads, flood/risk geometries, stages, inventory, capacities and score schema.
- Endpoints, action request body types, game snapshot field names, WebSocket message envelope, map coordinate formats.
- Licensing/attribution for Mapbox tiles, OSM/HOT and source flood/population data.

**Do not guess database tables/paths or create records just to make the UI populate.** If a field is genuinely absent, represent it as unavailable in the UI and adjust the label rather than forge a number.

### Locked single scenario

`nepal_rasuwa_hot_v1` is the old server's default real HOT/OSM scenario per the review; use it unless the current Mapbox-and-DB integration points to a different authoritative ID. Explicitly configure **one ID** in UI, server, world service and integration tests; don't let defaults disagree.

### Required authoritative gameplay actions

All must go through the existing rule engine with versioning and clear rejection codes:

- Digital `START` / create active mission (respects, or explicitly adapts, START-first rules)
- `place_token` bridge/shelter/hospital/food station
- `move_token` when physically relocated
- `remove_token` when physically lifted/removed
- `advance_flood_stage` or existing equivalent action
- `reset` to authoritative initial state
- `plan/suggest` ghost bridge hint (optional)
- `get world/scenario/score snapshot`

These are *semantic action names*. Map them to actual legacy payload enums/routes, don't assume those exact strings exist. Only a successful world action leads to changed projected consequences.

### Flood and residential overlay truthfulness

- Use actual flood corridor/stage geometry from world snapshots. Draw blue water over the correct real Mapbox areas (not random expanding ellipses).
- Intersect current flooded footprints with existing **real** residential polygon/population footprint data. If the current dataset supplies only population nodes (not residential polygons), draw bounded red circles/halos at their recorded points and explicitly label the visualization as **affected population markers**, not fake parcel footprints.
- Red overlay means **currently impacted/blocked by simulated flood state**. A red route means **graph routing currently fails/unavailable**. Don't make red appear merely because the clock reached a cinematic beat.
- Use snapshot-derived service paths (including `service_routes[].board_uv` if present). If “would-be path” is supplied, draw as dashed red when blocked; solid neon green/cyan only when backend marks it reachable.
- Preserve capacity constraints: a shelter cannot serve unlimited people because it has a glowing marker. Display unmet demand if capacity exhausted.
- For population movement, dots along graph paths are **symbolic route visualization of access**. Do not call them completed evacuations unless actual evacuation counts are computed by the active backend.

### Coordinates / transforms (must be explicitly tested)

```text
camera frame (px)
  -> board ArUco pose + homography
  -> normalized board UV
  -> validated physical pad / world action
  -> world graph / geo coordinates (existing map source)
  -> Mapbox route & flood geometry in the canonical map extent
  -> projector pixel/UV calibration to printed map
```

Mapbox rendering layer and projector overlay must use identical map extents, orientation and correct transform. Apply projector keystone/calibration **after** mapping to board space; do not store a separately guessed map geometry. Existing projector affine `C` is a useful starting point; use a four-corner homography if measured keystone distortion requires it.

### World reaction to visual reaction mapping

| Real backend/sensor event | Player-facing visual | Only when… |
|---|---|---|
| Stable physical candidate | Soft thin ring on tentative placement; no score | Camera observes candidate but backend has not accepted action |
| `place_token` accepted | Piece receives 500–800 ms halo; nearby zone illuminates | Authoritative action success + matching snapshot version |
| Bridge restores graph edge/reachability | Broken red dashed route redraws as solid green animated path | Returned backend service path is reachable |
| Shelter/hospital/food station accepted | Corresponding icon and actual service-route pulses; fulfilled-needs metric updates | Facility active and backend reports service access/capacity impact |
| Placement rejected | Short red outline with one human-readable reason, then fades; no route or score change | Backend rejects with reason code |
| Piece moves | Old site unhighlights; new site and routes recalculate | Authoritative move accepted |
| Piece removed | Light turns off; dependent green route/service transitions to unavailable if changed | Authoritative remove accepted |
| Flood stage advanced | Blue flood polygon transitions to next actual footprint; genuinely affected homes/routes turn red | New snapshot reports affected assets/routes |
| Population becomes accessible | Population node shifts from danger red to reachable pale green; optional small dot traverses computed route | Reachability/service snapshot supports it |
| Population loses access | Population node glows red, route fades to dashed warning | Reachability decreases in world snapshot |
| Capacity runs out | Service icon displays solid outlined full/limited-state and nearby need indicator persists | Backend capacity/unmet need supports it |
| Ghost bridge hint | Translucent violet bridge silhouette at real suggested pad | `/plan/suggest` returned valid suggestion |
| Win/results | Real score, accessible population/needs met and baseline difference | `snapshot.game` / actual metrics are present |
| Missing DB/server | Neutral hold screen, status label, no numbers | Health or real snapshot fails |

---

## 9. SKY — COMPLETE PROJECTOR GAME DESIGN PROMPT

> **Paste this section into the UI implementation task.** The UI must be grounded in existing Mapbox view/layers and real backend fields. No static sample neighborhood, fake scores or hardcoded bridge route.

### Creative direction

Create **FLOODSHIFT: THE LAST CROSSING**, a dark, cinematic, woodblock-inspired interactive projection over a real printed Mapbox map of Shyaphru Bensi, Nepal. It draws aesthetic inspiration from the Manu–Matsya flood narrative: a small warning grows into a catastrophic flood, and the player's responsibility is to protect lives and knowledge. The look should feel handcrafted, mythic and serious—not arcade neon, not a generic admin dashboard. Use **minimal but impactful glow**, restrained transitions and slightly dark values for projection on paper.

**This is a real projection surface**, so every visible road, flood boundary, population zone, valid pad and route must align with the existing real geospatial data and physical printed board. Respect the actual preprinted ArUco markers: projector must mask/avoid marker areas so corner detection stays legible. The map is Mapbox; keep Mapbox map style and transformations. Reuse existing woodblock flood art where available.

### Visual language

- **Base:** existing printed Mapbox cartography + optional low-opacity dark vignette inside board edges; don't wash out roads/labels.
- **Water:** deep desaturated teal/cyan, fine moving engraved ripple/hatching. Water boundary gets a brief bright cyan lip only when advancing.
- **Danger/flooded residential area:** transparent muted red/rose *only over real impacted population geometry*, fine diagonal ink hatching, 1–2 second red edge pulse on first impact. Never obscure ArUco markers.
- **Blocked route:** rust red dashed thin segmented path; pulse 2x upon loss then settle.
- **Safe accessible route:** restrained fresh green/seafoam line; bright traveling pulse on newly opened segment then dim to readable solid line.
- **Valid placement pads:** four corner brackets / small low-glow ring; only highlight the sites currently valid and relevant. Do not project over token or ArUco pattern.
- **Accepted placement:** one expanding translucent halo, short white-green rim pulse, tiny label `BRIDGE CONNECTED` or `SHELTER ACTIVE`; fade label after ~1.5 sec.
- **Invalid placement:** brief muted red ring, no destructive shake or flashing, context copy e.g. `CROSSING UNAVAILABLE`, `FLOOD RISK`, `SITE OCCUPIED`, `MOVE CLOSER` based on actual rejection code.
- **Population:** small clusters of cream pinpoints or concentric dots at actual population positions; count label from DB when available. Danger red; accessible mint. Dot travel along **computed** route optional/secondary.
- **Hospitals:** simple cross emblem, cool pearl glow; **shelters:** roof/safe haven motif, sea-green glow; **food:** relief crate/leaf motif; **bridge:** thin connection glyph.
- **Ghost hint:** violet outlined translucent bridge; clearly marked `SUGGESTED` rather than placed.
- **Narrative motif:** subtle fish-tail current or horn line animation at act transitions; minimal and outside marker/roads; never replace actual flood contours with fantastical ones.
- **Color safety:** do not use projector yellow/amber hues resembling old CV bridge filter. Maintain camera-safe palette from prior code (`e662b58`) and re-test against new classifier.
- **Motion safety/readability:** no continuous violent screen shake, no strobe; transitions ~250–800 ms. Essential status information always readable without animation.

### Physical surface layout

Use the **canonical Mapbox map** over the board. Avoid drawing a huge HUD on the terrain. Put small compact elements near board edges but outside ArUco markers: mission status upper edge, countdown outside/map margin or on laptop, a minimal objective cue close to current relevant site, and a clear localized result near accepted object. Never place fake settlement annotations. The operator laptop has full details.

### Exact before-play state

- **Physical inventory tray, outside board/active mask:** bridge, shelter, hospital, food station. Each has an identifiable real 3D print/top view; camera should not treat tray as placed assets.
- **No required person piece.** Residents are existing population groups in DB and projected on map.
- **No physical START token.** The operator clicks digital `START GAME`, which initializes world state through existing rules.
- **Base map:** subdued, real map of Shyaphru Bensi; existing ArUco markers uncovered.
- **Projector idle:** title `FLOODSHIFT / THE LAST CROSSING`, `Ready to respond`, a restrained undulating current along *the actual river* and soft highlights on existing service/population locations. **Do not show a false flooded area while idle.**

### The full 75-second story / game walkthrough

The mission clock is **fixed**; world consequences are **dynamic**. Failure to place a piece by a scheduled beat does not freeze progression. The operator can pause for hardware troubleshooting; pauses suspend the clock, but stage input still uses real backend actions.

| Time | Narrative prompt (exact suggested copy) | Player physically does | Projector: exact visible change | Implementation source |
|---|---|---|---|---|
| **00–10** | `FLASH FLOOD WARNING` / `Communities are losing access to safety.` | Watches and orients; no forced placement | Real river/flood footprint activates in blue; existing vulnerable population zones light up; genuinely blocked road segments dashed red; objective text `RESTORE THE CROSSING` | Real scenario snapshot, existing flood geometry, routing |
| **10–30** | `MISSION 01 — THE LAST CROSSING` / `Reconnect the isolated community.` | Lifts physical **bridge** from tray and sets it on a highlighted valid crossing | Candidate gets dim pending ring. After accepted world action: bridge halo blooms once; disconnected red route **only if actually restored** changes to green; population accessibility markers/needs totals update. Brief cue `ACCESS RESTORED` or, if no gain, `BRIDGE PLACED · NO NEW ACCESS` | New CV + old `rules.py` + `reachability.measure()` + world reactions |
| **30–50** | `MISSION 02 — THE PEOPLE` / `Food, refuge, and care are running out.` | Chooses **shelter or hospital** (food optional) and places at a valid live site | Valid service pads appear, real unmet-need areas brighten. Accepted shelter/hospital icon glows; actual returned service route pulses; counts change only if backend reports change. Highlight `REFUGE ACCESS IMPROVED`, `MEDICAL ACCESS IMPROVED`, or truthful capacity/no-gain label | Old facility placement rules, capacities and unmet needs |
| **50–70** | `MISSION 03 — THE SURGE` / `Another road may be lost. Act now.` | Responds with a remaining physical piece, moves one, or makes no change depending on available inventory/valid locations | Advance **one actual world flood stage**. Blue flood footprint expands according to real geometry; intersected residence/population markers receive muted red fill/hatch; routes blocked by that state turn dashed red; accessibility recomputes. Optional ghost recommendation if player needs help | Existing flood stage action + graph + ghost planner |
| **70–75** | `THE FLOOD SETTLES` / `Your actions shaped the outcome.` | Stops moving pieces; sees consequence | Sim state freezes for result rendering; map dims slightly; real results show **population with service access**, **needs met/unmet**, **routes restored**, and **change from baseline** if available. No fictional numbers, no ungrounded “lives saved” claim. | `snapshot.game` and live authoritative metrics |

**Countdown semantics:** use real monotonic mission elapsed time in client or shared session controller for pacing, independent of wall clock. Stage at 50 seconds must call the backend action and wait for a confirmed snapshot before any new flood footprint appears. The result screen derives from latest committed world snapshot (and shows pending indicator if a request is in flight). If backend advancement fails, show `FLOOD UPDATE UNAVAILABLE` rather than animating invented flooding.

### Moment-to-moment details (not optional visual design)

**Bridge success sequence, max ~2 seconds of effects:**

1. Placement enters ROI; faint *pending* contour around real bridge location with subtle dark-blue/white pulse (no change in green route).
2. Accepted action returns; world snapshot version increments.
3. Small mint/white halo around physical bridge, never over marker code.
4. Red cut path disappears/attenuates **only if real backend says it became connected**.
5. Actual computed route gradually strokes mint from resident group to real destination; a small luminous dot travels once along it (cosmetic, does not alter state).
6. Relevant population groups fade from threatened red to reachable mint if their calculated access improves.
7. Short exact message based on outcome: `ROUTE RESTORED`, `BRIDGE PLACED`, or `NO NEW ACCESS`.
8. Operator HUD updates verified world version, action provenance and access delta.

**Flood-impact sequence:**

1. Operator / timed system issues actual advance-stage action.
2. On accepted new world snapshot: animate **old flood polygon to new** where geospatially possible; otherwise crossfade discrete real footprints, never synthesize circles.
3. Existing population polygons/points that newly intersect risk flood get muted red overlay and 1-second boundary glow.
4. Routes changed to blocked animate from green to red dashed. Facilities in footprint become unavailable only when backend says so.
5. A small alert tag names the changed area **only if actual dataset supplies a name**; otherwise use `POPULATION AREA AFFECTED`, no fictional neighborhood names.
6. At end, all effects settle into readable static state; keep markers visible to CV.

**Shelter/hospital/food accepted:** icon location pulses once, connected service route highlights, real capacity indicator updates; if capacity or supply route blocks service, show `PLACED · ACCESS STILL LIMITED` and leave unmet-need markers red.

**Moving/removing:** remove old site's glow, recompute effect from world, optionally show a short “rerouting…” transition while waiting for accepted snapshot. Never overlay a ghost at an old piece position to conceal desync.

**Failure/uncertainty:** low confidence candidate -> dim outline and `CHECKING PLACEMENT` only on operator (player sees subtle candidate highlight). Invalid backend action -> red ring and short actual reason. Server disconnect -> freeze authoritative last map state and show discrete `CONNECTION LOST` operator warning; do not continue fictional gameplay visuals.

**Sound:** optional 4 simple local assets: low initial bell/current, accepted placement chime, brief flood-surge swell, restrained ending chord. Fail gracefully in silence, never autoplay external audio on a browser requiring permission. Provide `MUTE` on operator, not projector.

### Operator UI: every required button and display state

The operator view is **not** the projector. It needs an at-a-glance status line (`DB`, `world/ws`, `camera`, `ArUco calibrated`, `Perceptron`, `projector calibrated`, active scenario ID/version) and these functional controls:

| Control | Visible when | Exact effect | Guard / rule |
|---|---|---|---|
| `LOAD LIVE SCENARIO` | Before start | Load existing configured DB/scenario and initial authoritative snapshot | Fail with error; never substitute demo world |
| `CALIBRATE CAMERA` | Setup | Opens/starts real OpenCV ArUco calibration flow; show detected IDs and reprojection quality | Do not place objects until valid |
| `CALIBRATE PROJECTOR` | Setup | Align projector overlay against printed board, retain existing `C` capability | No simulated transform |
| `TEST PROJECTOR` | Setup | Display harmless registration outlines / corner reticles only | Ensure reticles do not occlude markers; not a fake game |
| `START GAME` | Idle and healthy world | Reset/init authoritative world and begin 75-sec clock; trigger first script beat | START-first backend rule handled explicitly |
| `PAUSE` | Running | Stops mission timer/automatic events, preserves state | Does not undo committed actions |
| `RESUME` | Paused | Resumes timer from same elapsed time | World connection required |
| `ADVANCE FLOOD` | Running / operator | Call actual existing flood-stage action once | No new flood visual before accepted snapshot |
| `SUGGEST BRIDGE` | Running | Calls existing `/plan/suggest` and projects actual recommended crossing | Show `NO VALID SUGGESTION` if none |
| `MANUAL PLACE` | Running / degraded detection | Operator selects actual piece + allowed site, calls same authoritative action | Shows source `operator_manual`; no invented outcome |
| `MANUAL MOVE` | Running / degraded | Calls same actual move action for selected token/site | Check valid token and backend version |
| `MANUAL REMOVE` | Running / degraded | Calls actual remove token action | Confirmation to avoid accidental deletion |
| `CLEAR PENDING DETECTION` | Any | Clears pending observation only, not world token | For CV false positive recovery |
| `RECALIBRATE` | Paused | Re-establish camera/projector transform | No silent world reset |
| `SHOW DEBUG` | Operator only | Raw camera frame, ROIs, track IDs, confidence, pending/rejects, marker IDs, latency | Never mirrored to projector |
| `MUTE / UNMUTE` | Any | Toggle local game effects/music | Persist for current session |
| `END & SHOW RESULTS` | Running | Ends timer and renders actual final snapshot | If score unavailable, show truthful limitation |
| `RESET GAME` | Any | Calls authoritative reset; clears mission clock, track mapping and effects | Confirm; preserve real DB/scenario data |
| `REPLAY` | Results | Resets authoritative world, returns to ready state | Never reuse old snapshot as new live data |

**Pre-existing shortcuts to retain:** `F` projector fullscreen, `M` overlay-only, `C` projector calibration. Existing keys `1–6` may stay **only in operator diagnostic/manual mode**, never as active player instructions. Preserve click-to-pad diagnostics if they call live actions.

**Displays operator needs:** current phase/remaining seconds; selected physical/matched world token; detected classes/confidence; camera frame/marker count; world response/rejection reasons; real unmet refuge/food/medical needs; population-access deltas; accepted/rejected action log; active DB/scenario fingerprint; projector health; latest authoritative snapshot version; manual-vs-camera provenance.

**Player/projector minimal UI:** compact mission headline, contextual instruction near valid pad, optional small timer, floating acceptance feedback, visible actual service/flood overlays and end result. No diagnostics or code labels.

### Game phase logic

`IDLE -> INTRO (optional, outside clock) -> WARNING -> CROSSING -> RELIEF -> SURGE -> RESULTS -> IDLE/REPLAY`

- Use a pure phase reducer/controller with explicit transitions by elapsed time. Start at `0`; phase boundaries `10`, `30`, `50`, `70`, `75` seconds.
- Gameplay events can happen early/late relative to phase boundaries. Place/move/remove always processed by backend if phase allows it.
- One-time flood advance for the surge needs a stable `event_id` and guard so pause/resume or React rerender cannot double-advance it.
- Results at 70–75 sec should freeze input by 70 if desired (design choice), but account for in-flight accepted actions consistently. Define a finalization barrier: wait for accepted action acknowledgments **without inventing new data**, or mark final as still syncing if response delayed.
- Allow operator override if hardware has trouble; route it through same live world action.
- Do not tie world route computation to CSS timers. Visual animations follow snapshots.

### Results page (no imaginary values)

Show only fields calculated by active scenario, e.g.:

- `POPULATION WITH REFUGE ACCESS` — live count if available.
- `FOOD NEEDS MET` / `MEDICAL NEEDS MET` — from capacity/reachability evaluation.
- `CROSSINGS/ROUTES RESTORED` — from accepted bridge action and change in graph reachability; do not infer from number of bridge tokens.
- `CHANGE VS. NO-RESPONSE BASELINE` — only if game score exposes a real comparison.
- `UNMET NEEDS REMAINING` — if available, make a non-victory ending meaningful too.
- `RESPONSE COMPLETE` as default; not `EVERYONE SAVED` if unmet need remains.

If the score supports real categorical outcome tiers, select copy based on those exact score fields. Do **not** invent thresholds before reviewing the live score. If a needed metric is absent, omit it rather than displaying `0`.

---

## 10. Real-data testing and integration acceptance

### No-fake-data policy

- Every end-to-end run uses the original real scenario/database, real physical board/markers, real Mapbox extent/layers and actual camera observations (or authentic recorded camera frames with source noted).
- **Unit tests may use small mathematical inputs for pure transforms**, but all gameplay/acceptance/integration tests must use real scenario records. Do not package a fabricated “demo” scenario or hardcode 9/12 saved, 48% improved, fake flood circles, etc.
- No fake Perceptron responses used to claim acceptance. A local recorded real SDK response can be retained with provenance to test parser regression; clearly label as recorded, not live.
- Explicitly fail or disable a feature when an upstream field is absent; log it. Never silently switch to synthetic data.

### End-to-end test matrix: demonstrate on actual hardware

| Test ID | Action | Expected, sourced outcome | Owner(s) |
|---|---|---|---|
| T01 | Start backend, load current DB and `nepal_rasuwa_hot_v1` or validated canonical ID | Non-empty real scenario, no mock_mode, clear scenario fingerprint | Shared |
| T02 | Open Mapbox/projector over printed map | Roads, river, service pads and flood footprint align with print; ArUco markers visible | Sky + Dev 1 |
| T03 | Detect real board markers | Actual IDs recognized; stable homography; calibrated status visible | Dev 1 |
| T04 | Place real bridge on known valid pad | One accepted world action, one live snapshot version bump, no duplicate | Both detection devs + backend |
| T05 | Verify after bridge placement | Actual reachable route becomes green **if** backend accessibility increased; score delta equals backend | Sky + shared |
| T06 | Place bridge on invalid pad, then correct it | Reason shown; later corrected placement accepted, no stale sent-position lock | Dev 1 + shared |
| T07 | Move then lift token | World move/remove action matches physical state; affected routes update | Dev 1 + shared + Sky |
| T08 | Place each of shelter/hospital/food | Class measured; only accepted service sites update real capacity/needs | Dev 2 + shared + Sky |
| T09 | Trigger actual flood stage | Real flood geometry appears; newly affected residential/population features red; blocked paths match graph | Shared + Sky |
| T10 | Timer crosses 30/50/70 under no input | Fixed story progresses with no made-up outcome; results reflect real non-response case | Sky + shared |
| T11 | Pause/resume during surge | Single flood advance, no duplicate and clock preserves elapsed time | Sky |
| T12 | Start then lose Perceptron/API | Camera does not freeze; operator sees degraded state; no fake auto-recognition | Dev 1 + Dev 2 |
| T13 | Start then lose backend/DB | Operator warns, projector holds; no synthetic routes or green successes | Sky + shared |
| T14 | Use manual operator placement | Same rules, server version and actual consequences; event marked manual | Sky + shared |
| T15 | Reset/replay after multiple placements | World state, score, track mapping, pending caches and clock correctly reset | All |
| T16 | Full 75-second run (multiple consecutive trials) | Script, CV, scoring, Mapbox/projection, flood stage and results all remain synchronized | All |

Record **actual measured** results for camera fps, classification latency, precision/recall by piece, marker reprojection error, action acceptance/duplicate rates, full-chain latency, Mapbox projector alignment error and successful full runs. Do not populate invented performance targets as achieved facts.

### Minimum passing evidence

- Live run video showing real map + physical bridge → green route that backend reports as reachable.
- Snapshot/action log corresponding to that same run, including before/after world versions and real service delta.
- Physical move/remove tested and correctly represented in world state.
- Surge shows actual flood footprint and red affects **only** corresponding real residential/population locations.
- One full uninterrupted 75-second timed run with truthful final results.
- Clear evidence the ArUco print markers are already present and functional on the actual board, plus current Mapbox and DB sourced from original repo.

---

## 11. Build sequence and merge gates

### Gate 0 — lock source truth (all, before parallel merges)

1. Select one coherent source commit from existing repo, including `sky` world + frontend dependencies where appropriate.
2. Verify **current Mapbox map** and real database, exact scenario ID, geographic extent, JSON/schema types, and ArUco printed marker IDs.
3. Copy actual world data and code; put secrets in `.env`.
4. Confirm existing world server starts with **real state**, `/world`, `/scenario`, `/action`, `/ws` function. Run current tests with UTF-8 explicitly on Windows if necessary.
5. Agree on single observation contract and backend action adapter before frontend/CV diverge.

### Parallel sprint A — Sky / game and projector

- Port Mapbox map + projector calibration + `worldReactions`/routes.
- Build operator start/pause/resume/reset, phase timer and story copy.
- Build real spatial overlay layers, route line/blocked-line effects, population/capacity markers.
- Hook ALL visuals to live authoritative snapshots (manual operator actions can exercise UI before camera integration; **not simulated**).
- Implement results and diagnostics with connected/failed states.

### Parallel sprint B — Dev 1 / OpenCV

- Calibrate using **existing real ArUco markers**, capture warped board view and stable UV.
- Implement candidate proposals, true track IDs, enter/move/remove transitions, retry after rejection.
- Send actual observation events with measured geometric certainty; provide debug visualization and camera health.

### Parallel sprint C — Dev 2 / Perceptron

- Validate SDK/key/model/real response; tune prompt/detection on actual physical piece photographs.
- Implement crop classification, unknown class, async worker, confidence band and fusion.
- Tune measured thresholds with real camera recordings including projector running.

### Integration sprint — all

1. Tie a real bridge observation to existing `place_token` accepted action and world snapshot.
2. Verify route and score response *before* adding extra animation polish.
3. Tie one other class/service to rules and real capacity.
4. Test move/removal and rejected/retry behavior.
5. Verify timed flood stage and spatial red overlay.
6. Run 75 seconds live; measure, fix, repeat; document evidence.

### Scope freeze order, if time is short

| Order | Must work before next thing | If failing, cut this instead |
|---|---|---|
| **P0** | Real Mapbox + DB + world/snapshot + physical ArUco alignment | No new map styles/alternate datasets |
| **P0** | Real bridge recognized or reliably entered through operator and validated by world | No multi-object gameplay requirement |
| **P0** | Projected actual route/flood/access consequences | No cinematic detail polish |
| **P0** | One-click start, 75-sec phases, reset, truthful results | No extra cutscene during the clock |
| **P1** | Real shelter/hospital recognition and effect | Food station becomes optional |
| **P1** | Stable physical move/remove | Ghost hints optional |
| **P2** | Citizen dots, music, sparkle, Gemini flavor text | No new gameplay mechanics |

**Preferred demo grade strategy:** reliable physically observed bridge + correct backend reaction + readable projector beats is substantially stronger than a gorgeous fabricated rescue score. Preserve originality through the physical interaction and Manu–Matsya visual framing, not a brittle number of ML calls.

---

## 12. Final no-go checklist (red flags)

- [ ] Game shows an invented `9/12` or population rescued number.
- [ ] Green routes come from token location guesses rather than confirmed world reachability.
- [ ] Flood red overlay randomly covers arbitrary circles or labeled neighborhoods absent from source data.
- [ ] UI uses a different map extent/style than current Mapbox printed board.
- [ ] Board ArUco markers are hidden by projection, piece, title card or START pad.
- [ ] Perceptron API returns a compile-only payload but game treats it as a detection.
- [ ] Camera thread freezes while waiting for SDK/network.
- [ ] Rejected piece cannot be retried without restarting code.
- [ ] Picking up a piece leaves backend token placed.
- [ ] Reset does not clear physical track/world binding.
- [ ] Mission timer auto-renders flooding without backend stage confirmation.
- [ ] Frontend continues to claim success while world DB is unavailable.
- [ ] Sky UI depends on `sky`-only backend fields absent from imported branch.
- [ ] Reviewers cannot see one confirmed physical event causing a real route/environmental result.

---

## 13. Handoff prompts to paste to each contributor

### SKY — UI / GAME / PROJECTOR

> Build the FloodShift 75-second live game/projector and operator UI from Sections 8–11. Preserve the existing Mapbox map, real source database/world snapshot, projected registration against the already ArUco-marked map, and current woodblock flood visuals. Implement all timed narrative beats and every control listed. Strong visual clarity: muted blue actual flood polygons, red actual flooded residential/population footprints, red dashed blocked paths, mint glowing reachable routes, real shelter/hospital/food needs and tiny population access dots, brief white-green placement halos, violet real ghost-bridge hints, a 5-second truthful real-data outcome screen. In-game Manu–Matsya motifs are restrained; existing optional cinematic remains outside the 75-second timer. Do not write fake state, route geometry, score, invented marker positions or mock API. Allow manual operator actions to call the **real backend** while CV teams build; all visuals must be derived from resulting authoritative snapshots. Make the physical bridge → real route connection visible in under a couple seconds when hardware/backend allows. Deliver `/projector`, `/operator`, phase reducer, live-data adapter, fail states, and a recorded real 75-second test.

### DETECTION DEV 1 — OPENCV / ARUCO / TRACKING

> In a fresh `perception/` service, detect the ArUco tags **already present on the actual map**, compute camera-to-board homography, identify candidate physical piece regions and maintain persistent track IDs as pieces are placed, moved and removed. Use current printed Mapbox board geometry/real calibration; do not draw new markers or invent their IDs. Emit well-typed observations with board UV, lifecycle, timestamp, geometry quality and provenance. Repair previous permanent rejected-spot, camera default, blob centroid, no-move/no-remove, and synchronous-inference bugs by design. Coordinate with Dev 2 for asynchronous crop-based class recognition, and with the shared backend adapter for accepted world token IDs. Never mutate world data in CV code. Deliver real camera demo with placement, invalid retry, move, remove, marker partial occlusion and projector-on conditions.

### DETECTION DEV 2 — PERCEPTRON / OBJECT CLASSIFICATION

> Use the official, verified Perceptron SDK and current model/detection API to classify **actual top-down physical bridge/shelter/hospital/food station pieces** in Dev 1's ROI crops. Study the installed SDK/real response shape; no hardcoded imaginary confidence fields, no compile-only SDK response counted as recognition. Reuse official OpenCV/Perceptron repo patterns rather than spinning up an unnecessary object-detection model. Implement async timeouts, unknown class, class evidence fusion, configurable measured confidence thresholds and classification result bound to Dev 1's stable track ID. Collect real test frames/top-view photos and report per-class accuracy and latency with projector on. Return confident observations to shared action adapter, not to the projector directly.

### SHARED INTEGRATION — EXISTING WORLD CORE

> Port the existing real DB, Mapbox-related geospatial assets and `nepal_rasuwa_hot_v1` or verified canonical live scenario, plus `WorldService`, rules, routing/capacity, flood stages, scoring and WebSocket snapshots. Keep one source of truth. Create the narrow physical-observation adapter that maps accepted placed/moved/removed tracks to legacy world actions, handles world versions/rejections/retry/dedup, and publishes a complete live snapshot for UI. Resolve digital START against legacy START-first validation, and verify `snapshot.game`, route board_uv and flood corridors are present on the selected branch. No fake fallback data; errors must be explicit. Capture real world/snapshot before-after evidence for physical bridge placement and timed flood stage.

---

## 14. References and provenance

**Confirmed by team conversation / uploaded audit** (not independently live-verified source code): original repo `aditi-labs/floodshift-`, current real DB and existing Mapbox map, physically printed ArUco tags, Nepal HOT scenario, world rules, NetworkX reachability, ghost bridge, WorldService, game score branch, projector reactions, and earlier failure list.

**Official external implementation resources:**

- OpenCV ArUco board/partial occlusion: https://docs.opencv.org/4.13.0/db/da9/tutorial_aruco_board_detection.html
- OpenCV ArUco detection: https://github.com/opencv/opencv/blob/5.x/doc/tutorials/objdetect/aruco_detection/aruco_detection.markdown
- Perceptron SDK: https://github.com/perceptron-ai-inc/perceptron
- Perceptron agentic detection: https://www.perceptron.inc/blog/introducing-perceptron-agentic-detection

**Revision protocol:** once repository code is cloned and real DB examined, replace every proposed field/path here with verified exact names in `docs/INTEGRATION_CONTRACT.md`. Never silently promote a proposed contract to “implemented.”
