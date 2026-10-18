import type { GameIntervention, WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { RESPONSE_COMPLETE } from "./story";
import { crossingsCarryingRoutes, totalNeed, totalPeople, unmetNeed } from "./worldAdapter";

// Final impact summary. Every number is read from the committed snapshot and the
// game layer's own no-response baseline (backend/world/game.py); a number whose source
// field is absent is omitted, never shown as 0. There is no "YOU WIN" tier.

export interface ResultRow {
  id: string;
  label: string;
  value: string;
  detail?: string;
  tone?: "good" | "bad";
}

export interface ImpactStat {
  id: "residents" | "services" | "improvement";
  value: string;
  label: string;
}

export interface Decision {
  label: string;
  effective: boolean;
  text: string;
}

export interface Results {
  headline: string;
  /** The three big numbers on the final screen. */
  impact: ImpactStat[];
  decisions: Decision[];
  rows: ResultRow[];
  score: { value: number; label: string } | null;
  unresolved: string[];
  improved: string[];
  unit: string;
  empty: boolean;
}

const MARGINAL_WORDS: [keyof GameIntervention["marginal"], string][] = [
  ["unmet_refuge_model", "refuge"],
  ["unmet_medical_model", "medical"],
  ["unmet_food_model", "food"],
];

function decisionText(i: GameIntervention): string {
  const parts: string[] = [];
  if (i.marginal.reachable_communities > 0) parts.push(`reconnected ${i.marginal.reachable_communities} community`);
  for (const [key, word] of MARGINAL_WORDS) if (i.marginal[key] < 0) parts.push(`met ${-i.marginal[key]} ${word} needs`);
  return parts.length ? parts.join(", ") : "no measured effect at the end";
}

/** Model people in communities that reach the depot and at least one essential service. */
export function residentsReachingHelp(snapshot: WorldSnapshot): number {
  const served = new Set((snapshot.service_routes ?? []).filter((r) => r.reachable).map((r) => r.population_id));
  return snapshot.population_demand.filter((d) => d.depot_reachable !== false && served.has(d.id)).reduce((n, d) => n + d.people_model, 0);
}

export function buildResults(scenario: ScenarioGeometry, snapshot: WorldSnapshot): Results {
  const game = snapshot.game?.status === "active" ? snapshot.game : null;
  const unit = snapshot.population_demand.some((d) => d.headcount_known === false) ? "model groups" : "model people";
  const empty: Results = { headline: RESPONSE_COMPLETE, impact: [], decisions: [], rows: [], score: null, unresolved: [], improved: [], unit, empty: true };
  if (!game || snapshot.phase !== "disaster_active") return empty;

  const impact: ImpactStat[] = [];
  const people = totalPeople(snapshot);
  if (people != null && people > 0) impact.push({ id: "residents", value: `${residentsReachingHelp(snapshot)}/${people}`, label: "Residents reach essential services" });
  const servingFacilities = snapshot.facilities.filter((f) => (f.active ?? true) && (snapshot.service_routes ?? []).some((r) => r.reachable && r.facility_id === f.id)).length;
  const crossings = crossingsCarryingRoutes(scenario, snapshot);
  const connectedBridges = snapshot.mission?.crossing_restored ? 1 : 0;
  impact.push({ id: "services", value: String(servingFacilities + Math.max(crossings, connectedBridges)), label: "Services & crossings restored" });
  const baseline = game.baseline_unmet_total_model;
  const unmet = game.unmet_total_model;
  if (baseline != null && unmet != null && baseline > 0) {
    const pct = Math.round((100 * (baseline - unmet)) / baseline);
    impact.push({ id: "improvement", value: `${pct > 0 ? "+" : ""}${pct}%`, label: "Needs met vs. no response" });
  }

  const rows: ResultRow[] = [];
  if (people != null && people > 0) {
    rows.push({ id: "refuge_access", label: "POPULATION WITH REFUGE ACCESS", value: `${snapshot.metrics.people_reachable_for_shelter} / ${people}`, detail: unit, tone: snapshot.metrics.people_reachable_for_shelter > 0 ? "good" : "bad" });
  }
  for (const [id, label, need] of [["food_met", "FOOD NEEDS MET", "food"], ["medical_met", "MEDICAL NEEDS MET", "medical"]] as const) {
    const total = totalNeed(snapshot, need);
    if (total == null || total === 0) continue;
    const met = total - Math.min(total, unmetNeed(snapshot, need));
    rows.push({ id, label, value: `${met} / ${total}`, detail: "model need units", tone: met === total ? "good" : met > 0 ? undefined : "bad" });
  }
  if (game.communities_reconnected != null) {
    rows.push({ id: "routes_restored", label: "CROSSINGS / ROUTES RESTORED", value: String(crossings), detail: `crossing(s) carrying a reachable route · ${game.communities_reconnected} community(ies) reconnected vs no response`, tone: crossings > 0 || game.communities_reconnected > 0 ? "good" : undefined });
  }
  if (baseline != null && unmet != null) {
    const delta = baseline - unmet;
    rows.push({ id: "baseline_change", label: "CHANGE VS. NO-RESPONSE BASELINE", value: `${delta >= 0 ? "−" : "+"}${Math.abs(delta)}`, detail: `unmet need units: ${baseline} with no response → ${unmet} now`, tone: delta > 0 ? "good" : undefined });
  }
  if (unmet != null && game.total_need_model != null) {
    rows.push({ id: "unmet_remaining", label: "UNMET NEEDS REMAINING", value: `${unmet} / ${game.total_need_model}`, detail: "model need units", tone: unmet > 0 ? "bad" : "good" });
  }

  return {
    headline: RESPONSE_COMPLETE,
    impact,
    decisions: game.interventions.map((i) => ({ label: i.label, effective: i.effective, text: decisionText(i) })),
    rows,
    score: { value: game.score, label: game.label },
    unresolved: game.summary?.unresolved ?? [],
    improved: game.summary?.improved ?? [],
    unit,
    empty: false,
  };
}
