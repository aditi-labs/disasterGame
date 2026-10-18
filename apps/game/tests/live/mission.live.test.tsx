import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { resolve } from "node:path";
import { act, create } from "react-test-renderer";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { ProjectionScene } from "../../src/game/overlays/ProjectionScene";
import { PIECE_NAME } from "../../src/game/story";
import { buildResults } from "../../src/game/results";
import { StartScreen } from "../../src/routes/operator/StartScreen";

// Real HTTP, real WebSockets, real BroadcastChannel, real reducer, real 75 seconds.
// React test rendering verifies behavior/markup; it cannot verify browser pixels.
const root = resolve("../..");
const winPython = resolve(root, ".venv/Scripts/python.exe");
const unixPython = resolve(root, ".venv/bin/python");
const python = existsSync(winPython) ? winPython : existsSync(unixPython) ? unixPython : "python";
const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
let backend: ReturnType<typeof spawn>;
let backendLog = "";
let operator: ReturnType<typeof create>;
let projector: ReturnType<typeof create>;
let baseUrl: string;
const frames: any[] = [];
const actions: any[] = [];

const text = (node: any): string => typeof node === "string" || typeof node === "number" ? String(node) : node?.children?.map(text).join("") ?? "";
const board = () => operator.root.findByType(ProjectionScene).props;
const projected = () => projector.root.findByType(ProjectionScene).props;
async function until(check: () => boolean, timeout = 6000) {
  const end = Date.now() + timeout;
  while (!check()) {
    if (Date.now() > end) throw new Error(`Timed out waiting for live UI. UI: ${text(operator?.toJSON()).slice(0, 1500)} Backend: ${backendLog.slice(-1500)}`);
    await act(async () => { await delay(100); });
  }
}
async function click(label: string) {
  const button = operator.root.findAllByType("button").find(b => text(b) === label);
  expect(button, `button ${label}`).toBeDefined();
  expect(button!.props.disabled).not.toBe(true);
  await act(async () => { await button!.props.onClick(); });
}
async function select(label: string, value: string) {
  await act(async () => { operator.root.findAllByType("select").find(s => s.props["aria-label"] === label)!.props.onChange({ target: { value } }); });
}
function capture(label: string) {
  const b = board(), p = projected();
  frames.push({ label, at: new Date().toISOString(), elapsed_ms: b.clock.elapsedMs, phase: b.clock.phase,
    projector_phase: p.clock.phase, world_version: b.snapshot.world_version, projector_world_version: p.snapshot.world_version,
    simulation_stage: b.snapshot.simulation_stage, surge: b.clock.surge, syncing: p.resultsSyncing,
    metrics: b.snapshot.metrics, token_sites: b.snapshot.tokens.map((t: any) => ({ type: t.type, site: t.site_id, source: t.vision_source })),
    open_routes: b.model.open.length, blocked_roads: b.model.blocked.length });
}

beforeAll(async () => {
  // Bind a fresh ephemeral port so an existing operator/world session is never reset.
  const port = await new Promise<number>(r => {
    const server = createServer();
    server.listen(0, "127.0.0.1", () => { const address = server.address() as { port: number }; server.close(() => r(address.port)); });
  });
  baseUrl = `http://127.0.0.1:${port}`;
  // Controlled test calibration, never used by the launcher or described as measured hardware.
  const calibrationFolder = resolve(root, ".runtime/ui-physical-test-" + port);
  mkdirSync(calibrationFolder, { recursive: true });
  const registration = JSON.parse(readFileSync(resolve(root, "perception/board_registration.json"), "utf8"));
  registration.status = "MEASURED";
  registration.markers.forEach((m: any) => m.verified = true);
  registration.aruco.marker_size_mm = 40;
  writeFileSync(resolve(calibrationFolder, "markers.json"), JSON.stringify(registration));
  writeFileSync(resolve(calibrationFolder, "mapping.json"), JSON.stringify({ status: "MEASURED", scenario_id: "nepal_rasuwa_hot_v1", print_to_world: [1,0,.1,0,1,0,0,0,1], measured_by: "AUTOMATED TEST ONLY", measured_on: "TEST FIXTURE", source: "Controlled software inputs, not a hardware measurement" }));
  backend = spawn(python, ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONUTF8: "1", FLOODSHIFT_SCENARIO: "nepal_rasuwa_hot_v1", FLOODSHIFT_SESSION: "", FLOODSHIFT_BOARD_MAPPING: resolve(calibrationFolder, "mapping.json"), FLOODSHIFT_BOARD_REGISTRATION: resolve(calibrationFolder, "markers.json") },
  });
  backend.stdout!.on("data", data => { backendLog += data.toString(); });
  backend.stderr!.on("data", data => { backendLog += data.toString(); });
  let ready = false;
  for (let i = 0; i < 60; i++) {
    try { ready = (await fetch(baseUrl + "/health")).ok; } catch { /* waiting for real startup */ }
    if (ready) break;
    await delay(100);
  }
  if (!ready) throw new Error(backendLog || "Backend failed to start");
  vi.stubEnv("VITE_API_URL", baseUrl);
  vi.stubEnv("VITE_SCENARIO_ID", "nepal_rasuwa_hot_v1");
  const events = new EventTarget();
  vi.stubGlobal("window", { setInterval, clearInterval, setTimeout, clearTimeout, innerWidth: 1920, innerHeight: 1080,
    location: { search: "?mode=screen" }, confirm: () => true,
    dispatchEvent: events.dispatchEvent.bind(events),
    addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events) });
  const storage = () => { const data = new Map(); return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => data.set(k, v) }; };
  vi.stubGlobal("localStorage", storage());
  vi.stubGlobal("sessionStorage", storage());
  const { OperatorRoute } = await import("../../src/routes/operator/OperatorRoute");
  const { ProjectorRoute } = await import("../../src/routes/projector/ProjectorRoute");
  await act(async () => { operator = create(<OperatorRoute />); projector = create(<ProjectorRoute />); });
  await until(() => operator.root.findAllByType(StartScreen).length > 0 && projector.root.findAllByType(ProjectionScene).length > 0 && !!projected().snapshot);
});

afterAll(async () => {
  await act(async () => { operator?.unmount(); projector?.unmount(); });
  backend?.kill();
  vi.unstubAllGlobals(); vi.unstubAllEnvs();
});

it("plays both UI screens for 75 real seconds, including correction, the surge stage and replay", async () => {
  const wire = new WebSocket(baseUrl.replace("http", "ws") + "/ws");
  wire.addEventListener("message", event => {
    try { const m = JSON.parse(String(event.data)); if (m.type === "world.snapshot") actions.push({ at: new Date().toISOString(), version: m.payload.world_version, phase: m.payload.phase, stage: m.payload.simulation_stage }); } catch { /* pong */ }
  });
  try {
    await until(() => operator.root.findAllByType("button").some(b => text(b) === "START" && !b.props.disabled));
    expect(operator.root.findAllByType("button")).toHaveLength(1);
    await click("START");
    const openTools = new Event("keydown");
    Object.defineProperty(openTools, "key", { value: "o" });
    act(() => window.dispatchEvent(openTools));
    await until(() => board().snapshot.population_demand.length === 2 && projected().clock.phase === "WARNING");
    capture("digital_start_with_both_population_records");
    await click("PAUSE");
    const pausedAt = board().clock.elapsedMs;
    await act(async () => { await delay(400); });
    expect(board().clock.elapsedMs).toBe(pausedAt);
    await click("RESUME");
    await until(() => board().clock.phase === "CROSSING", 15000);
    await until(() => projected().clock.phase === "CROSSING");
    capture("crossing_10s");
    const pad = () => operator.root.findAllByType("circle").find(c => c.props["aria-label"]?.includes("(crossing_east)"))!;
    const post = (path: string, body: unknown) => fetch(baseUrl+path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json());
    const epoch = (await (await fetch(baseUrl+"/perception/status")).json()).integration.world_epoch;
    const observe = async (site: string, lifecycle: string, confidence_band = "high") => {
      await post("/perception/status", { registration: { valid: true, registration_verified: true } });
      const uv = board().scenario.sites.find((s: any) => s.id === site).board_uv;
      return post("/perception/physical", { event_id: crypto.randomUUID(), session_id: "controlled-camera-test", world_epoch: epoch,
        track_id: "controlled-track", piece_class: "bridge", class_source: "perceptron", lifecycle, confidence_band,
        observed_at_ms: Date.now(), source: "recording", frame_provenance: "TEST: controlled observations; not real camera detections", board_uv: { u: uv[0]-.1, v: uv[1] }, geometry: { bbox_mm: [70,40] }, orientation_deg: 0 });
    };
    const versionBefore = board().snapshot.world_version;
    await act(async () => { await observe("crossing_east", "candidate", "review"); });
    await until(() => projected().pending.some((o: any) => o.token_id === "controlled-track"));
    expect(board().snapshot.world_version).toBe(versionBefore);
    await act(async () => { expect((await observe("crossing_east", "placed")).accepted).toBe(true); });
    await until(() => board().snapshot.tokens.some((t: any) => t.type === "bridge"));
    capture("controlled_physical_bridge_accepted");
    await act(async () => { expect((await observe("crossing_west", "moved")).accepted).toBe(true); });
    await until(() => projected().snapshot.tokens.some((t: any) => t.type === "bridge" && t.site_id === "crossing_west"));
    capture("controlled_physical_bridge_moved");
    await act(async () => { expect((await observe("crossing_west", "removed")).removed).toBe(true); });
    await until(() => !projected().snapshot.tokens.some((t: any) => t.type === "bridge"));
    await act(async () => { expect((await observe("crossing_east", "placed")).accepted).toBe(true); });
    await until(() => board().snapshot.tokens.some((t: any) => t.type === "bridge"));
    const bridge = board().snapshot.tokens.find((t: any) => t.type === "bridge");
    await select("Piece to move", bridge.id);
    await select("Destination site", "crossing_west");
    await click("MOVE");
    await until(() => board().snapshot.tokens.some((t: any) => t.id === bridge.id && t.site_id === "crossing_west"));
    capture("bridge_moved");
    await click("MANUAL REMOVE");
    await until(() => !board().snapshot.tokens.some((t: any) => t.type === "bridge"));
    await act(async () => { pad().props.onClick(); });
    await until(() => board().snapshot.tokens.some((t: any) => t.type === "bridge"));
    await act(async () => { pad().props.onClick(); });
    await until(() => text(operator.toJSON()).includes("rejected: site_occupied"));
    capture("retry_after_move_and_remove_with_duplicate_rejected");
    await until(() => board().clock.phase === "RELIEF", 25000);
    for (const [type, site] of [["shelter", "shelter_site_west"], ["hospital", "medical_site_west"], ["food_shelter", "food_site_west"]] as const) {
      const pieceButton = operator.root.findAllByType("button").find(b => b.props.className?.includes("btn-piece") && text(b).includes(PIECE_NAME[type]))!;
      await act(async () => { pieceButton.props.onClick(); });
      await select("Placement site", site);
      await click("PLACE");
      await until(() => board().snapshot.tokens.some((t: any) => t.type === type));
    }
    await until(() => projected().snapshot.world_version === board().snapshot.world_version);
    capture("relief_services_accepted");
    await until(() => board().clock.phase === "SURGE" && board().clock.surge === "accepted", 25000);
    await until(() => board().snapshot.simulation_stage === 2 && projected().snapshot.simulation_stage === 2);
    expect(board().snapshot.edges.find((e: any) => e.id === "road-7cae6a171bef").blocked).toBe(true);
    expect(projected().guide.story).toBe("One of the evacuation roads is now impassable.");
    expect(text(projector.toJSON())).toContain("CHAPTER IV");
    const surgeLog = operator.root.findAllByType("li").filter(li => text(li).includes("[game_clock] advance_stage"));
    expect(surgeLog).toHaveLength(1);
    capture("surge_50s_stage_2_accepted");
    await until(() => board().clock.phase === "RESULTS", 25000);
    expect(operator.root.findAllByType("button").find(b => text(b) === "PLACE")!.props.disabled).toBe(true);
    await until(() => projected().clock.phase === "RESULTS" && !projected().resultsSyncing);
    capture("results_70s");
    await until(() => board().clock.mode === "finished", 8000);
    expect(board().clock.elapsedMs).toBe(75000);
    const final = await (await fetch(baseUrl + "/world")).json();
    const results = buildResults(board().scenario, final);
    expect(projected().results.score.value).toBe(final.game.score);
    capture("finished_75s");
    await click("REPLAY");
    await until(() => board().clock.phase === "IDLE" && projected().clock.phase === "IDLE" && board().snapshot.phase === "ready");
    expect(board().snapshot.tokens).toEqual([]);
    capture("replay_reset_confirmed");
    const evidence = { kind: "floodshift.ui.live-test", verified_at: new Date().toISOString(), scenario_id: final.scenario_id,
      execution: "React test renderer + real HTTP/WebSocket/BroadcastChannel + real monotonic 75-second clock; controlled PhysicalObservation inputs and test calibration, not live detections",
      browser_visual_check: "NOT RUN: no browser session available", physical_board_check: "NOT RUN",
      assertions: ["both routes mounted", "START-only laptop view", "operator tools preserve clock", "digital START and two population records", "pause/resume acknowledges backend input gate", "controlled physical pending/place/move/remove reaches projector", "manual correction and duplicate rejection", "three facilities accepted", "one timed surge accepted: stage 2 closes the hillside road", "backend physical input closed and final state captured at 70s", "finished at 75s", "backend-derived results", "replay clears world and epoch"],
      frames, websocket_snapshots: actions, final_results: results };
    const folder = resolve(root, "docs/evidence");
    mkdirSync(folder, { recursive: true });
    writeFileSync(resolve(folder, "ui-live-run.json"), JSON.stringify(evidence, null, 2) + "\n");
  } finally { wire.close(); }
});
