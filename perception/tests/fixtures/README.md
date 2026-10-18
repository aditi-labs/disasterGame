# Perception test fixtures

| File | Provenance | What it is | What it is NOT |
|---|---|---|---|
| `real_bridge_piece_composite_1280x720.jpg` | Copied from `aditi-labs/floodshift-` `tests/fixtures/board_frames/bridge_camera_1280x720.jpg` (commit `c5e13fb`, 2026-10-18) | A photograph of the **actual printed yellow bridge piece** (`hardware/tokens/bridge/photo_top.jpg`) that the original team downscaled and pasted on a plain grey 1280x720 canvas | A camera frame of the board. It contains **no ArUco markers** and no map print. It is used only to check the measured geometry/colour of the real piece. |

There is **no recorded frame of the real board with its ArUco markers in any repository yet**.
Record one with `python -m perception.service --record assets/live_captures/<run>` over the
physical board; recordings go in `assets/live_captures/` (gitignored) and are referenced from
`docs/BOARD_REGISTRATION.md` with date, camera and operator.

## Real board photo (added 2026-10-18)

| File | Provenance | What it is |
|---|---|---|
| `real_board_photo_2026-10-18_portrait_1400.jpg` | Phone photo supplied by the team on 2026-10-18 (original 3213x5712), downscaled to 1400 px tall | The **actual printed map with its four ArUco markers**, lying on carpet, photographed with the map rotated 90 deg clockwise (portrait). Perspective, not rectified. |

Verified from it (see `docs/BOARD_REGISTRATION.md`): 4X4 dictionary family, IDs 10/11/12/13, their corner layout, identical printed rotation. **Not** verified: millimetre positions, marker size, paper size.
