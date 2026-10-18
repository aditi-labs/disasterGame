# Operator run of show

Start with the [README](../README.md) launcher. Use a second window of the **same browser profile and origin** for `/projector`; the laptop and a different browser/device do not share the clock channel. `/operator` normally has one START button. Press **O** to reveal or close technical controls in place; this preserves the running clock. `/operator?tools=1` opens the technical view on initial load. Keep exactly one operator window open, and do not reload it during a run.

For screen rehearsal, LOAD LIVE SCENARIO and check world/WS is live with the expected scenario ID. Open `/projector?mode=screen` in the same browser, or press `M` on the projector to show the source map. Physical overlay currently shows BOARD REGISTRATION REQUIRED because Lane B's landscape print differs from the square world extent; no measured print-to-world transform is available. Do not use pixel keystone or stretching to conceal that mismatch. After shared integration provides the mapping, confirm the print and measured marker registration using [BOARD_REGISTRATION](BOARD_REGISTRATION.md), then test/calibrate against hardware. Camera/ArUco/Perceptron statuses come from the perception service; a healthy world does not imply working detection. CALIBRATE CAMERA opens reported status; lane B starts calibration externally.

Place the four real pieces in a tray outside the active board area. No physical START or person piece is needed. Clear old pieces before reset/replay so the external tracker does not re-place them. For a manual rehearsal, use the operator controls; they call the real reducer and carry manual provenance.

The current data has only one flooded stage. Tell the presenter before rehearsal: START activates it; the scheduled 50-second advance will report FLOOD UPDATE UNAVAILABLE. The data owner must supply a reviewed second stage for the intended surge demo. The incoming photo verifies marker IDs/layout/rotation (bottom-right 13, bottom-left 12); centre/size measurements, the print-to-world transform and projector alignment remain hardware gates.

START leads directly into gameplay; the seven-frame artwork prologue is omitted at the user's request. START (or START GAME in technical controls) resets the authoritative world, places digital START and the two existing population inputs, then starts 75 seconds. A rejected setup action keeps the clock idle. If setup fails, inspect the reason, reset, and retry. The legacy optional transition card remains available in technical controls, outside the game clock.

| Mission time | Operator/player action | Expected truthful output |
| --- | --- | --- |
| 0–10 s | Orient the player | Warning, actual stage-1 closure state, population point cues |
| 10–30 s | Place bridge on a lit crossing; manual fallback can select/click a real pad | Accepted token halo; only real reachability/route changes glow mint. East crossing restores access in this scenario; other crossings can be accepted without improving access |
| 30–50 s | Place shelter or hospital; food optional | Actual facility capacity and returned service paths; unmet needs may remain after placement |
| 50–70 s | Respond with remaining pieces or move/remove | Exactly one timed advance request. Current bundle rejects `last_stage`; map remains at the accepted stage and reports unavailable |
| 70–75 s | Stop moving pieces | UI input closes. Results wait for outstanding UI acknowledgments/snapshots, then capture one confirmed state for both windows |
| 75 s onward | Discuss outcome; DOWNLOAD RUN RECORD | Clock finishes; results remain. START begins another run, or technical REPLAY resets to ready |

PAUSE banks elapsed mission time and suspends automatic events; manual world actions can still be accepted before the 70-second cutoff. RESUME requires a live world connection. RECALIBRATE while paused opens projector tools and camera status without resetting the world. Manual flood advance remains a real action and does not replace the one-time scheduled request.

For corrections, select the piece and site then PLACE, or click a site on the operator map. Map pads also accept keyboard Enter/Space. To move, select a placed token and a compatible destination then MOVE. MANUAL REMOVE requires confirmation. Invalid requests show backend reasons and do not create routes. Pending detection outlines may be cleared without deleting an accepted token.

On connection loss, stop physical interaction and inspect the operator status. The projector keeps the last confirmed map and shows a warning; it freezes clock extrapolation after the operator heartbeat is lost. Reconnect, LOAD LIVE SCENARIO as needed and verify versions before resuming. A failed RESET retains the local mission state and asks for retry; it does not claim a successful replay. No offline demo state is substituted.

END & SHOW RESULTS ends the local clock early and reports that fact. RESET GAME requires confirmation. REPLAY resets world, clock and UI pending/effect state; it does **not** reset a separate perception process's track bindings. Coordinate that reset with lane B. DOWNLOAD RUN RECORD includes run/session timestamps, geometry fingerprint, versions, action provenance, surge response and final model metrics; camera events are visible in the operator log but are not a complete server event export.

Lane B can report status using `.venv/Scripts/python.exe -m perception.service --source auto --status-url http://localhost:8010/perception/status`. Calibrate first using its documented CLI. Its new PhysicalObservation payload is not accepted directly by the legacy gateway endpoint; the shared adapter must map frames, lifecycle, class names and track bindings before automated world actions. The UI displays nested status without claiming that adapter is complete.

After a hardware rehearsal, attach the real video and corresponding run export to [TEST_EVIDENCE](TEST_EVIDENCE.md). Include failed attempts, calibration measurements and latency, as observed. The current automated React evidence is not a physical demo recording.
