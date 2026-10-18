# FLOODSHIFT: The Last Crossing

A 75-second tabletop flood-response game for the retained `nepal_rasuwa_hot_v1` world. Sky's UI lives in `apps/game`: `/operator` controls the mission and `/projector` draws accepted backend state over the printed board.

On Windows, install Node.js and Python 3.11+, then run from this repository:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-world.txt fastapi 'uvicorn[standard]' pydantic python-dotenv
Set-Location apps/game
npm.cmd ci
Set-Location ../..
powershell -ExecutionPolicy Bypass -File scripts/start_all.ps1
```

Open [operator](http://localhost:5180/operator), then use its **open /projector** link to open the projection window in the same browser. **START GAME** resets the real world, places its digital START and both existing population records, then starts the clock. Both windows need the same origin and browser profile. `F` toggles projector fullscreen, `M` switches the screen basemap/physical overlay, `C` opens calibration, and `T` toggles registration reticles. Use `?mode=screen` or press `M` for laptop rehearsal. Physical overlay currently holds at **BOARD REGISTRATION REQUIRED**: the incoming board photo shows a landscape print whose coordinates differ from the square scenario, and no measured print-to-world transform is supplied.

The launcher checks ports, starts a hidden backend, waits for health, and runs Vite in the foreground. Ctrl+C cleans up its backend. If 8010 or 5180 is occupied, choose `-BackendPort 8011 -FrontendPort 5181`; it leaves existing servers alone. It starts the UI lane only. The merged Lane B camera/tracker is in [perception](perception/README.md); classification and the observation-to-world adapter are separate integration work.

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
# Optional real-time integration run; starts its own temporary backend:
npm.cmd run test:live
Set-Location ../..
.venv/Scripts/python.exe -m pytest -q
# Incoming Lane B tests require its OpenCV dependencies:
.venv/Scripts/python.exe -m pip install -r perception/requirements.txt
.venv/Scripts/python.exe -m pytest perception/tests -q
```

The live test drives both React screens and real HTTP/WebSocket actions for 75 seconds, recording evidence under `docs/evidence`. It requires the repository Python environment. It runs without a browser and does not verify pixel layout or physical projection.

Current constraints: the checked-in cartography is HOT/OSM SVG geometry; Mapbox assets are absent. Lane B's real photo verifies marker IDs and corner order (TL 10, TR 11, BR 13, BL 12); marker centres/paper size still need measurement, and landscape print UV must be mapped to world UV before physical projection or observation actions. START activates the bundle's only flooded stage, so the 50-second advance correctly reports `FLOOD UPDATE UNAVAILABLE` / `last_stage`. A second stage must come from the data owner. UI colors avoid the legacy bridge HSV filter; the new classifier still needs projector-on testing.

Read [data inventory](docs/LIVE_DATA_INVENTORY.md), [integration contract](docs/INTEGRATION_CONTRACT.md), [board registration](docs/BOARD_REGISTRATION.md), [operator run of show](docs/RUN_OF_SHOW.md), and [test evidence](docs/TEST_EVIDENCE.md) before hardware rehearsal. Backend/world and public-contract changes require shared review under the master spec; this UI continuation does not change those files.
