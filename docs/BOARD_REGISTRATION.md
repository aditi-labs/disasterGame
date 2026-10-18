# Board registration

Status on 2026-10-18: software transform and provisional masks implemented; **physical registration unverified**. No board photo, camera feed, marker measurements or projector is available in this workspace.

The checked-in board is the square HOT/OSM geometry from `nepal_rasuwa_hot_v1`. Its 420 × 420 mm dimensions are explicitly provisional. The spec names Mapbox as canonical, but this checkout has no Mapbox implementation. Match the actual print to the source before accepting alignment; do not calibrate one map against another.

| Item | Current value | Confidence |
| --- | --- | --- |
| Board UV | Top-left origin; u right, v down | Verified in source |
| Projector transform | Affine translation, rotation, independent scale, plus 4-corner homography | Unit tested; not physically measured |
| ArUco dictionary | Legacy `DICT_4X4_100` reference | Unverified on current board |
| Marker IDs / centers | 10 at `(0.04,0.04)`, 11 at `(0.96,0.04)`, 12 at `(0.96,0.96)`, 13 at `(0.04,0.96)` | Legacy guesses, not observed markers |
| Keep-out half size | 0.045 UV | Provisional; needs actual marker bounds and quiet zone |
| Calibration storage | Projector browser local storage, key `floodshift.game.projector.calibration.v2` | Software behavior only |

`apps/game/src/game/board.ts` sets `MARKERS_VERIFIED=false`. Black masks are drawn last in physical-overlay mode, after floods, routes, results and registration patterns. They reduce light at provisional positions but cannot guarantee the real tags remain clear until measured. Screen mode draws only provisional marker guides. Pressing Enter records operator confirmation time; it is not an automatic measurement or validation of ArUco registration.

Use this sequence on hardware:

1. Identify the printed map asset, board dimensions and orientation. Record the physical print/source hash and a photo.
2. Lane B measures actual dictionary, marker IDs, four marker corners in board UV, orientation and reprojection error from the real camera. Record them here; update `board.ts` masks and provenance together. Set verification true only after measurement/review.
3. Open `/projector` in a second window of the operator's browser; move it to the projector output. Press `F` there for fullscreen. Use `M` to select overlay mode so printed cartography carries the basemap.
4. Clear the physical tray and marker quiet zones. Click TEST PROJECTOR or press `T` for outlines/reticles. Press `C` to calibrate.
5. Align the projected map against several actual road intersections and crossings, not just the outer corners. Enter saves confirmation; `C` closes tools. Test mode toggles separately; use the operator's close-tools control to close both.
6. Measure residual error at center, corners and all actionable crossings. Re-check after moving either camera or projector. Test actual pieces with projection on; record classifier false positives and marker stability.

| Calibration key | Effect |
| --- | --- |
| Arrow keys | Translate whole image, or selected corner, 1 px |
| Shift + adjustment | 10× step |
| `[` / `]` | Rotate by 0.1° |
| `-` / `=` | Uniform scale |
| `,` / `.` | Horizontal scale |
| `;` / `'` | Vertical scale |
| `1`–`4` | Select TL, TR, BR, BL corner |
| `5` | Return to whole-image adjustment |
| `0` | Reset calibration |
| Enter | Record calibration confirmation |
| `C` | Toggle calibration panel |

Record actual values below after the hardware session. Blank means unmeasured.

| Measurement | Result |
| --- | --- |
| Printed asset/hash, dimensions | Pending team confirmation |
| Camera/device, resolution, lens correction | Pending lane B |
| Dictionary/IDs, measured board corners, orientation | Pending lane B |
| Camera reprojection error | Not measured |
| Projector resolution/transform, board alignment error | Not measured |
| Marker occlusion tolerance with projector on | Not measured |
| Classifier false positives with projector on | Not measured |
