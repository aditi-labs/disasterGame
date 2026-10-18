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
.venv/bin/python -m perception.service --classifier perception.classifier_port:create_classifier   # Dev 2's Perceptron classifier
.venv/bin/python -m perception.service --control-port 8011                                           # operator/adapter control API
```

`--observe-url` must point at the **shared observation adapter**. The retained gateway's
`/perception/observe` takes the legacy `ObjectObservation` and turns every confirmed
observation into a placement; the service refuses that URL (see `docs/INTEGRATION_CONTRACT.md`).

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

## Lane C seam (Dev 2's classifier)

`perception/classifier_port.py` wraps Dev 2's `PieceClassifier` in the `ClassifierPort`
interface, so there is exactly one tracker, one lifecycle and one emitter of
`PhysicalObservation` (spec 1 and 6.6). Through the port:

- model results (`class_source == "perceptron"`) pass through with their confidence;
- colour-fallback results keep their class as a labelled hint but their confidence is
  withheld, so they can never reach HIGH on their own (spec 5: never fabricate a model
  confidence; spec 7.9: degraded, not pretend);
- valid-but-unknown answers leave the track asking again.

`perception/fusion.py` (Dev 2) carries its own `TrackedPiece` lifecycle and observation
emitter. That is a second tracker stack, which the spec forbids, and it currently does not
import (it expects fields `PhysicalObservation` does not have). It is not used by the
service; the port above is the integration path. Flagged for Lane C review.

## Control API (operator / adapter)

`--control-port 8011` serves `GET /status` and `POST /control/{reset, reference,
clear_pending, recalibrate, pause, feedback, operator_class, reemit, exclusions}`
(`perception/control.py`). This is the owner-side reset the shared contract asked for:
the UI's RESET/REPLAY should call `/control/reset` so track IDs, world-token bindings,
pending candidates and caches are cleared with the world (spec 5, 6.10). Commands are
applied on the next frame.

## DroidCam helpers

`perception.camera.list_cameras()`, `connect_droidcam(ip=..., port=4747)` (Wi-Fi MJPEG),
`connect_droidcam(use_usb=True)` (after `adb forward tcp:4747 tcp:4747`) or
`connect_droidcam(index=...)` (DroidCam client's virtual camera). The returned worker has
`read_frame()` and `stream_frames()`.

## Status (for the operator status line)

`PerceptionService.status()` / `--status-url` posts flat gateway keys (`mode`, `calibration`,
`perceptron`, `objects_tracked`; a photo-estimated registration reports `valid_unmeasured`,
never `calibrated`) plus camera health (source, size, fps, frame
age, reconnects), registration (valid/held/degraded, markers used vs expected, RMS in UV and
px, `registration_verified`), reference state and changed fraction, tracks, classifier
status, sink counters, processing time, warnings.

## Latency and accuracy knobs (added after the first friend's-laptop run)

- **Time-based stability.** A track confirms after `tracker.stable_ms` (350 ms) of stillness and
  at least `stable_frames` (4) frames, so a 10 fps laptop confirms as fast as a 30 fps one.
  Occlusion grace is likewise `occlusion_grace_ms` (700 ms) *and* `occlusion_grace_frames`.
- **Median position filter.** `tracker.position_filter = "median"` makes the emitted centre
  immune to a single jittery frame.
- **ArUco cadence.** `board.redetect_every_n_frames` reuses the last registration between
  detections; with `adaptive_cadence` the service raises it (up to 3) when the loop falls
  behind `target_fps` and lowers it again when it recovers. The operator line shows `every Nf`.
- **Classifier crops.** ROIs are rotated so the piece's long axis is horizontal and downscaled
  to `service.roi_max_px` (320) before Perceptron sees them: faster upload, consistent view.
  `classifier_max_inflight` (2) bounds outstanding model calls; extra tracks simply ask again.
- **Timing telemetry.** Status carries `timing` with p50/p95 per stage (aruco, warp,
  candidates, tracker, classify, total) and the port reports classifier latency p50/p95.
  Tune from these numbers on a `--record` replay, not from feel.
- **`--fast` preset** for weak laptops: 1.0 px/mm warp (default is 1.5), ArUco every 2 frames, warp window off,
  sparse recording, 256 px ROIs.

## Tuning

Starting thresholds live in `perception/config.py`. Spec 5 requires tuning against recorded
live frames of the real board with the projector on and off, not against synthetic hit rates.
Record with `--record`, replay with `--source <dir>`, and keep measured precision/recall and
latency in `docs/BOARD_REGISTRATION.md` / the team's test-evidence document.

## Hardware evidence still required (spec "Dev 1 done when")

- [x] Marker dictionary, IDs 10-13, corner layout and rotation verified from the 2026-10-18 board photo
- [ ] Real board registration measured with a ruler and written by `--calibrate` (`docs/BOARD_REGISTRATION.md` table)
- [ ] Place / invalid-retry / move / remove demonstrated on the physical board, recorded
- [ ] Partial marker occlusion by hand and by piece, recorded, no UV jump
- [ ] Projector on: no extra candidates from overlays; `G` structure gate evaluated
- [ ] Camera unplug / DroidCam drop: health shows DOWN, loop keeps running, no events invented
