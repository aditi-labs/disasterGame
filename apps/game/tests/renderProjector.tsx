import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { Resvg } from "@resvg/resvg-js";
import { BoardSvg } from "../src/game/overlays/BoardSvg";
import { buildBoardModel } from "../src/game/worldAdapter";
import { buildResults } from "../src/game/results";
import { IDLE_VIEW, MISSION_MS } from "../src/game/clock";
import { BEATS } from "../src/game/story";
import { setBoardAspect } from "../src/types/geometry";
import { fixture } from "./fixtures";

// These images are actual component renders from the retained reducer's output.
// They verify SVG appearance, not browser layout, live camera input or physical alignment.
const folder = resolve("../../docs/evidence/projector");
mkdirSync(folder, { recursive: true });
const css = readFileSync("src/styles.css", "utf8");
const fonts = ["C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/georgiai.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/consola.ttf"].filter(existsSync);
setBoardAspect(fixture.scenario.aspect_ratio);
const scenes = [
  { name: "idle", state: fixture.states.ready, phase: "IDLE", elapsed: 0 },
  { name: "crossing-before", state: fixture.states.services, phase: "CROSSING", elapsed: 15000 },
  { name: "crossing-after", state: fixture.states.connected, phase: "CROSSING", elapsed: 16000 },
  { name: "results", state: fixture.states.connected, phase: "RESULTS", elapsed: 75000 },
] as const;
const outputs = [];
for (const scene of scenes) {
  const clock = { ...IDLE_VIEW, phase: scene.phase, mode: scene.phase === "IDLE" ? "idle" as const : scene.phase === "RESULTS" ? "finished" as const : "running" as const, elapsedMs: scene.elapsed, remainingMs: MISSION_MS - scene.elapsed };
  const svg = renderToStaticMarkup(<BoardSvg scenario={fixture.scenario} snapshot={scene.state} model={buildBoardModel(fixture.scenario, scene.state, BEATS[scene.phase].pieces, scene.phase !== "IDLE" && scene.phase !== "RESULTS")} clock={clock} reactions={[]} rejections={[]} pending={[]} surface="screen" variant="projector" results={scene.phase === "RESULTS" ? buildResults(fixture.scenario, scene.state) : null} />)
    .replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ')
    .replace(/(<svg[^>]*>)/, "$1<style>" + css + "</style>");
  writeFileSync(resolve(folder, scene.name + ".svg"), svg);
  const png = new Resvg(svg, { fitTo: { mode: "width", value: 1000 }, font: { fontFiles: fonts, loadSystemFonts: true }, background: "#000000" }).render().asPng();
  writeFileSync(resolve(folder, scene.name + ".png"), png);
  outputs.push({ name: scene.name, world_version: scene.state.world_version, phase: scene.phase, metrics: scene.state.metrics });
  console.log("Rendered " + scene.name);
}
writeFileSync(resolve(folder, "manifest.json"), JSON.stringify({ generated_at: new Date().toISOString(), scenario_id: fixture.scenario.scenario_id, source: "Real retained WorldService reducer; backend-generated test snapshots", renderer: "React SVG + resvg; not browser screenshots or physical evidence", outputs }, null, 2) + "\n");
