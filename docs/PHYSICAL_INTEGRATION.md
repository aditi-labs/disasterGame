# Physical game setup and verification

The pipeline is camera → OpenCV registration/candidates/tracker → Perceptron ClassifierPort → `PhysicalObservation` → `/perception/physical` → retained `WorldService` → WebSocket snapshot → projector. There is one tracker and one world. The old parallel fusion tracker and projector intro card are removed.

## Install and configure

From the repository root, install `requirements-world.txt`, the backend dependencies listed in README, and `requirements.txt` for OpenCV and Perceptron. Copy `.env.example` to `.env` and set `PERCEPTRON_API_KEY`. Both the backend and camera CLI read this file. Never put this credential in a Vite variable. The SDK version verified here is 0.4.0; its [official documentation](https://pypi.org/project/perceptron/) describes media wrapping, result boxes and request timeout configuration.

The SDK may return a class without numeric confidence. The adapter preserves `None`; three agreeing results from distinct camera frames plus the existing geometric/stability checks can qualify the observation. A count of agreeing frames is local evidence, not a calibrated model probability. Missing credentials, API errors, unknown classes and ambiguous crops stay pending. Color heuristics are not substituted for Perceptron in the game path.

## Measure the board and map

1. Use [BOARD_REGISTRATION](BOARD_REGISTRATION.md) to measure the actual paper, marker size/centres and camera reprojection. Run `.venv/Scripts/python.exe -m perception.service --source auto --calibrate`. The checked-in estimates are not measurements.
2. Collect at least six corresponding landmarks on the real print and the source map: four widely separated, non-collinear points to fit, followed by two or more independent points to check. Each entry in a JSON array needs `label`, `print_uv` and `world_uv`, with two measured normalized coordinates per UV. Print UV includes the paper margins; world UV uses the scenario extent. Use actual river/road landmarks, not a stretched screenshot or guessed service-pad locations.
3. Save those real pairs in a local file, then fit:

   ```powershell
   .venv/Scripts/python.exe scripts/register_print_world.py --points .runtime/measured-landmarks.json --measured-by "Your name" --source "Physical print and measurement record"
   ```

   The script writes `perception/board_mapping.json` only after held-out error is at most 0.01 world UV. It records the actual residual and input pairs. This software threshold is a starting gate; verify physical reprojection against the intended piece/pad tolerance.
4. Restart the backend after measuring. `/projection/registration` must report `ready: true`. Both registration files must have measured status, matching scenario and valid geometry. The checked-in mapping deliberately remains `UNMEASURED`.

The backend transforms print UV into world UV before any action. The projector applies the inverse matrix to world geography, fits the measured paper aspect, then applies projector pixel calibration. Marker masks remain in print coordinates and draw last. `F`, `M`, `C`, `T` and the existing keystone keys remain. Pressing Enter saves a pixel adjustment; it cannot invent measured registration.

Camera-measured oriented bounding boxes also supply black piece-surface keep-outs, with a 6 mm margin. These are optical masks, independent of placement acceptance; rings and labels sit outside the measured footprint. They update on candidate/movement observations and clear when the track leaves. Verify the margin and top-surface/parallax coverage with actual pieces and projector lighting.

## Start the connected services

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1 -WithPerception -CameraSource auto
```

Use a camera index or DroidCam/video source instead of `auto` if needed. Open `/operator` and `/projector` in the same browser profile and origin. The default laptop page has one START button; O opens technical controls without reloading the clock. The optional camera process is hidden and logs to `.runtime/perception.stdout.log` / `.runtime/perception.stderr.log`. Without `-WithPerception`, the launcher runs a manual screen rehearsal.

To run the camera separately against an existing backend:

```powershell
.venv/Scripts/python.exe -m perception.service --source auto --classifier perception.fusion:create_classifier --observe-url http://localhost:8010/perception/physical --status-url http://localhost:8010/perception/status --record assets/live_captures/run1
```

Capture the empty-board reference with no pieces present. Keep pieces in the tray before START/reset. The camera uses a background reference; projector-on lighting, hands, shadows and white tokens must be tested on this board. `--structure-gate` is available for the existing projection-resistant candidate mode; it still requires hardware tuning.

## Lifecycle and timing

- The backend owns track-to-token bindings. PLACED creates a token only on reducer acceptance. MOVED changes that token; a rejected move leaves its old site and binding intact. A correction can be accepted later. REMOVED removes only a bound token. Candidate/lost/uncertain observations create no world consequences.
- Camera HTTP feedback is queued and applied on the camera processing thread. Backend reset changes `world_epoch`; status feedback clears camera tracks/bindings on the next frame. Delayed events from an old epoch are rejected. Restarting the detector mid-run requires resetting the game so stale identities cannot become new tokens.
- START completes digital START and existing population setup, then opens a backend input run. Pause/resume is acknowledged by the backend. Manual corrections remain available while paused before 70 seconds.
- Backend monotonic time rejects physical input after 70 seconds even if the operator misses the close callback. Closing input and reading the final snapshot happen under the mutation lock. The projector and run export use that captured snapshot. The narrative clock ends at 75 seconds.
- At 50 seconds the UI requests a stage advance once. The current data still has only one flooded stage and returns `last_stage`; no extra inundation is invented.

## Acceptance on hardware

Verify bridge placement, an invalid placement then correction, sliding/moving, lifting, brief occlusion, all facility classes, replay with a fresh epoch, pause/resume and the 70-second cutoff. Check actual routes and unmet needs against `/world`, and record the camera/projector video plus JSONL/run export. Measure classifier precision/recall and latency on real frames with the projector on and off.

Automated tests cover this software contract using controlled observations and synthetic camera fixtures. They do not establish live-camera accuracy, lighting tolerance, physical alignment or browser pixels. Current automated results and the unchanged HOT reproducibility failure are in [TEST_EVIDENCE](TEST_EVIDENCE.md).
