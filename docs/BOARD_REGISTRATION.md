# Board registration: real ArUco IDs and measured board positions

Owner: Detection Dev 1 (Lane B). Source of truth for values: the **physical board** under the
**actual camera**, measured with `python -m perception.service --calibrate`. Spec references:
FLOODSHIFT_MASTER_BUILD_SPEC section 2 (retain existing markers), 6.2–6.4, 8 (asset inventory),
10 (no fake data).

## Current status: UNVERIFIED

| Item | Value in `perception/board_registration.json` | Verified on the physical board? | Source |
|---|---|---|---|
| Dictionary | `DICT_4X4_100` | **No** | Legacy `backend/calibration/board.py` in `aditi-labs/floodshift-` |
| Marker IDs | 10 (top-left), 11 (top-right), 12 (bottom-right), 13 (bottom-left) | **No** | Same legacy file; the spec calls these "tentative" |
| Marker centres (UV) | (0.04, 0.04), (0.96, 0.04), (0.96, 0.96), (0.04, 0.96) | **No** | Same legacy file |
| Marker edge length | `null` (not measured) | **No** | Nobody has measured it; centres-only mode is in use until set |
| Marker printed rotation | 0 deg for all | **No** | Assumption; `--calibrate` key `O` solves it |
| Board size | 420 x 420 mm, UV origin top-left | Provisional | `scenarios/nepal_rasuwa_hot_v1/data/scenario.json` (`dimensions_provisional: true`) |
| Reprojection error | not measured | – | – |

No repository (old or new) contains a camera frame of the real board with its markers. The
only real-hardware image is a photo of the yellow bridge piece on a plain background
(`perception/tests/fixtures/README.md`). Until the table below is filled from a live
measurement, the service runs but prints `registration NOT VERIFIED ON BOARD` in its
status and the operator status line.

## How to measure (15 minutes, at the venue, projector off then on)

1. Mount the camera in its final position. Start DroidCam (or the webcam). Find it:
   ```
   .venv/bin/python -m perception.service --list-cameras
   ```
   DroidCam with no virtual-camera driver: use `--source http://<phone-ip>:4747/video`.
2. Measure with a ruler, in millimetres from the board's top-left corner, the centre of each
   printed marker, and the edge length of the black marker square. Convert to UV by dividing
   by 420 (or the measured board size).
3. Run the calibrate flow with the measured values. Example with made-up placeholders that
   **must be replaced by your ruler readings**:
   ```
   .venv/bin/python -m perception.service --calibrate \
     --marker-size-mm <edge_mm> \
     --marker 10:<u>:<v> --marker 11:<u>:<v> --marker 12:<u>:<v> --marker 13:<u>:<v> \
     --measured-by "<name>"
   ```
   The window lists every dictionary that finds markers and the IDs each finds. If the
   configured dictionary finds nothing but another one does, the board was printed with that
   family: pass `--config` with `"board": {...}` or edit `aruco.dictionary` and re-run. If the IDs
   on the board are not 10–13, add `--marker <id>:<u>:<v>` for the real IDs and remove the
   stale ones from the JSON.
4. Press `O` to solve each marker's printed rotation, then `W` to write. The file is rewritten
   with `status: MEASURED`, `verified: true` for every marker used, and a `measured` block
   (date, camera source, frame size, RMS error in UV and px, per-marker RMS, detected IDs).
5. Copy the `measured` block into the table below, and record a 20-second empty-board
   recording for regression: `--record assets/live_captures/<date>_empty_board`.
6. Repeat the RMS check with the projector on (idle title screen) and note any difference.

Acceptance (spec 5/6): RMS reprojection error well under the pad tolerance of 0.025 UV
(10.5 mm). Target under 0.005 UV (about 2 mm). With `marker_size_mm` set, registration
survives one or two occluded markers; without it all four must stay visible.

## Measured values (fill from the written `measured` block; do not type values by hand)

| Field | Value |
|---|---|
| measured_on | – |
| measured_by | – |
| camera_source | – |
| frame_size | – |
| dictionary | – |
| marker IDs used | – |
| marker_size_mm | – |
| reprojection_rms_uv / px | – |
| per-marker RMS (uv) | – |
| detected_ids_all (including non-board IDs) | – |
| projector on: RMS | – |
| recording path | – |

## Rules

- Board markers are calibration references, never playable objects. The service dilates their
  footprints by 6 mm and excludes them from candidate detection.
- The camera-to-board homography is separate from the projector-to-board transform (UI lane).
- A registration file with `status: UNVERIFIED_TENTATIVE` must never be reported as calibrated to judges.
