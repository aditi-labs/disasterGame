import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { Resvg } from "@resvg/resvg-js";
import { ProjectionScene } from "../src/game/overlays/ProjectionScene";
import { buildBoardModel } from "../src/game/worldAdapter";
import { buildGuide } from "../src/game/guide";
import { buildResults } from "../src/game/results";
import { diffSnapshots } from "../src/game/reactions";
import { IDLE_VIEW, MISSION_MS, type ClockView, type GamePhase } from "../src/game/clock";
import type { ProjectionRegistration, UV, WorldSnapshot } from "../src/types/contracts";
import registration from "../../../perception/board_registration.json";
import mapping from "../../../perception/board_mapping.json";
import { fixture } from "./fixtures";

// Actual component renders of the 75-second game from the retained reducer's output,
// with the measured print mapping. "screen" renders sit on the printed artwork (what the
// players see on the board); "overlay" renders are the projector's own white output.
// They verify SVG appearance, not browser layout, live camera input or physical alignment.
const folder = resolve("../../docs/evidence/projector");
mkdirSync(folder, { recursive: true });
for (const f of readdirSync(folder)) if (/\.(png|svg)$/.test(f)) rmSync(resolve(folder, f));
const css = readFileSync("src/styles.css", "utf8");
const artwork = "data:image/png;base64," + readFileSync(resolve("../../nepalmap.png")).toString("base64");
const fonts = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/georgiai.ttf", "C:/Windows/Fonts/consola.ttf"].filter(existsSync);

const [a, b, c, d, e, f, g, h, i] = mapping.print_to_world as number[];
const adj = [e * i - f * h, c * h - b * i, b * f - c * e, f * g - d * i, a * i - c * g, c * d - a * f, d * h - e * g, b * g - a * h, a * e - b * d];
const det = a * adj[0] + b * adj[3] + c * adj[6];
const reg: ProjectionRegistration = {
  ready: true, mapping_ready: true, world_to_print: adj.map((n) => n / det), board: registration.board,
  markers: registration.markers.map((m) => ({ id: m.id, center_uv: m.center_uv as UV })), marker_size_mm: Math.max(...Object.values(registration.aruco.marker_sizes_mm)),
};
const s = fixture.states;
const scenes: { name: string; state: WorldSnapshot; prev?: WorldSnapshot; phase: GamePhase; elapsed: number; surface: "screen" | "overlay" }[] = [
  { name: "0-idle", state: s.ready, phase: "IDLE", elapsed: 0, surface: "screen" },
  { name: "1-warning", state: s.game_start, phase: "WARNING", elapsed: 4000, surface: "screen" },
  { name: "1b-mission1-reveal", state: s.game_start, phase: "WARNING", elapsed: 8500, surface: "screen" },
  { name: "2-crossing-before", state: s.game_start, phase: "CROSSING", elapsed: 15000, surface: "screen" },
  { name: "2a-matsyas-guidance", state: s.game_guided, phase: "CROSSING", elapsed: 19000, surface: "screen" },
  { name: "2b-crossing-restored", state: s.game_bridge, prev: s.game_start, phase: "CROSSING", elapsed: 18000, surface: "screen" },
  { name: "3-refuge-choice", state: s.game_bridge, phase: "RELIEF", elapsed: 32000, surface: "screen" },
  { name: "3b-hospital-deployed", state: s.game_service, prev: s.game_bridge, phase: "RELIEF", elapsed: 40000, surface: "screen" },
  { name: "4-surge", state: s.game_surge, prev: s.game_service, phase: "SURGE", elapsed: 55000, surface: "screen" },
  { name: "5-impact", state: s.game_final, phase: "RESULTS", elapsed: 75000, surface: "screen" },
  { name: "overlay-2-crossing-before", state: s.game_start, phase: "CROSSING", elapsed: 15000, surface: "overlay" },
  { name: "overlay-4-surge", state: s.game_surge, prev: s.game_service, phase: "SURGE", elapsed: 55000, surface: "overlay" },
];
const outputs = [];
for (const scene of scenes) {
  const clock: ClockView = { ...IDLE_VIEW, phase: scene.phase, mode: scene.phase === "IDLE" ? "idle" : scene.phase === "RESULTS" ? "finished" : "running", elapsedMs: scene.elapsed, remainingMs: MISSION_MS - scene.elapsed, surge: scene.phase === "SURGE" ? "accepted" : "not_due" };
  const reaction = scene.prev ? diffSnapshots(scene.prev, scene.state, fixture.scenario) : null;
  const reactions = reaction ? [{ ...reaction, at: Date.now(), until: Date.now() + 60_000 }] : [];
  const svg = renderToStaticMarkup(
    <ProjectionScene scenario={fixture.scenario} snapshot={scene.state} model={buildBoardModel(fixture.scenario, scene.state, [], true)} guide={buildGuide(clock, scene.state)} clock={clock} reactions={reactions} rejections={[]} pending={[]} surface={scene.surface} variant="projector" results={scene.phase === "RESULTS" ? buildResults(fixture.scenario, scene.state) : null} registration={reg} />,
  )
    .replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ')
    .replace(/(<image[^>]*href=")[^"]*"/, `$1${artwork}"`)
    // Static evidence shows each animation's settled state.
    .replace(/(<svg[^>]*>)/, "$1<style>" + css + " *{animation:none!important}</style>");
  writeFileSync(resolve(folder, scene.name + ".svg"), svg);
  const png = new Resvg(svg, { fitTo: { mode: "width", value: 1600 }, font: { fontFiles: fonts, loadSystemFonts: true, defaultFontFamily: "Segoe UI" }, background: "#ffffff" }).render().asPng();
  writeFileSync(resolve(folder, scene.name + ".png"), png);
  outputs.push({ name: scene.name, surface: scene.surface, world_version: scene.state.world_version, phase: scene.phase, elapsed_ms: scene.elapsed, stage: scene.state.simulation_stage, metrics: scene.state.metrics });
  console.log("Rendered " + scene.name);
}
writeFileSync(resolve(folder, "manifest.json"), JSON.stringify({ generated_at: new Date().toISOString(), scenario_id: fixture.scenario.scenario_id, source: "Real retained WorldService reducer; backend-generated test snapshots; measured print mapping", renderer: "React SVG + resvg; not browser screenshots or physical evidence", outputs }, null, 2) + "\n");
