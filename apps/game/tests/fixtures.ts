import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import type { WorldSnapshot } from "../src/types/contracts";
import type { ScenarioGeometry } from "../src/types/scenario";

const windowsPython = resolve("../../.venv/Scripts/python.exe");
const unixPython = resolve("../../.venv/bin/python");
const python = existsSync(windowsPython) ? windowsPython : existsSync(unixPython) ? unixPython : "python";
export const fixture = JSON.parse(execFileSync(python, ["tests/world_fixtures.py"], { encoding: "utf8", maxBuffer: 10_000_000 })) as {
  scenario: ScenarioGeometry;
  states: Record<"ready" | "started" | "services" | "connected" | "moved" | "removed" | "surged" | "failed_surge" | "reset" | "game_start" | "game_guided" | "game_bridge" | "game_service" | "game_surge" | "game_final", WorldSnapshot>;
};
