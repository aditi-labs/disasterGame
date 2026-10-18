import type { WorldSnapshot } from "../types/contracts";
import { residentsReachingHelp } from "./results";
import { totalPeople } from "./worldAdapter";

// The Boat of Hope: a symbolic narrative layer, deliberately NOT a score. Its three
// lanterns echo what Manu's boat carried through the flood — life, family, and the
// Vedas (knowledge) — and each brightens only from outcomes the backend already
// measured, relative to its own no-response baseline, so every lantern starts dark at
// START and lights only when the players' pieces actually change something.
// No numbers are shown on the boat; the real metrics stay on the impact screen.

export interface Lantern {
  id: "life" | "family" | "knowledge";
  /** 0..1 brightness. */
  light: number;
}

export interface BoatOfHope {
  lanterns: Lantern[];
  /** 0..1 overall glow (mean of the lanterns). */
  glow: number;
}

const clamp = (n: number) => (Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0);

export function boatOfHope(snapshot: WorldSnapshot | null): BoatOfHope | null {
  const game = snapshot?.phase === "disaster_active" && snapshot.game?.status === "active" ? snapshot.game : null;
  if (!snapshot || !game || !game.baseline || !game.current) return null;
  const people = totalPeople(snapshot) ?? 0;
  // Life: residents who can now reach an essential service (none can with no response).
  const life = people > 0 ? residentsReachingHelp(snapshot) / people : 0;
  // Family: communities reconnected to supplies, out of those the flood cut off.
  const total = game.communities_total ?? snapshot.population_demand.length;
  const cut = total - game.baseline.reachable_communities;
  const family = cut > 0 ? (game.current.reachable_communities - game.baseline.reachable_communities) / cut : 0;
  // Knowledge: essential needs met beyond the no-response baseline.
  const base = game.baseline_unmet_total_model ?? 0;
  const knowledge = base > 0 ? (base - (game.unmet_total_model ?? base)) / base : 0;
  const lanterns: Lantern[] = [
    { id: "life", light: clamp(life) },
    { id: "family", light: clamp(family) },
    { id: "knowledge", light: clamp(knowledge) },
  ];
  return { lanterns, glow: lanterns.reduce((n, l) => n + l.light, 0) / lanterns.length };
}

export interface NarrativeLine {
  id: Lantern["id"];
  title: string;
  text: string;
}

/** Final card: Manu's responsibility, stated with the real outcome behind each line. */
export function manuCard(snapshot: WorldSnapshot | null): NarrativeLine[] {
  const game = snapshot?.phase === "disaster_active" && snapshot.game?.status === "active" ? snapshot.game : null;
  if (!snapshot || !game) return [];
  const people = totalPeople(snapshot);
  const lines: NarrativeLine[] = [];
  if (people) lines.push({ id: "life", title: "LIFE", text: `${residentsReachingHelp(snapshot)} of ${people} residents can reach essential care.` });
  if (game.current && game.communities_total) lines.push({ id: "family", title: "FAMILY", text: `${game.current.reachable_communities} of ${game.communities_total} communities stay connected to supplies.` });
  if (game.interventions.length) {
    const held = game.interventions.filter((i) => i.effective).length;
    lines.push({ id: "knowledge", title: "KNOWLEDGE", text: `${held} of ${game.interventions.length} decisions held — carry what worked to the next flood.` });
  }
  return lines;
}
