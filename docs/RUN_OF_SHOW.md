# Operator run of show

Start with the [README](../README.md) launcher. Use a second window of the **same browser profile and origin** for `/projector`; the laptop and a different browser/device do not share the clock channel. `/operator` normally has one START button. Press **O** to reveal or close technical controls in place; this preserves the running clock. `/operator?tools=1` opens the technical view on initial load. Keep exactly one operator window open, and do not reload it during a run.

For screen rehearsal, use the technical controls to check world/WS and scenario identity, then open `/projector?mode=screen`. For physical play, follow [PHYSICAL_INTEGRATION](PHYSICAL_INTEGRATION.md), measure the markers and map landmarks, restart the backend, and verify `/projection/registration` reports ready. Start the launcher with `-WithPerception` to connect OpenCV, the Perceptron ClassifierPort and the physical gateway. Pixel keystone does not replace map registration. Camera/ArUco/Perceptron badges come from service telemetry; a healthy world does not imply working detection.

Place the four real pieces in a tray outside the active board area. No physical START or person piece is needed. Clear old pieces before reset/replay so the external tracker does not re-place them. For a manual rehearsal, use the operator controls; they call the real reducer and carry manual provenance.

The current data has only one flooded stage. Tell the presenter before rehearsal: START activates it; the scheduled 50-second advance will report FLOOD UPDATE UNAVAILABLE. The data owner must supply a reviewed second stage for the intended surge demo. The incoming photo verifies marker IDs/layout/rotation (bottom-right 13, bottom-left 12); centre/size measurements, the print-to-world transform and projector alignment remain hardware gates.

START leads directly into gameplay; the seven-frame artwork prologue and old intro card are omitted. START resets the authoritative world, places digital START and the two existing population inputs, opens a backend physical-input run, then starts 75 seconds. A rejected setup action keeps the clock idle. If setup fails, inspect the reason, reset, and retry.

| Mission time | Operator/player action | Expected truthful output |
| --- | --- | --- |
| 0–10 s | Orient the player | Warning, actual stage-1 closure state, population point cues |
| 10–30 s | Place bridge on a lit crossing; manual fallback can select/click a real pad | Accepted token halo; only real reachability/route changes glow mint. East crossing restores access in this scenario; other crossings can be accepted without improving access |
| 30–50 s | Place shelter or hospital; food optional | Actual facility capacity and returned service paths; unmet needs may remain after placement |
| 50–70 s | Respond with remaining pieces or move/remove | Exactly one timed advance request. Current bundle rejects `last_stage`; map remains at the accepted stage and reports unavailable |
| 70–75 s | Stop moving pieces | UI and backend physical input close. Closing under the mutation lock captures one final snapshot for both windows |
| 75 s onward | Discuss outcome; DOWNLOAD RUN RECORD | Clock finishes; results remain. START begins another run, or technical REPLAY resets to ready |

PAUSE/RESUME first acknowledges the backend physical-input gate, then banks/resumes the local clock. Automatic events pause; manual corrections remain available before 70 seconds. A failed acknowledgment displays a notice and retains the clock state. RECALIBRATE opens projector tools and camera status without resetting the world. Manual flood advance remains a real action and does not replace the scheduled request.

For corrections, select the piece and site then PLACE, or click a site on the operator map. Map pads also accept keyboard Enter/Space. To move, select a placed token and a compatible destination then MOVE. MANUAL REMOVE requires confirmation. Invalid requests show backend reasons and do not create routes. Pending detection outlines may be cleared without deleting an accepted token.

On connection loss, stop physical interaction and inspect the operator status. The projector keeps the last confirmed map and shows a warning; it freezes clock extrapolation after the operator heartbeat is lost. Reconnect, LOAD LIVE SCENARIO as needed and verify versions before resuming. A failed RESET retains the local mission state and asks for retry; it does not claim a successful replay. No offline demo state is substituted.

END & SHOW RESULTS ends the clock early and finalizes the backend run. RESET/REPLAY resets the world, clock, effects and backend bindings, and changes the world epoch. The camera learns that epoch through its next status acknowledgment and clears tracks on its processing thread; old queued events are rejected. Keep pieces off the map until that reset is reflected in status. DOWNLOAD RUN RECORD includes the captured final version/metrics; camera JSONL recording supplies complete observation evidence.

Use `perception.fusion:create_classifier` with both `--observe-url http://localhost:8010/perception/physical` and `--status-url http://localhost:8010/perception/status`. The launcher supplies these flags with `-WithPerception`. Leave the legacy `/perception/observe` endpoint for old clients. Check real place/move/remove/rejection feedback and actual graph consequences before the hardware demo.

After a hardware rehearsal, attach the real video and corresponding run export to [TEST_EVIDENCE](TEST_EVIDENCE.md). Include failed attempts, calibration measurements and latency, as observed. The current automated React evidence is not a physical demo recording.
