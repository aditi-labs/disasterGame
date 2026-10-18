import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ProjectionScene } from "../src/game/overlays/ProjectionScene";
import { buildBoardModel } from "../src/game/worldAdapter";
import { buildResults } from "../src/game/results";
import { buildGuide } from "../src/game/guide";
import { IDLE_VIEW, MISSION_MS, type ClockView, type GamePhase } from "../src/game/clock";
import { applyHomography, calibrationMatrix3d, DEFAULT_CALIBRATION, solveHomography, targetCorners } from "../src/game/homography";
import { looksLikeBridgeToCamera, PALETTE } from "../src/game/palette";
import { makeFrame, PRINT_H, PRINT_W } from "../src/game/printFrame";
import { BOARD_MARKERS, MARKER_LAYOUT_VERIFIED } from "../src/game/board";
import { placementHint } from "../src/game/story";
import { boatOfHope, manuCard } from "../src/game/narrative";
import { buildGuide as guideFor, matsyaGuidance } from "../src/game/guide";
import registration from "../../../perception/board_registration.json";
import mapping from "../../../perception/board_mapping.json";
import type { WorldSnapshot } from "../src/types/contracts";
import { fixture } from "./fixtures";

const inverse3 = (m: number[]) => {
  const [a, b, c, d, e, f, g, h, i] = m;
  const adj = [e * i - f * h, c * h - b * i, b * f - c * e, f * g - d * i, a * i - c * g, c * d - a * f, d * h - e * g, b * g - a * h, a * e - b * d];
  const det = a * adj[0] + b * adj[3] + c * adj[6];
  return adj.map((n) => n / det);
};
const worldToPrint = inverse3(mapping.print_to_world as number[]);
const clockAt = (phase: GamePhase, elapsedMs: number, surge: ClockView["surge"] = "not_due"): ClockView => ({ ...IDLE_VIEW, phase, mode: phase === "IDLE" ? "idle" : phase === "RESULTS" ? "finished" : "running", elapsedMs, remainingMs: MISSION_MS - elapsedMs, surge });

describe("print registration from the printed artwork", () => {
  it("places every scenario map site inside the printed sheet", () => {
    const frame = makeFrame(worldToPrint);
    expect(frame.aligned).toBe(true);
    for (const s of fixture.scenario.sites.filter((s) => s.kind !== "control_start_pad")) {
      const p = frame.pt(s.board_uv);
      expect(p.x).toBeGreaterThan(0);
      expect(p.x).toBeLessThan(PRINT_W);
      expect(p.y).toBeGreaterThan(0);
      expect(p.y).toBeLessThan(PRINT_H);
    }
  });
  it("puts the restored crossing where the artwork shows the east bridge", () => {
    // nepalmap.png (1448 x 1086): the east crossing sits on the river at about (925, 458) px.
    const p = makeFrame(worldToPrint).pt(fixture.scenario.sites.find((s) => s.id === "crossing_east")!.board_uv);
    expect(Math.abs(p.x / PRINT_W - 925 / 1448)).toBeLessThan(0.01);
    expect(Math.abs(p.y / PRINT_H - 458 / 1086)).toBeLessThan(0.01);
  });
  it("uses the measured marker layout from the registered photo", () => {
    expect(BOARD_MARKERS).toEqual(registration.markers.map((m) => ({ id: m.id, center: m.center_uv })));
    expect(BOARD_MARKERS.map((m) => m.id)).toEqual([10, 11, 13, 12]);
    expect(MARKER_LAYOUT_VERIFIED).toBe(true);
  });
});

describe("projector keystone", () => {
  const src: [number, number][] = [[0, 0], [1920, 0], [1920, 1080], [0, 1080]];
  it("maps all four measured corners and round-trips points under perspective", () => {
    const dst: [number, number][] = [[32, 10], [1880, 51], [1902, 1031], [20, 1074]];
    const forward = solveHomography(src, dst);
    const inverse = solveHomography(dst, src);
    src.forEach((p, i) => applyHomography(forward, p).forEach((n, j) => expect(n).toBeCloseTo(dst[i][j], 7)));
    applyHomography(inverse, applyHomography(forward, [550, 780])).forEach((n, i) => expect(n).toBeCloseTo([550, 780][i], 7));
  });
  it("keeps default alignment and encodes the same affine/corner transform in CSS", () => {
    expect(targetCorners(DEFAULT_CALIBRATION, 1920, 1080)).toEqual(src);
    const cal = { ...DEFAULT_CALIBRATION, dx: 10, dy: -8, sx: 0.96, sy: 1.03, rot: 1.2 };
    const matrix = calibrationMatrix3d(cal, 1920, 1080).slice(9, -1).split(",").map(Number);
    src.forEach(([x, y], i) => {
      const w = matrix[3] * x + matrix[7] * y + matrix[15];
      expect((matrix[0] * x + matrix[4] * y + matrix[12]) / w).toBeCloseTo(targetCorners(cal, 1920, 1080)[i][0], 5);
    });
  });
  it("rejects degenerate corner measurements", () => expect(() => solveHomography(src, [[0, 0], [0, 0], [0, 0], [0, 0]])).toThrow(/degenerate/));
});

describe("projection palette", () => {
  it("detects the legacy yellow range, including both thresholds", () => {
    expect(looksLikeBridgeToCamera("#ffff00")).toBe(true);
    expect(looksLikeBridgeToCamera("#ffaa00")).toBe(true);
    expect(looksLikeBridgeToCamera("#ffffff")).toBe(false);
  });
  it.each(Object.entries(PALETTE))("%s stays outside the legacy bridge HSV filter", (_, hex) => expect(looksLikeBridgeToCamera(hex)).toBe(false));
});

describe("mission guide follows the backend, not the clock alone", () => {
  const s = fixture.states;
  it("names the isolated village and reveals Mission 1 at second 8", () => {
    const early = buildGuide(clockAt("WARNING", 3000), s.game_start);
    expect(early.story).toContain("Shyaphru Bensi");
    expect(early.focus).toEqual([]);
    const reveal = buildGuide(clockAt("WARNING", 8200), s.game_start);
    expect(reveal.title).toBe("MISSION 1: RESTORE THE CROSSING");
    expect(reveal.focus.map((f) => f.option.site_id)).toEqual(["crossing_east"]);
  });
  it("highlights only the crossing the reducer says reconnects people, then confirms it", () => {
    const before = buildGuide(clockAt("CROSSING", 15000), s.game_start);
    expect(before.step).toBe("PLACE THE BRIDGE ON THE GLOWING CROSSING");
    expect(before.fallback.map((o) => o.site_id)).toEqual(["crossing_east"]);
    const after = buildGuide(clockAt("CROSSING", 18000), s.game_bridge);
    expect(after.title).toBe("CROSSING RESTORED — ACCESS IMPROVED");
    expect(after.focus).toEqual([]);
  });
  it("offers a real choice between the service pieces the camera recognises", () => {
    const g = buildGuide(clockAt("RELIEF", 32000), s.game_bridge);
    expect(g.focus.map((f) => f.option.piece).sort()).toEqual(["food_shelter", "hospital"]);
    expect(g.title).toBe("MISSION 2: HOSPITAL OR FOOD STATION?");
    expect(guideFor(clockAt("RELIEF", 32000), s.game_bridge, ["bridge", "hospital", "food_shelter", "shelter"]).focus).toHaveLength(3);
    expect(g.focus.every((f) => f.detail?.startsWith("meets "))).toBe(true);
    expect(buildGuide(clockAt("RELIEF", 40000), s.game_service).title).toBe("HOSPITAL DEPLOYED");
  });
  it("points at the remaining response after the surge, from the backend preview", () => {
    const g = buildGuide(clockAt("SURGE", 55000, "accepted"), s.game_surge);
    expect(g.title).toBe("MISSION 3: ONE LAST CHANCE");
    expect(g.focus[0].option.piece).toBe("food_shelter");
    expect(s.game_surge.mission!.services).toContainEqual(g.focus[0].option);
  });
  it("gives piece-specific placement corrections", () => {
    expect(placementHint("bridge", "outside_site")).toBe("MOVE BRIDGE CLOSER TO THE GLOWING CROSSING");
    expect(placementHint("hospital", "outside_site")).toBe("MOVE HOSPITAL CLOSER TO A HIGHLIGHTED SITE");
    expect(placementHint("bridge", "detection_pending")).toBe("PIECE DETECTED");
  });
});

describe("Matsya's Guidance only repeats the backend ghost planner", () => {
  it("appears only when the snapshot carries a ghost_suggestion", () => {
    expect(matsyaGuidance(fixture.states.game_start)).toBeNull();
    const g = matsyaGuidance(fixture.states.game_guided)!;
    expect(g.suggestion).toEqual(fixture.states.game_guided.ghost_suggestion);
    expect(g.suggestion.site_id).toBe("crossing_east");
    expect(g.hint).toBe("Try placing the bridge here.");
    expect(matsyaGuidance(fixture.states.game_bridge)).toBeNull();
  });
});

describe("Boat of Hope is symbolic and tied to measured improvement", () => {
  it("starts dark at START and brightens only with real outcomes", () => {
    const start = boatOfHope(fixture.states.game_start)!;
    expect(start.lanterns.every((l) => l.light === 0)).toBe(true);
    const bridged = boatOfHope(fixture.states.game_bridge)!;
    expect(bridged.lanterns.find((l) => l.id === "family")!.light).toBe(1);
    const final = boatOfHope(fixture.states.game_final)!;
    expect(final.glow).toBeGreaterThan(bridged.glow);
    expect(boatOfHope(fixture.states.ready)).toBeNull();
  });
  it("ends with Manu's card stated from real outcomes", () => {
    const card = manuCard(fixture.states.game_final);
    expect(card.map((l) => l.id)).toEqual(["life", "family", "knowledge"]);
    const held = fixture.states.game_final.game!.interventions.filter((i) => i.effective).length;
    expect(card[2].text).toContain(`${held} of ${fixture.states.game_final.game!.interventions.length} decisions held`);
  });
});

describe("results use real metrics and the no-response baseline", () => {
  it("reports residents, services and improvement from the final snapshot", () => {
    const final = fixture.states.game_final;
    const r = buildResults(fixture.scenario, final);
    const game = final.game!;
    const pct = Math.round((100 * (game.baseline_unmet_total_model! - game.unmet_total_model!)) / game.baseline_unmet_total_model!);
    expect(r.impact.find((x) => x.id === "improvement")!.value).toBe(`+${pct}%`);
    expect(r.impact.find((x) => x.id === "residents")!.value).toMatch(/^\d+\/16$/);
    expect(r.decisions.some((d) => d.label === "Hospital" && !d.effective)).toBe(true);
  });
});

describe("scene rendering with actual backend snapshots", () => {
  const { scenario } = fixture;
  const reg = { ready: true, mapping_ready: true, world_to_print: worldToPrint, board: registration.board, markers: registration.markers.map((m) => ({ id: m.id, center_uv: m.center_uv as [number, number] })), marker_size_mm: Math.max(...Object.values(registration.aruco.marker_sizes_mm)) };
  const render = (phase: GamePhase, state: WorldSnapshot, surface: "screen" | "overlay" | "align" = "overlay", elapsed = 15000, syncing = false) => {
    const clock = clockAt(phase, elapsed, phase === "SURGE" ? "accepted" : "not_due");
    return renderToStaticMarkup(
      <ProjectionScene scenario={scenario} snapshot={state} model={buildBoardModel(scenario, state, [], true)} guide={buildGuide(clock, state)} clock={clock} reactions={[]} rejections={[]} pending={[]} surface={surface} variant="projector" results={buildResults(scenario, state)} resultsSyncing={syncing} registration={reg} />,
    );
  };
  it("is a white projection, with the printed artwork only on screen and align surfaces", () => {
    const overlay = render("CROSSING", fixture.states.game_start);
    expect(overlay).toContain('fill="#ffffff"');
    expect(overlay).not.toContain("layer-basemap");
    expect(render("CROSSING", fixture.states.game_start, "screen")).toContain("nepalmap");
    expect(render("CROSSING", fixture.states.game_start, "align")).toContain("ALIGN THE PROJECTOR TO THE PRINT");
    expect(overlay).not.toMatch(/NaN|undefined/);
  });
  it("shows the cut lifeline, the cut-off village and the crossing to fix", () => {
    const html = render("CROSSING", fixture.states.game_start);
    expect(html).toContain("lifeline-cut");
    expect(html).toContain("CUT OFF");
    expect(html).toContain("PLACE BRIDGE HERE");
    const after = render("CROSSING", fixture.states.game_bridge, "overlay", 18000);
    expect(after).toContain("lifeline-open");
    expect(after).toContain("bridge-outline");
    expect(after).toContain("traveller");
  });
  it("masks markers last and shows an impact summary instead of a win screen", () => {
    const html = render("RESULTS", fixture.states.game_final, "overlay", 75000);
    expect(html.indexOf("layer-markers")).toBeGreaterThan(html.indexOf('class="results"'));
    expect(html).toContain("MISSION COMPLETE · YOUR IMPACT");
    expect(html).toContain("Your decisions changed the outcome.");
    expect(html).not.toContain("YOU WIN");
    expect(render("RESULTS", fixture.states.game_final, "overlay", 75000, true)).toContain("SYNCING RESULTS");
  });
  it("reveals the no-response network beside the players' network", () => {
    const html = render("RESULTS", fixture.states.game_final, "overlay", 75000);
    expect(html).toContain("BEFORE · NO RESPONSE");
    expect(html).toContain("AFTER · YOUR PLAN");
    expect(html).toContain(`${fixture.states.game_final.game!.baseline_unmet_total_model} needs unmet · 1 village cut off`);
    expect(html).toContain(`${fixture.states.game_final.game!.unmet_total_model} needs unmet · every village connected`);
    expect(html).toContain("THE BOAT OF HOPE");
  });
  it("draws Matsya's Guidance and can hide the whole narrative layer", () => {
    const clock = clockAt("CROSSING", 19000);
    const state = fixture.states.game_guided;
    const scene = (narrative: boolean) => renderToStaticMarkup(<ProjectionScene scenario={scenario} snapshot={state} model={buildBoardModel(scenario, state, [], true)} guide={buildGuide(clock, state)} clock={clock} reactions={[]} rejections={[]} pending={[{ token_id: "t", board_uv: [0.3, 0.4], label: "PIECE DETECTED" }]} surface="overlay" variant="projector" results={null} registration={reg} narrative={narrative} />);
    expect(scene(true)).toContain("MATSYA&#x27;S GUIDANCE");
    expect(scene(true)).toContain("boat-of-hope");
    expect(scene(true)).toContain("PIECE DETECTED");
    expect(scene(false)).not.toContain("MATSYA&#x27;S GUIDANCE");
    expect(scene(false)).not.toContain("boat-of-hope");
    expect(scene(false)).toContain("PLACE BRIDGE HERE");
  });
  it("shows the idle Manu story and how to play before START", () => {
    const html = render("IDLE", fixture.states.ready, "overlay", 0);
    expect(html).toContain("Manu saved a small fish");
    expect(html).toContain("PRESS START ON THE LAPTOP");
  });
});
