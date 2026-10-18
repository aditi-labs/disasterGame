# UI test evidence

Verified on 2026-10-18 while integrating Sky's UI work with `origin/main` at `cc38a00`. The Master spec, retained backend, simulation, planning, public Python contracts, scenario data and incoming Lane B source are preserved. UI adaptations consume Lane B's nested telemetry and photo-verified marker metadata; no print/world transform is guessed.

| Check | Result |
| --- | --- |
| UI regression suite (`cd apps/game; npm.cmd test`) | **69 passed** across 8 files: prior UI coverage plus nested Lane B telemetry, marker-layout consistency and the physical-projection registration guard |
| Typecheck / production build | Passed. Vite bundles both routes |
| Real-time UI integration (`npm.cmd run test:live`) | Passed cleanly: both React routes mounted against an isolated real backend; 75-second mission plus pause and replay; no mocked HTTP/WebSocket endpoints |
| Launcher / merged dev imports | Initial launcher check passed on 18012/15181, including occupied-port refusal. Merged app rechecked on 18013/15182: both routes, transformed board module and its shared registration JSON import returned HTTP 200 |
| Retained backend suite | 80 passed, 1 failed: `test_hot_build_is_reproducible_and_preserves_all_crossing_states`, the already-reported baseline byte-reproducibility failure |
| Browser screenshots / visual layout | **Not run.** Browser runtime reports no available session. HTTP 200 and React rendering do not validate browser pixels |
| Lane B regression suite (`pytest perception/tests -q`) | **62 passed**, including the actual team board photo checks for IDs/layout/rotation. Centre/size estimates remain unmeasured |
| Physical camera / projector / print | **Not run live here.** A board photo is supplied, but live measured registration and print-to-world alignment remain unavailable |

The live test record is [evidence/ui-live-run.json](evidence/ui-live-run.json). It records timed phase observations, real backend versions/metrics, token sites and WebSocket snapshots. Its execution field explicitly identifies React test rendering; it is not browser or physical demo video. The test launches a fresh ephemeral-port backend so it never resets an existing operator session, and cleans up that process afterward.

The passing run verified:

- START acknowledged reset, digital START and both original population nodes before starting the clock.
- Pause held elapsed time; resume continued the same mission.
- A manual bridge placement, move to another real crossing, removal and retry updated accepted state. A duplicate occupied-site attempt was rejected.
- Shelter, hospital and food station were accepted at their source-defined sites.
- Exactly one `game_clock` surge action was attempted at 50 seconds. `last_stage` was reported, the world remained at stage 1, and the projector displayed FLOOD UPDATE UNAVAILABLE.
- Input closed at 70 seconds; both routes showed results from the confirmed world; the clock finished at 75,000 ms.
- REPLAY reset the actual world to ready and cleared accepted tokens.

For this specific run, the final backend score was **419**. Results showed refuge reachability **16/16 model people**, food needs met **10/16**, medical needs met **3/4**, **1** crossing carrying a reachable route, and unmet need **13/36** versus **36** with no response. These are educational model outputs, not achieved rescue counts. Reachability does not imply enough service capacity: the unresolved summary still reports 6 food, 1 medical and 6 refuge need units unmet.

The first full React run passed its gameplay assertions but exposed delayed WebSocket callbacks during teardown. That cleanup issue was fixed, covered by a regression test, and the full run repeated with a clean exit. Initial sandboxed backend attempts could not access temporary directories; the final backend verification used a repository-local temporary directory with the required access. These setup errors are not included as backend assertion failures.

## Hardware acceptance still outstanding

| Required evidence | Owner / next action |
| --- | --- |
| Canonical printed map / Mapbox reconciliation | Team confirms actual print and source |
| Actual marker centres/size, paper dimensions and live reprojection error | IDs/layout/rotation verified by incoming photo; Lane B supplies ruler measurements/live calibration |
| Landscape print UV → square world UV / print bounds | Shared integration supplies a measured transform; physical projection is held until then |
| Physical placed/moved/lifted lifecycle and tracker reset | Lanes B/C and shared backend agree/implement the current missing contract |
| Second reviewed flood stage | Data owner adds actual stage data; shared review |
| Bridge observation → accepted route change video and matching run log | Hardware team rehearses; Sky captures UI evidence |
| Browser/layout check at operator laptop and projector resolutions | Open both routes, inspect all phases/results and calibration; record screenshots |
| Projector-on classifier precision/recall and full-chain latency | Lanes B/C measure actual frames; no values claimed here |
| Multiple consecutive hardware runs, rejected retry and occlusion | Whole team |

Palette tests check source colors against the old bridge HSV window (OpenCV hue 17–36, saturation ≥58/255, value ≥59/255). They do not establish camera safety for blended projected light on paper or the new classifier. Homography tests establish software corner mapping, not measured board alignment.
