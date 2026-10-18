import type { WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { RESPONSE_COMPLETE } from "./story";
import { crossingsCarryingRoutes, totalNeed, totalPeople, unmetNeed } from "./worldAdapter";

// Results screen rows (spec §9 "Results page (no imaginary values)"). Every row is
// read from the latest committed snapshot; a row whose source field is absent is
// omitted, never shown as 0. There are no outcome tiers: the live score exposes none.

export interface ResultRow {
  id: string;
  label: string;
  value: string;
  detail?: string;
  tone?: "good" | "bad";
}

export interface Results {
  headline: string;
  rows: ResultRow[];
  score: { value: number; label: string } | null;
  /** Plain statements of what remains unresolved, from snapshot.game.summary. */
  unresolved: string[];
  improved: string[];
  unit: string;
  /** Results reflect a non-started world (no mission state to report). */
  empty: boolean;
}

export function buildResults(scenario: ScenarioGeometry, snapshot: WorldSnapshot): Results {
  const game = snapshot.game?.status === "active" ? snapshot.game : null;
  const unit = snapshot.population_demand.some((d) => d.headcount_known === false) ? "model groups" : "model people";
  const rows: ResultRow[] = [];
  if (!game || snapshot.phase !== "disaster_active") {
    return { headline: RESPONSE_COMPLETE, rows, score: null, unresolved: [], improved: [], unit, empty: true };
  }

  const people = totalPeople(snapshot);
  if (people != null && people > 0) {
    rows.push({
      id: "refuge_access",
      label: "POPULATION WITH REFUGE ACCESS",
      value: `${snapshot.metrics.people_reachable_for_shelter} / ${people}`,
      detail: unit,
      tone: snapshot.metrics.people_reachable_for_shelter > 0 ? "good" : "bad",
    });
  }
  for (const [id, label, need] of [
    ["food_met", "FOOD NEEDS MET", "food"],
    ["medical_met", "MEDICAL NEEDS MET", "medical"],
  ] as const) {
    const total = totalNeed(snapshot, need);
    if (total == null || total === 0) continue;
    const met = total - Math.min(total, unmetNeed(snapshot, need));
    rows.push({ id, label, value: `${met} / ${total}`, detail: "model need units", tone: met === total ? "good" : met > 0 ? undefined : "bad" });
  }

  const crossings = crossingsCarryingRoutes(scenario, snapshot);
  const reconnected = game.communities_reconnected;
  if (reconnected != null) {
    rows.push({
      id: "routes_restored",
      label: "CROSSINGS / ROUTES RESTORED",
      value: String(crossings),
      detail: `crossing(s) carrying a reachable route · ${reconnected} community(ies) reconnected vs no response`,
      tone: crossings > 0 || reconnected > 0 ? "good" : undefined,
    });
  }

  if (game.baseline_unmet_total_model != null && game.unmet_total_model != null) {
    const delta = game.baseline_unmet_total_model - game.unmet_total_model;
    rows.push({
      id: "baseline_change",
      label: "CHANGE VS. NO-RESPONSE BASELINE",
      value: `${delta >= 0 ? "−" : "+"}${Math.abs(delta)}`,
      detail: `unmet need units: ${game.baseline_unmet_total_model} with no response → ${game.unmet_total_model} now`,
      tone: delta > 0 ? "good" : undefined,
    });
  }

  if (game.unmet_total_model != null && game.total_need_model != null) {
    rows.push({
      id: "unmet_remaining",
      label: "UNMET NEEDS REMAINING",
      value: `${game.unmet_total_model} / ${game.total_need_model}`,
      detail: "model need units",
      tone: game.unmet_total_model > 0 ? "bad" : "good",
    });
  }

  return {
    headline: RESPONSE_COMPLETE,
    rows,
    score: { value: game.score, label: game.label },
    unresolved: game.summary?.unresolved ?? [],
    improved: game.summary?.improved ?? [],
    unit,
    empty: false,
  };
}
