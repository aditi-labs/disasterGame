# Perception test fixtures

| File | Provenance | What it is | What it is NOT |
|---|---|---|---|
| `real_bridge_piece_composite_1280x720.jpg` | Copied from `aditi-labs/floodshift-` `tests/fixtures/board_frames/bridge_camera_1280x720.jpg` (commit `c5e13fb`, 2026-10-18) | A photograph of the **actual printed yellow bridge piece** (`hardware/tokens/bridge/photo_top.jpg`) that the original team downscaled and pasted on a plain grey 1280x720 canvas | A camera frame of the board. It contains **no ArUco markers** and no map print. It is used only to check the measured geometry/colour of the real piece. |

There is **no recorded frame of the real board with its ArUco markers in any repository yet**.
Record one with `python -m perception.service --record assets/live_captures/<run>` over the
physical board; recordings go in `assets/live_captures/` (gitignored) and are referenced from
`docs/BOARD_REGISTRATION.md` with date, camera and operator.
