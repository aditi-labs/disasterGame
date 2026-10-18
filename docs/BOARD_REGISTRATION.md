# Board registration: real ArUco IDs and measured board positions

Owner: Detection Dev 1 (Lane B). Source of truth for values: the **physical board** under the
**actual camera**, measured with `python -m perception.service --calibrate`. Spec references:
FLOODSHIFT_MASTER_BUILD_SPEC section 2 (retain existing markers), 6.2–6.4, 8 (asset inventory),
10 (no fake data).

## Current status: IDs and layout verified from a photo; positions still unmeasured

On 2026-10-18 the team supplied a phone photo of the real printed map with its markers
(`perception/tests/fixtures/real_board_photo_2026-10-18_upright_1400.jpg`, final landscape orientation). Running the
perception detector on it verified the first four rows below; the rest are estimates
from that single perspective photo and still need a ruler.

| Item | Value in `perception/board_registration.json` | Verified on the physical board? | Source |
|---|---|---|---|
| Dictionary | 4X4 family; `DICT_4X4_50` configured (all 4X4 dictionaries decode these IDs) | **Yes** | Photo 2026-10-18, detector scan over every OpenCV dictionary |
| Marker IDs | 10, 11, 12, 13 | **Yes** | Photo; ID 12 (bottom-left) decodes only with the padded-frame retry because its paper touched the image border |
| Corner layout (upright map) | TL = 10, TR = 11, **BR = 13, BL = 12** | **Yes** | Photo. The legacy audit assumed BR = 12, BL = 13: the real board has them swapped |
| Printed rotation | 0 deg for all four in the upright frame | **Yes** | Photo: all four patterns share one rotation, equal to the map text's rotation |
| Upright frame | the team's final landscape orientation: labels readable, river enters from the top; u right, v down, origin paper top-left | **Yes** (orientation) | Photo as supplied; river/confluence shape matches the scenario's board-UV data orientation |
| Marker centres (UV) | 10 (0.065, 0.067), 11 (0.944, 0.067), 13 (0.944, 0.918), 12 (0.065, 0.918) | **No, photo estimate** | Rectified photo; the bottom inset is least certain (paper edge cut off at the photo border) |
| Marker edge length | `null`; estimate 0.132 x paper height (~60 mm if the paper is 453 mm tall) | **No** | Rectified photo; set it after measuring to enable corner-based registration |
| Board (paper) size | 594 x 453 mm **assumed** (aspect 0.763 measured, absolute size not) | **No** | The print is landscape; A-series width assumed only to give mm gates a scale |
| Reprojection error | not measured live | – | – |

**Cross-lane flag (shared integration / Sky):** the physical print is landscape (height about
0.76 of width) while `scenarios/nepal_rasuwa_hot_v1/data/scenario.json` describes a 420 x 420
square board frame, and the print's visible extent differs from the square export (the main
river leaves the print at the right edge, not the bottom-right corner). Perception reports
UV in the **print** frame defined above. The transform print-UV -> world `board_uv` / geo is
owned by the shared lane and is **not** the identity; it should come from the Mapbox print
bounds, not from stretching the square frame onto the paper.

Until the measured table below is filled from a live `--calibrate`, the service prints
`registration NOT VERIFIED ON BOARD` in its status and the operator status line.

## How to measure (15 minutes, at the venue, projector off then on)

1. Mount the camera in its final position. Start DroidCam (or the webcam). Find it:
   ```
   .venv/bin/python -m perception.service --list-cameras
   ```
   DroidCam with no virtual-camera driver: use `--source http://<phone-ip>:4747/video`.
2. Hold the map upright (labels readable, river entering from the top). Measure with a ruler,
   in millimetres: the paper width and height, the centre of each black marker square from
   the paper's top-left corner, and the edge length of the black square. Convert centres to
   UV by dividing x by the paper width and y by the paper height. Keep all four markers at
   least a marker's width away from the camera frame edge.
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
