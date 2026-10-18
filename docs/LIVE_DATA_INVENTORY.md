# Live data inventory

Verified from this checkout on 2026-10-18. This inventory describes checked-in files and running code; it does not independently verify the upstream download or the physical print.

| Source | Verified use |
| --- | --- |
| `scenarios/nepal_rasuwa_hot_v1/data/scenario.json` | Scenario version 2; 5 model budget units; 1 bridge, shelter, hospital and food station; 2 population inputs; digital START |
| `roads.json` | Authoritative graph: 16 nodes, 18 edges; mapped road polylines in board UV |
| `sites.json` | 9 sites: START, 2 population nodes, 3 facility pads, 3 crossings. Each population is 8 model people, with food/refuge need 8 and medical need 2 |
| `hazard.json` | `illustrative_disruption_mask`; stage 0 dry, stage 1 closes east/west/south crossings; no stage 2 |
| `waterways_board.json`, `settlements_board.json`, `bridges_board.json`, `roads_board.json` | HOT/OSM source geometry and references; geometry endpoint returns 4 river lines and 2 settlement labels |
| `map_print.svg`, `map_projection.svg` | Available print/projection assets. No Mapbox package, token, style or source implementation is present in this checkout |
| `source_manifest.json` | Source filenames, hashes, bounds, attribution and transformation. Manifest reports HOT via HDX, OpenStreetMap contributors, ODC-ODbL; upstream metadata has not been re-fetched for this UI task |
| `backend/world/service.py` | Retained `WorldService`; owns accepted actions, world versions and snapshots |
| `backend/simulation/reachability.py`, `backend/world/game.py` | Reachability, capacity, unmet need, score and no-response comparison. The UI displays these outputs |
| `backend/world/session_store.py` | Optional SQLite checkpoint store via `FLOODSHIFT_SESSION`. Default server uses memory with the real bundle; there is no required external database |

The cartography is mapped source geography. Population, site suitability, flood closures, capacity, budget and outcomes are educational assumptions already in the source scenario, not measured demographic or operational flood predictions. The UI creates no replacement records. START places the existing population inputs at their scenario coordinates.

Board coordinates use `(0,0)` at top left, `(1,1)` at bottom right. The manifest's projected CRS is EPSG:32645, with bounds `[336089.89297685644, 3115343.646000852, 338489.89297685644, 3117743.646000852]`. `u=(x-xmin)/(xmax-xmin)`, `v=(ymax-y)/(ymax-ymin)`. Board dimensions are provisionally 420 × 420 mm; verify against the print. The UI uses the scenario aspect ratio, not a new geographic projection.

The geometry response contains no residential parcel footprints. Its four flood corridors follow mapped waterways near simulated closures; they are explicitly illustrative, not measured inundation boundaries. Danger indicators remain at population points; they do not claim parcel flooding.

| File under `scenarios/nepal_rasuwa_hot_v1/data/` | SHA-256 |
| --- | --- |
| `scenario.json` | `9b37810713f6cf340208a68047a6604e0bad294fea7f6d840d087265db5b2831` |
| `roads.json` | `255b6d00f331c71663cac48f8daacaadde2bd4d882aeff7e61a476296633b6ba` |
| `sites.json` | `4d5e4ae8ba9a312c3f0aa6b625d5c0ce9346e3cf6e14724f9bad4dc1249e1475` |
| `hazard.json` | `e27d7f29e553bc89c5b05b223eec6ea80b60f1f0ec46c1fedbe8fb5e9923459c` |
| `map_print.svg` | `b08243c64fe3a8ab8d9899b496082b037286a2b8703f200b720f5a0038e1c6f8` |

The operator separately computes SHA-256 over the exact `/scenario` response bytes and includes it in downloaded run records. That is a geometry-response fingerprint, not a database or complete scenario-bundle fingerprint.

Shared decisions still needed: identify the actual printed map and resolve the spec's Mapbox requirement; provide a second reviewed flood stage; measure the existing board markers. Existing backend additions in `1a1406f` still require shared review. This continuation changes UI, tests and documentation only.
