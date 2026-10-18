# UI test evidence

Verified on 2026-10-18. The retained world rules, simulation, planning, scoring and scenario data are preserved. The gateway now accepts camera lifecycle events; the Perceptron ClassifierPort connects to the existing OpenCV tracker. The normal laptop flow is START-only, with O opening tools. The projector uses compact narrative, localized cues, measured piece keep-outs and a runtime print/world transform. The old intro card/styles are removed; the seven-frame prologue remains omitted. No actual calibration values or physical detections are fabricated.

| Check | Result |
| --- | --- |
| UI regression suite (`cd apps/game; npm.cmd test`) | **78 passed** across 9 files, including physical feedback, runtime measured mapping, paper aspect, marker/piece masks and confirmed final-state capture |
| Typecheck / production build | Passed. Vite bundles both routes |
| Real-time UI integration (`npm.cmd run test:live`) | Passed: a real 75-second mission against an isolated backend, with controlled PhysicalObservation inputs and test-only calibration. Pending/place/move/remove reach the projector; pause/resume and finalization acknowledge the backend. No mocked HTTP/WebSocket endpoints; no live detections claimed |
| Launcher / merged dev imports | Initial launcher check passed on 18012/15181, including occupied-port refusal. Merged app rechecked on 18013/15182: both routes, transformed board module and its shared registration JSON import returned HTTP 200 |
| Backend + perception suite (`python -X utf8 -m pytest tests perception/tests -q`) | **167 passed, 1 failed**. The only failure is the existing `test_hot_build_is_reproducible_and_preserves_all_crossing_states` manifest byte/hash comparison; all new integration tests pass |
| Browser screenshots / visual layout | **Not run.** Browser runtime reports no available session. HTTP 200 and React rendering do not validate browser pixels |
| Projector SVG visual inspection (`npm.cmd run render:projector`) | Four actual component renders inspected: idle, crossing before/after, results. Corrected a flood-rim mask that filled the river corridor with bright cyan. These are resvg rasterizations, not browser screenshots |
| Perception suite | **74 passed**: existing actual board-photo/synthetic-camera tests plus SDK-contract parsing, distinct-frame agreement, camera-thread reset feedback, backend pause/resume resynchronization and a synthetic-frame → ClassifierPort → HIGH-band check without invented model confidence |
| Physical gateway integration | **13 passed** against the real reducer: place/move/remove, invalid correction, duplicate handling, pending observations, fresh registration/epoch, pause/cutoff/finalization, WebSocket feedback, footprint masks and landmark validation |
| SDK / launcher checks | Installed official Perceptron 0.4.0, checked its public signatures and imported the connected factory without credentials. Paid API calls and live classifier precision/recall were not run. CLI and PowerShell syntax checked |
| Physical camera / projector / print | **Not run live here.** A board photo is supplied, but live measured registration and print-to-world alignment remain unavailable |

The live test record is [evidence/ui-live-run.json](evidence/ui-live-run.json). It records timed phase observations, real backend versions/metrics, token sites and WebSocket snapshots. Its execution field explicitly identifies React test rendering; it is not browser or physical demo video. The test launches a fresh ephemeral-port backend so it never resets an existing operator session, and cleans up that process afterward.

The passing run verified:

- The laptop initially had exactly one START button; O exposed fallback tools without remounting the mission controller.
- START acknowledged reset, digital START and both original population nodes before starting the clock.
- Pause held elapsed time; resume continued the same mission.
- Controlled physical pending/place/move/remove inputs traversed the real HTTP adapter and reached the projector. Manual correction, removal and retry still worked; an occupied-site duplicate was rejected. Controlled observations are explicitly labelled test input with replay provenance.
- Shelter, hospital and food station were accepted at their source-defined sites.
- Exactly one `game_clock` surge action was attempted at 50 seconds. `last_stage` was reported, the world remained at stage 1, and the projector displayed FLOOD UPDATE UNAVAILABLE.
- UI and backend physical input closed at 70 seconds; finalization captured one accepted snapshot for both windows. The clock finished at 75,000 ms.
- REPLAY reset the real world, accepted tokens and backend epoch. A separate test verifies status feedback resets camera bindings on its processing thread.

Visual evidence is in [evidence/projector/manifest.json](evidence/projector/manifest.json): [idle](evidence/projector/idle.png), [before bridge](evidence/projector/crossing-before.png), [after bridge](evidence/projector/crossing-after.png), [results](evidence/projector/results.png). The before/after pair deliberately starts with the three real facilities already placed so the bridge's computed route improvement is visible; those fixture scenes are not a recording of phase order. SVG sources are saved beside the PNGs. All geography and model values come from the retained reducer and scenario.

For this specific run, the final backend score was **419**. Results showed refuge reachability **16/16 model people**, food needs met **10/16**, medical needs met **3/4**, **1** crossing carrying a reachable route, and unmet need **13/36** versus **36** with no response. These are educational model outputs, not achieved rescue counts. Reachability does not imply enough service capacity: the unresolved summary still reports 6 food, 1 medical and 6 refuge need units unmet.

The first full React run passed its gameplay assertions but exposed delayed WebSocket callbacks during teardown. That cleanup issue was fixed, covered by a regression test, and the full run repeated with a clean exit. Initial sandboxed backend attempts could not access temporary directories; the final backend verification used a repository-local temporary directory with the required access. These setup errors are not included as backend assertion failures.

## Hardware acceptance still outstanding

| Required evidence | Owner / next action |
| --- | --- |
| Canonical printed map / Mapbox reconciliation | Team confirms actual print and source |
| Actual marker centres/size, paper dimensions and live reprojection error | IDs/layout/rotation verified by incoming photo; Lane B supplies ruler measurements/live calibration |
| Landscape print UV → square world UV / print bounds | Tooling and shared mapping path implemented; team supplies actual measured landmark pairs and verifies projection |
| Physical placed/moved/lifted lifecycle and tracker reset | Software contract tested; verify actual pieces, occlusion and replay on hardware |
| Second reviewed flood stage | Data owner adds actual stage data; shared review |
| Bridge observation → accepted route change video and matching run log | Hardware team rehearses; Sky captures UI evidence |
| Browser/layout check at operator laptop and projector resolutions | Open both routes, inspect all phases/results and calibration; record screenshots |
| Projector-on classifier precision/recall and full-chain latency | Lanes B/C measure actual frames; no values claimed here |
| Multiple consecutive hardware runs, rejected retry and occlusion | Whole team |

Palette tests check source colors against the old bridge HSV window (OpenCV hue 17–36, saturation ≥58/255, value ≥59/255). They do not establish camera safety for blended projected light on paper or the new classifier. Homography tests establish software corner mapping, not measured board alignment.
