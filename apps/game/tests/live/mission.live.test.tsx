import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { resolve } from "node:path";
import { act, create } from "react-test-renderer";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { BoardSvg } from "../../src/game/overlays/BoardSvg";
import { PIECE_NAME } from "../../src/game/story";
import { buildResults } from "../../src/game/results";

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
const board = () => operator.root.findByType(BoardSvg).props;
const projected = () => projector.root.findByType(BoardSvg).props;
async function until(check: () => boolean, timeout = 6000) {
  const end = Date.now() + timeout;
  while (!check()) {
    if (Date.now() > end) throw new Error(`Timed out waiting for live UI. Backend: ${backendLog.slice(-2000)}`);
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
  backend = spawn(python, ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: root, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONUTF8: "1", FLOODSHIFT_SCENARIO: "nepal_rasuwa_hot_v1", FLOODSHIFT_SESSION: "" },
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
    addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events) });
  const storage = () => { const data = new Map(); return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => data.set(k, v) }; };
  vi.stubGlobal("localStorage", storage());
  vi.stubGlobal("sessionStorage", storage());
  const { OperatorRoute } = await import("../../src/routes/operator/OperatorRoute");
  const { ProjectorRoute } = await import("../../src/routes/projector/ProjectorRoute");
  await act(async () => { operator = create(<OperatorRoute />); projector = create(<ProjectorRoute />); });
  await until(() => operator.root.findAllByType(BoardSvg).length > 0 && projector.root.findAllByType(BoardSvg).length > 0 && !!board().snapshot && !!projected().snapshot);
});

afterAll(async () => {
  await act(async () => { operator?.unmount(); projector?.unmount(); });
  backend?.kill();
  vi.unstubAllGlobals(); vi.unstubAllEnvs();
});

it("plays both UI screens for 75 real seconds, including correction, surge failure and replay", async () => {
  const wire = new WebSocket(baseUrl.replace("http", "ws") + "/ws");
  wire.addEventListener("message", event => {
    try { const m = JSON.parse(String(event.data)); if (m.type === "world.snapshot") actions.push({ at: new Date().toISOString(), version: m.payload.world_version, phase: m.payload.phase, stage: m.payload.simulation_stage }); } catch { /* pong */ }
  });
  try {
    await until(() => operator.root.findAllByType("button").some(b => text(b) === "START GAME" && !b.props.disabled));
    await click("START GAME");
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
    await act(async () => { pad().props.onClick(); });
    await until(() => board().snapshot.tokens.some((t: any) => t.type === "bridge"));
    capture("bridge_accepted");
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
    await until(() => board().clock.phase === "SURGE" && board().clock.surge === "failed", 25000);
    expect(board().snapshot.simulation_stage).toBe(1);
    expect(board().clock.surgeReason).toBe("last_stage");
    expect(text(projector.toJSON())).toContain("FLOOD UPDATE UNAVAILABLE");
    const surgeLog = operator.root.findAllByType("li").filter(li => text(li).includes("[game_clock] advance_stage"));
    expect(surgeLog).toHaveLength(1);
    capture("surge_50s_truthful_last_stage_failure");
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
      execution: "React test renderer + real HTTP/WebSocket/BroadcastChannel + real monotonic 75-second clock",
      browser_visual_check: "NOT RUN: no browser session available", physical_board_check: "NOT RUN",
      assertions: ["both routes mounted", "digital START and two population records", "pause/resume", "manual bridge place/move/remove/retry", "duplicate placement rejected", "three facilities accepted", "exactly one timed surge rejected last_stage", "input closed at 70s", "finished at 75s", "backend-derived results", "replay clears world"],
      frames, websocket_snapshots: actions, final_results: results };
    const folder = resolve(root, "docs/evidence");
    mkdirSync(folder, { recursive: true });
    writeFileSync(resolve(folder, "ui-live-run.json"), JSON.stringify(evidence, null, 2) + "\n");
  } finally { wire.close(); }
});
