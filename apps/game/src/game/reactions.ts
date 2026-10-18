import type { PlacedToken, ServiceKind, ServiceRoute, TokenType, UV, WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";
import { ACTIVE_LABEL, PIECE_NAME } from "./story";
import { peopleReachable, populationStatus, routeKey, SERVICE_OF, unmetNeed } from "./worldAdapter";

// Snapshot diff -> visual cues (spec §8 "World reaction to visual reaction mapping").
// Ported from floodshift- frontend/src/lib/worldReactions.ts and re-worded to the
// spec's copy. Every cue is backed by a difference between two accepted
// authoritative snapshots; mouse, operator and camera actions all react identically
// because all of them arrive as snapshots.

export type Tone = "good" | "bad" | "info";

export type CueKind =
  | "halo" // accepted placement: one expanding halo at the piece
  | "removed" // piece lifted: light turns off
  | "edge_restored"
  | "edge_blocked"
  | "route_opened" // newly reachable route: stroke on + one travelling dot
  | "route_lost"
  | "population_danger"
  | "population_access"
  | "flood_advance";

export interface Cue {
  id: string;
  kind: CueKind;
  tone: Tone;
  uv?: UV;
  edgeIds?: string[];
  path?: UV[];
  service?: ServiceKind;
  piece?: TokenType;
  stage?: number;
}

export interface ReactionSet {
  /** scenario:branch:version: identical deliveries of one snapshot react once. */
  key: string;
  cues: Cue[];
  /** One short line for the board, chosen by priority and only if the state supports it. */
  headline: { text: string; tone: Tone } | null;
  /** Tiny label beside the piece that changed (fades after ~1.5 s). */
  pieceLabel: { uv: UV; text: string; tone: Tone } | null;
  scoreDelta: number | null;
  /** Reset/branch load: the world was replaced, not changed by one intervention. */
  replaced: boolean;
  /** START: the mission began (setup, not a player decision). */
  started: boolean;
}

export function snapshotKey(s: WorldSnapshot): string {
  return `${s.scenario_id}:${s.branch_id}:${s.world_version}`;
}

const SERVICE_WORD: Record<ServiceKind, string> = { refuge: "REFUGE", medical: "MEDICAL", food: "FOOD" };

function byId<T extends { id: string }>(items: T[]): Map<string, T> {
  return new Map(items.map((i) => [i.id, i]));
}

export function diffSnapshots(prev: WorldSnapshot | null, next: WorldSnapshot, scenario: ScenarioGeometry): ReactionSet | null {
  if (!prev || snapshotKey(prev) === snapshotKey(next) || prev.scenario_id !== next.scenario_id) return null;
  const key = snapshotKey(next);
  const cues: Cue[] = [];
  const add = (c: Omit<Cue, "id">) => cues.push({ ...c, id: `${key}#${cues.length}` });

  const replaced =
    next.branch_id !== prev.branch_id ||
    next.world_version < prev.world_version ||
    (prev.phase === "disaster_active" && next.phase === "ready");
  if (replaced) return { key, cues, headline: null, pieceLabel: null, scoreDelta: null, replaced: true, started: false };

  const started = prev.phase === "ready" && next.phase === "disaster_active";
  if (next.simulation_stage > prev.simulation_stage) add({ kind: "flood_advance", tone: "bad", stage: next.simulation_stage });

  const sites = new Map(scenario.sites.map((s) => [s.id, s]));
  const prevTokens = byId(prev.tokens);
  const nextTokens = byId(next.tokens);
  const isGamePiece = (t: PlacedToken) => t.type !== "disaster_start" && t.type !== "person";
  const added = next.tokens.filter((t) => isGamePiece(t) && (!prevTokens.has(t.id) || prevTokens.get(t.id)!.site_id !== t.site_id));
  const removed = prev.tokens.filter((t) => isGamePiece(t) && (!nextTokens.has(t.id) || nextTokens.get(t.id)!.site_id !== t.site_id));
  const moved = added.filter((t) => prevTokens.has(t.id));

  const prevEdges = byId(prev.edges);
  const restoredEdges = next.edges.filter((e) => !e.blocked && prevEdges.get(e.id)?.blocked).map((e) => e.id);
  const blockedEdges = next.edges.filter((e) => e.blocked && prevEdges.get(e.id) && !prevEdges.get(e.id)!.blocked).map((e) => e.id);
  if (restoredEdges.length) add({ kind: "edge_restored", tone: "good", edgeIds: restoredEdges });
  if (blockedEdges.length) add({ kind: "edge_blocked", tone: "bad", edgeIds: blockedEdges });

  const prevRoutes = new Map((prev.service_routes ?? []).map((r) => [routeKey(r), r]));
  const nextRoutes = new Map((next.service_routes ?? []).map((r) => [routeKey(r), r]));
  const opened = [...nextRoutes.values()].filter((r) => r.reachable && !prevRoutes.get(routeKey(r))?.reachable);
  const lost = [...prevRoutes.values()].filter((r) => r.reachable && !nextRoutes.get(routeKey(r))?.reachable);
  for (const r of opened) add({ kind: "route_opened", tone: "good", service: r.service, edgeIds: r.edge_ids, path: r.board_uv ?? undefined });
  for (const r of lost) {
    const now = nextRoutes.get(routeKey(r));
    add({ kind: "route_lost", tone: "bad", service: r.service, edgeIds: r.edge_ids, path: (now?.board_uv ?? r.board_uv) ?? undefined });
  }

  for (const s of scenario.sites.filter((s) => s.kind === "population_node")) {
    const was = populationStatus(prev, s.id);
    const is = populationStatus(next, s.id);
    if (is === "danger" && was !== "danger") add({ kind: "population_danger", tone: "bad", uv: s.board_uv });
    if (is === "access" && was === "danger") add({ kind: "population_access", tone: "good", uv: s.board_uv });
  }

  for (const t of added) add({ kind: "halo", tone: "good", uv: t.board_uv, piece: t.type });
  // A moved piece appears in both lists: its old site turns off, its new site gets the halo.
  for (const t of removed) add({ kind: "removed", tone: "info", uv: t.board_uv, piece: t.type });

  const communities = (next.metrics.reachable_communities ?? 0) - (prev.metrics.reachable_communities ?? 0);
  const prevScore = prev.game?.status === "active" ? prev.game.score : null;
  const nextScore = next.game?.status === "active" ? next.game.score : null;
  const scoreDelta = !started && prevScore != null && nextScore != null && nextScore !== prevScore ? nextScore - prevScore : null;

  const changes = { added, removed, moved, opened, lost, restoredEdges, communities };
  return {
    key,
    cues,
    headline: started ? null : headline(prev, next, changes),
    pieceLabel: started ? null : pieceLabel(next, sites, changes),
    scoreDelta,
    replaced: false,
    started,
  };
}

interface Changes {
  added: PlacedToken[];
  removed: PlacedToken[];
  moved: PlacedToken[];
  opened: ServiceRoute[];
  lost: ServiceRoute[];
  restoredEdges: string[];
  communities: number;
}

function improved(prev: WorldSnapshot, next: WorldSnapshot, service: ServiceKind): boolean {
  return unmetNeed(next, service) < unmetNeed(prev, service) || peopleReachable(next, service) > peopleReachable(prev, service);
}

function headline(prev: WorldSnapshot, next: WorldSnapshot, c: Changes): ReactionSet["headline"] {
  if (next.simulation_stage > prev.simulation_stage) {
    const affected = next.population_demand.some((d) => populationStatus(next, d.id) === "danger" && populationStatus(prev, d.id) !== "danger");
    // The dataset gives these nodes no reviewed area name, so none is invented.
    return { text: affected ? "POPULATION AREA AFFECTED" : `FLOOD STAGE ${next.simulation_stage}`, tone: "bad" };
  }

  const placed = c.added[0];
  if (placed && placed.type === "bridge") {
    if (c.opened.length) return { text: "ROUTE RESTORED", tone: "good" };
    if (c.communities > 0) return { text: "ACCESS RESTORED", tone: "good" };
    return { text: "BRIDGE PLACED · NO NEW ACCESS", tone: "info" };
  }
  if (placed) {
    const service = SERVICE_OF[placed.type];
    if (service) {
      if (improved(prev, next, service)) return { text: `${SERVICE_WORD[service]} ACCESS IMPROVED`, tone: "good" };
      return { text: "PLACED · ACCESS STILL LIMITED", tone: "bad" };
    }
  }

  const gone = c.removed.find((t) => !c.moved.some((m) => m.id === t.id));
  if (gone) {
    const name = PIECE_NAME[gone.type] ?? gone.type.toUpperCase();
    const lostAccess = c.lost.length > 0 || c.communities < 0;
    return { text: lostAccess ? `${name} REMOVED · ACCESS LOST` : `${name} REMOVED`, tone: lostAccess ? "bad" : "info" };
  }
  if (c.opened.length || c.communities > 0) return { text: "ACCESS RESTORED", tone: "good" };
  if (c.lost.length || c.communities < 0) return { text: "ACCESS LOST", tone: "bad" };
  return null;
}

function pieceLabel(next: WorldSnapshot, sites: Map<string, { edge_id?: string }>, c: Changes): ReactionSet["pieceLabel"] {
  const t = c.added[0];
  if (!t) return null;
  if (t.type === "bridge") {
    const edge = t.site_id ? sites.get(t.site_id)?.edge_id : undefined;
    const connected = !!edge && c.restoredEdges.includes(edge);
    return { uv: t.board_uv, text: connected ? ACTIVE_LABEL.bridge! : "BRIDGE PLACED", tone: connected ? "good" : "info" };
  }
  const f = next.facilities.find((x) => x.id === t.id);
  const serving = !!f && (f.active ?? true) && f.reachable && (next.service_routes ?? []).some((r) => r.reachable && r.facility_id === t.id);
  return { uv: t.board_uv, text: serving ? (ACTIVE_LABEL[t.type] ?? "ACTIVE") : "PLACED · ACCESS STILL LIMITED", tone: serving ? "good" : "bad" };
}
