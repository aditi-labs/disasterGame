import { describe, expect, it } from "vitest";
import { buildBoardModel, populationStatus, crossingsCarryingRoutes } from "../src/game/worldAdapter";
import { diffSnapshots } from "../src/game/reactions";
import { buildResults } from "../src/game/results";
import { fixture } from "./fixtures";

const { scenario, states: s } = fixture;
describe("real HOT snapshot adapter", () => {
  it("draws the backend's road polylines and depot access without computing a route", () => {
    const model = buildBoardModel(scenario, s.connected, [], true);
    expect(model.populations.map(p => p.siteId)).toEqual(scenario.sites.filter(x => x.kind === "population_node").map(x => x.id));
    expect(populationStatus(s.started, "people_east")).toBe("danger");
    expect(populationStatus(s.connected, "people_east")).toBe("access");
    for (const path of [...model.open, ...model.blocked, ...model.cut]) expect(path.path).toEqual(scenario.roads.find(r => r.id === path.id)!.path);
    expect(model.open.length).toBeGreaterThan(0);
    expect(model.bridges[0].carriesRoute).toBe(true);
  });
  it("highlights pads only with matching inventory, budget, occupancy, and a closed edge", () => {
    const available = buildBoardModel(scenario, s.started, ["bridge"], true).pads;
    expect(available.length).toBeGreaterThan(0);
    expect(available.every(p => p.piece === "bridge")).toBe(true);
    expect(buildBoardModel(scenario, s.connected, ["bridge"], true).pads).toEqual([]);
    expect(buildBoardModel(scenario, { ...s.started, budget_remaining_model: 0 }, ["bridge"], true).pads).toEqual([]);
    expect(buildBoardModel(scenario, s.started, ["bridge"], false).pads).toEqual([]);
    expect(buildBoardModel(scenario, s.ready, ["bridge"], true).pads).toEqual([]);
  });
  it("leaves unknown population access unknown and omits facilities with no real position", () => {
    expect(populationStatus(s.ready, "people_east")).toBe("unknown");
    expect(populationStatus(s.started, "missing")).toBe("unknown");
    const partial = { ...s.connected, tokens: [], facilities: s.connected.facilities.map(f => ({ ...f, site_id: null })) };
    expect(buildBoardModel(scenario, partial, [], false).facilities).toEqual([]);
  });
});

describe("snapshot-driven reactions", () => {
  it("announces restored routes only after the actual bridge outcome", () => {
    const reaction = diffSnapshots(s.services, s.connected, scenario)!;
    expect(reaction.headline?.text).toBe("CROSSING RESTORED — ACCESS IMPROVED");
    expect(reaction.cues.some(c => c.kind === "halo")).toBe(true);
    for (const cue of reaction.cues.filter(c => c.kind === "route_opened")) expect(s.connected.service_routes!.some(r => r.reachable && JSON.stringify(r.board_uv) === JSON.stringify(cue.path))).toBe(true);
    expect(diffSnapshots(s.connected, s.connected, scenario)).toBeNull();
    expect(diffSnapshots(null, s.connected, scenario)).toBeNull();
  });
  it("removes the old bridge glow and reports lost routes after a real move/removal", () => {
    const moved = diffSnapshots(s.connected, s.moved, scenario)!;
    expect(moved.cues.some(c => c.kind === "removed")).toBe(true);
    expect(moved.cues.some(c => c.kind === "halo")).toBe(true);
    expect(moved.cues.some(c => c.kind === "route_lost")).toBe(true);
    expect(moved.headline?.text).toBe("MOVE CONFIRMED · ACCESS LOST");
    expect(moved.pieceLabel?.text).toBe("MOVE CONFIRMED");
    expect(crossingsCarryingRoutes(scenario, s.moved)).toBe(0);
    const removed = diffSnapshots(s.moved, s.removed, scenario)!;
    expect(removed.cues.some(c => c.kind === "removed")).toBe(true);
    expect(removed.cues.some(c => c.kind === "halo")).toBe(false);
  });
  it("does not animate a rejected surge or a reset as successful play", () => {
    expect(s.failed_surge).toEqual(s.surged);
    expect(diffSnapshots(s.surged, s.failed_surge, scenario)).toBeNull();
    expect(diffSnapshots(s.connected, s.reset, scenario)).toMatchObject({ replaced: true, cues: [], headline: null });
  });
});

describe("surge reactions name what the flood actually cut", () => {
  it("reports the hospital cut off when the surge removes its last route", () => {
    const reaction = diffSnapshots(s.game_service, s.game_surge, scenario)!;
    expect(reaction.headline).toEqual({ text: "HOSPITAL CUT OFF BY FLOODWATER", tone: "bad" });
    expect(reaction.cues.some(c => c.kind === "flood_advance")).toBe(true);
  });
  it("counts the need units a placed service actually meets", () => {
    const reaction = diffSnapshots(s.game_surge, s.game_final, scenario)!;
    const met = s.game_surge.metrics.unmet_food_model - s.game_final.metrics.unmet_food_model;
    expect(reaction.headline?.text).toBe(`FOOD STATION OPEN — ${met} FOOD NEEDS MET`);
    expect(reaction.pieceLabel?.text).toBe("PLACEMENT ACCEPTED");
  });
});

describe("truthful model outcomes", () => {
  it("uses backend score, capacity-bounded needs and the actual baseline", () => {
    const result = buildResults(scenario, s.connected);
    expect(result.headline).toBe("MISSION COMPLETE");
    expect(result.score?.value).toBe(s.connected.game!.score);
    const food = s.connected.population_demand.reduce((sum, d) => sum + d.need_food, 0);
    expect(result.rows.find(r => r.id === "food_met")?.value).toBe(`${food - s.connected.metrics.unmet_food_model} / ${food}`);
    expect(result.rows.find(r => r.id === "routes_restored")?.value).toBe(String(crossingsCarryingRoutes(scenario, s.connected)));
    expect(result.unresolved).toEqual(s.connected.game!.summary!.unresolved);
  });
  it("does not invent score, baseline or population counts when absent", () => {
    expect(buildResults(scenario, s.ready)).toMatchObject({ empty: true, score: null, rows: [] });
    expect(buildResults(scenario, { ...s.connected, game: null }).score).toBeNull();
    const partial = structuredClone(s.connected);
    delete partial.game!.baseline_unmet_total_model;
    partial.population_demand = [];
    const result = buildResults(scenario, partial);
    expect(result.rows.some(r => r.id === "baseline_change" || r.id === "refuge_access" || r.id === "food_met")).toBe(false);
  });
});
