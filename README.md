# FLOODSHIFT: The Last Crossing

A 75-second tabletop flood-response game for the retained `nepal_rasuwa_hot_v1` world. The projected map is the player interface. Sky's UI lives in `apps/game`: `/operator` normally shows one START button; `/projector` shows localized flood, route and piece overlays from accepted backend state.

On Windows, install Node.js and Python 3.11+, then run from this repository:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-world.txt fastapi 'uvicorn[standard]' pydantic python-dotenv
# For the camera and classifier:
.venv/Scripts/python.exe -m pip install -r requirements.txt
Set-Location apps/game
npm.cmd ci
Set-Location ../..
powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1
```

Open [operator](http://localhost:5180/operator) and [projector](http://localhost:5180/projector) in two windows of the same browser profile and origin. **START** resets the real world, places its digital START and both existing population records, then starts the clock. It starts gameplay directly; the seven-frame prologue is omitted as requested. After 75 seconds, the same START control starts another run. Press **O** on the laptop to open/close technical controls without resetting the mission. For initial setup, `/operator?tools=1` opens those controls immediately; do not reload the operator page during a run because it owns the clock.

`F` toggles projector fullscreen, `M` switches the screen basemap/physical overlay, `C` opens calibration, and `T` toggles registration reticles. Use [/projector?mode=screen](http://localhost:5180/projector?mode=screen) for screen rehearsal. Physical overlay currently holds at **BOARD REGISTRATION REQUIRED**: the incoming board photo shows a landscape print whose coordinates differ from the square scenario, and no measured print-to-world transform is supplied. The default START screen reports physical input as unavailable until registration/classification are actually ready.

After pulling updates, run `npm.cmd ci` in `apps/game` and restart its Vite process. Open port **5180**, served by this app. The normal laptop page has one START button; the projector has a compact mission prompt and map overlays. Camera, calibration, pause/reset and manual fallback belong to the technical controls, outside the player projection.

The launcher checks ports, starts a hidden backend, waits for health, and runs Vite in the foreground. Ctrl+C cleans up its processes. If 8010 or 5180 is occupied, choose `-BackendPort 8011 -FrontendPort 5181`; it leaves existing servers alone. For camera + Perceptron + game together, set `PERCEPTRON_API_KEY` in `.env`, complete [physical registration](docs/PHYSICAL_INTEGRATION.md), then run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1 -WithPerception -CameraSource auto
```

This starts the existing OpenCV tracker with `perception.fusion:create_classifier`, posting lifecycle events to `/perception/physical`. Bridge placement, movement and removal invoke the retained reducer; rejected moves keep the accepted token at its previous site. No color fallback is presented as Perceptron. Camera diagnostics are in `.runtime/perception.stderr.log`.

To run the services separately:

```powershell
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8010
# In a second terminal:
Set-Location apps/game
npm.cmd run dev
```

Copy `.env.example` to `.env` for backend settings and `apps/game/.env.example` to `apps/game/.env.local` for UI overrides. The default world is in memory; `FLOODSHIFT_SESSION` enables the existing SQLite checkpoint store. Never place service credentials in `VITE_*` variables.

Verification:

```powershell
Set-Location apps/game
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
# Export BoardSvg using backend-generated snapshots:
npm.cmd run render:projector
# Optional real-time integration run; starts its own temporary backend:
npm.cmd run test:live
Set-Location ../..
.venv/Scripts/python.exe -X utf8 -m pytest tests -q
# Incoming Lane B tests require its OpenCV dependencies:
.venv/Scripts/python.exe -m pip install -r perception/requirements.txt
.venv/Scripts/python.exe -m pytest perception/tests -q
```

The live test drives both React screens for 75 seconds with real HTTP/WebSocket actions, controlled physical observations and test-only calibration. It records evidence under `docs/evidence`; it is not a live detection test. [Projector previews](docs/evidence/projector/manifest.json) are actual SVG component renders: [before the crossing](docs/evidence/projector/crossing-before.png), [after the crossing](docs/evidence/projector/crossing-after.png), and [results](docs/evidence/projector/results.png). These checks do not establish browser layout, classifier accuracy or physical alignment.

Current constraints: the checked-in cartography is HOT/OSM SVG geometry; Mapbox assets are absent. Lane B's real photo verifies marker IDs and corner order (TL 10, TR 11, BR 13, BL 12); marker centres/paper size still need measurement, and landscape print UV must be mapped to world UV before physical projection or observation actions. START activates the bundle's only flooded stage, so the 50-second advance correctly reports `FLOOD UPDATE UNAVAILABLE` / `last_stage`. A second stage must come from the data owner. UI colors avoid the legacy bridge HSV filter; the new classifier still needs projector-on testing.

Read [physical setup](docs/PHYSICAL_INTEGRATION.md), [integration contract](docs/INTEGRATION_CONTRACT.md), [board registration](docs/BOARD_REGISTRATION.md), [operator run of show](docs/RUN_OF_SHOW.md), and [test evidence](docs/TEST_EVIDENCE.md) before hardware rehearsal. World rules, scenario data, simulation and scoring are preserved. Integration adds gateway endpoints and connects the detection service to them.
