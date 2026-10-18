# `perception/` — FloodShift Lane B (OpenCV camera, ArUco, tracking)

Owner: Detection Dev 1. Spec: `FLOODSHIFT_MASTER_BUILD_SPEC (2).md` sections 3, 5, 6, 10.
This package owns only what the camera observes. It never mutates world state, never
routes, never scores, and never invents a class. Classification is Lane C's
(`ClassifierPort`); world actions are the shared adapter's.

## Setup

```
python -m venv .venv
.venv/bin/pip install -r perception/requirements.txt
.venv/bin/python -m pytest perception/tests -q
```

## Run

```
.venv/bin/python -m perception.service --list-cameras
.venv/bin/python -m perception.service --calibrate                   # measure the real board (see docs/BOARD_REGISTRATION.md)
.venv/bin/python -m perception.service --source auto --jsonl runs/obs.jsonl
.venv/bin/python -m perception.service --source http://192.168.1.20:4747/video      # DroidCam MJPEG
.venv/bin/python -m perception.service --source 1 --record assets/live_captures/run1  # record evidence
.venv/bin/python -m perception.service --source assets/live_captures/run1/frames      # replay it
.venv/bin/python -m perception.service --observe-url http://localhost:8000/<adapter> --status-url http://localhost:8000/perception/status
.venv/bin/python -m perception.service --classifier perception.perceptron_adapter:create_classifier   # Dev 2 plug-in
```

**DroidCam.** On macOS DroidCam appears either as a virtual camera (an index from
`--list-cameras`) or, with no driver, through its MJPEG URL. Both work. `--source auto`
probes indices 0..7 and picks the first one that delivers frames at the requested size.

**Operator keys** (debug window, operator laptop only, never projected): `Q` quit, `R`
re-capture the empty-board reference, `C` recalibrate (drop held registration), `N` new
session (reset tracks, bindings, caches), `P` pause, `X` clear pending candidates, `E`
re-emit the latest still track (operator retry), `S` save frame to `assets/live_captures/`,
`W` warp view, `M` change mask, `G` projector-safe structure gate.

## Pipeline

```
camera thread (latest frame only)           perception/camera.py
  -> optional undistortion                  perception/intrinsics.py
  -> ArUco detect + homography (px->UV)     perception/board_aruco.py   (RMS error, hold/grace, occlusion guard)
  -> top-down warp of the board plane       perception/geometry.py
  -> reference-based candidates in mm       perception/candidate_regions.py (markers + projected UI excluded)
  -> persistent tracks + lifecycle          perception/tracker.py
  -> footprint UV (+ parallax correction)   perception/geometry.py
  -> confidence band                        perception/confidence.py
  -> PhysicalObservation                    perception/events.py
  -> non-blocking sinks (jsonl/http/cb)     perception/sinks.py
ROI crops for Lane C ------------------->   ClassifierPort.submit(ROIRequest), results via poll()
```

## Observation contract (spec section 5, proposal)

Every event is a `PhysicalObservation` JSON object:

| Field | Meaning |
|---|---|
| `event_id` | deterministic idempotency key per (session, track, lifecycle, emission) |
| `session_id` | reset on `N` / `reset_session()` |
| `track_id` | camera track identity (`t1`, `t2`, ...). **Not** a world token ID |
| `piece_class` | `bridge`/`shelter`/`hospital`/`food_station` or `null` when not verified |
| `lifecycle` | `candidate` (pending outline only), `placed`, `moved`, `removed`, `lost` |
| `board_uv` | `{u,v}` 0..1 after ArUco homography, `null` when the board is not registered |
| `orientation_deg` | long-axis angle on the board, optional |
| `detection_confidence` | Lane C's reported confidence passed through, else `null` |
| `localization_confidence` | local geometric quality (reprojection RMS, jitter, edge distance, hold) |
| `confidence_band` | `high` / `review` / `reject` (see `confidence.py`) |
| `observed_at_ms`, `source` | capture time; `live_camera` or `recording` |
| `class_source`, `class_confidence` | who said the class (`perceptron`, `operator`, ...) |
| `camera_px`, `previous_track_id`, `geometry`, `appearance`, `frame_provenance`, `reason` | debug and fusion evidence |

Rules the adapter can rely on: `placed` is emitted once per stable placement; `moved` only
for tracks the adapter has bound (`handle_adapter_feedback({"track_id", "accepted":true,
"world_token_id"})`); a rejected track that is moved and settles re-emits `placed`; `removed`
comes only after the occlusion grace; nothing is emitted while the board registration is
lost. Only `high` should ever be auto-committed; `review` is for the pending cue and operator
manual actions; `reject` is for diagnostics.

## Status (for the operator status line)

`PerceptionService.status()` / `--status-url` posts: camera health (source, size, fps, frame
age, reconnects), registration (valid/held/degraded, markers used vs expected, RMS in UV and
px, `registration_verified`), reference state and changed fraction, tracks, classifier
status, sink counters, processing time, warnings.

## Tuning

Starting thresholds live in `perception/config.py`. Spec 5 requires tuning against recorded
live frames of the real board with the projector on and off, not against synthetic hit rates.
Record with `--record`, replay with `--source <dir>`, and keep measured precision/recall and
latency in `docs/BOARD_REGISTRATION.md` / the team's test-evidence document.

## Hardware evidence still required (spec "Dev 1 done when")

- [ ] Real board registration measured and written (`docs/BOARD_REGISTRATION.md` table)
- [ ] Place / invalid-retry / move / remove demonstrated on the physical board, recorded
- [ ] Partial marker occlusion by hand and by piece, recorded, no UV jump
- [ ] Projector on: no extra candidates from overlays; `G` structure gate evaluated
- [ ] Camera unplug / DroidCam drop: health shows DOWN, loop keeps running, no events invented
