import type { Facility, ServiceKind, ServiceRoute, TokenType, UV, WorldSnapshot } from "../types/contracts";
import { TOKEN_SITE_KIND } from "../types/contracts";
import type { RoadGeometry, ScenarioGeometry, SiteGeometry } from "../types/scenario";

// Real snapshot -> visible layers (spec §4 game/worldAdapter.ts). Pure and read-only:
// every flag below is copied or grouped from fields the backend computed. The UI never
// routes, never scores and never decides that a placement is legal; "valid pad" is
// only a highlight hint drawn from the same snapshot, and the backend still rules.

export const SERVICE_OF: Partial<Record<TokenType, ServiceKind>> = {
  hospital: "medical",
  food_shelter: "food",
  shelter: "refuge",
};
export const SERVICES: ServiceKind[] = ["refuge", "medical", "food"];

export type PopulationStatus = "danger" | "access" | "unknown";

export interface PopulationMark {
  siteId: string;
  uv: UV;
  /** Model people from the scenario record; null when the backend has no demand row. */
  peopleModel: number | null;
  headcountKnown: boolean;
  status: PopulationStatus;
  /** Per-service reachability, only for services the backend routed. */
  services: Partial<Record<ServiceKind, boolean>>;
  /** Capacity-bounded unmet units at this node (sum of the three needs), when reported. */
  unmet: number | null;
}

export interface FacilityMark {
  tokenId: string;
  type: TokenType;
  siteId: string | null;
  uv: UV;
  active: boolean;
  supplied: boolean;
  used: number;
  capacity: number;
  full: boolean;
  /** At least one population's reachable route ends here. */
  serving: boolean;
  provenance: string;
}

export interface BridgeMark {
  tokenId: string;
  siteId: string | null;
  uv: UV;
  rotation: number;
  /** The crossing edge this pad restores is open in the snapshot. */
  connected: boolean;
  /** A reachable service route uses that edge. */
  carriesRoute: boolean;
  provenance: string;
}

export interface PathMark {
  id: string;
  path: UV[];
}

export interface PadMark {
  siteId: string;
  uv: UV;
  piece: TokenType;
  rotation: number;
}

export interface BoardModel {
  active: boolean;
  stage: number;
  blocked: PathMark[];
  /** Mapped edges carrying at least one reachable service route. */
  open: PathMark[];
  /** Would-be paths of unreachable routes, minus edges an open route already draws. */
  cut: PathMark[];
  populations: PopulationMark[];
  facilities: FacilityMark[];
  bridges: BridgeMark[];
  pads: PadMark[];
  ghost: WorldSnapshot["ghost_suggestion"] | null;
}

const routeKey = (r: ServiceRoute) => `${r.population_id}|${r.service}`;
export { routeKey };

function roadMap(scenario: ScenarioGeometry): Map<string, RoadGeometry> {
  return new Map(scenario.roads.map((r) => [r.id, r]));
}

function siteMap(scenario: ScenarioGeometry): Map<string, SiteGeometry> {
  return new Map(scenario.sites.map((s) => [s.id, s]));
}

/** Population access straight from the snapshot: depot reachability and routed services. */
export function populationStatus(snapshot: WorldSnapshot, siteId: string): PopulationStatus {
  if (snapshot.phase !== "disaster_active") return "unknown";
  const demand = snapshot.population_demand.find((d) => d.id === siteId);
  if (!demand) return "unknown";
  const routes = (snapshot.service_routes ?? []).filter((r) => r.population_id === siteId);
  if (demand.depot_reachable === false || routes.some((r) => !r.reachable)) return "danger";
  if (demand.depot_reachable === true) return "access";
  // Older snapshots without depot_reachable: only routed services can speak for access.
  return routes.length > 0 ? "access" : "unknown";
}

function facilityProvenance(snapshot: WorldSnapshot, tokenId: string): string {
  return snapshot.tokens.find((t) => t.id === tokenId)?.vision_source ?? "unknown";
}

export function buildBoardModel(
  scenario: ScenarioGeometry,
  snapshot: WorldSnapshot,
  relevantPieces: TokenType[],
  inputOpen: boolean,
): BoardModel {
  const roads = roadMap(scenario);
  const sites = siteMap(scenario);
  const active = snapshot.phase === "disaster_active";
  const routes = snapshot.service_routes ?? [];
  const edgeBlocked = new Map(snapshot.edges.map((e) => [e.id, e.blocked]));

  const path = (id: string): PathMark | null => {
    const r = roads.get(id);
    return r ? { id, path: r.path } : null;
  };
  const marks = (ids: Iterable<string>) => [...ids].sort().map(path).filter((m): m is PathMark => m !== null);

  const openIds = new Set(routes.filter((r) => r.reachable).flatMap((r) => r.edge_ids));
  const cutIds = new Set(routes.filter((r) => !r.reachable).flatMap((r) => r.edge_ids).filter((id) => !openIds.has(id)));

  const populations: PopulationMark[] = scenario.sites
    .filter((s) => s.kind === "population_node")
    .map((s) => {
      const demand = snapshot.population_demand.find((d) => d.id === s.id);
      const services: Partial<Record<ServiceKind, boolean>> = {};
      for (const r of routes) if (r.population_id === s.id) services[r.service] = r.reachable;
      const unmetParts = demand ? [demand.unmet_food, demand.unmet_medical, demand.unmet_refuge] : [];
      return {
        siteId: s.id,
        uv: s.board_uv,
        peopleModel: demand ? demand.people_model : null,
        headcountKnown: demand ? demand.headcount_known !== false : false,
        status: populationStatus(snapshot, s.id),
        services,
        unmet: demand && unmetParts.every((n) => typeof n === "number") ? unmetParts.reduce<number>((a, n) => a + (n as number), 0) : null,
      };
    });

  const facilities: FacilityMark[] = snapshot.facilities.flatMap((f: Facility) => {
    const token = snapshot.tokens.find((t) => t.id === f.id);
    const site = f.site_id ? sites.get(f.site_id) : undefined;
    const uv = token?.board_uv ?? site?.board_uv;
    if (!uv) return [];
    return [{
      tokenId: f.id,
      type: f.type,
      siteId: f.site_id ?? null,
      uv,
      active: f.active ?? true,
      supplied: f.reachable,
      used: f.used_capacity_model,
      capacity: f.capacity_model,
      full: f.capacity_model > 0 && f.used_capacity_model >= f.capacity_model,
      serving: routes.some((r) => r.reachable && r.facility_id === f.id),
      provenance: facilityProvenance(snapshot, f.id),
    }];
  });

  const bridges: BridgeMark[] = snapshot.tokens
    .filter((t) => t.type === "bridge")
    .map((t) => {
      const site = t.site_id ? sites.get(t.site_id) : undefined;
      const edge = site?.edge_id;
      return {
        tokenId: t.id,
        siteId: t.site_id ?? null,
        uv: t.board_uv,
        rotation: site?.rotation_deg ?? t.rotation_deg ?? 0,
        connected: edge ? edgeBlocked.get(edge) === false : false,
        carriesRoute: edge ? routes.some((r) => r.reachable && r.edge_ids.includes(edge)) : false,
        provenance: t.vision_source,
      };
    });

  const occupied = new Set(snapshot.tokens.map((t) => t.site_id));
  const budget = snapshot.budget_remaining_model;
  const pads: PadMark[] = [];
  if (active && inputOpen) {
    for (const piece of relevantPieces) {
      if ((snapshot.token_inventory[piece] ?? 0) <= 0) continue;
      const kind = TOKEN_SITE_KIND[piece];
      for (const s of scenario.sites) {
        if (s.kind !== kind || occupied.has(s.id)) continue;
        if (budget != null && s.resource_cost != null && s.resource_cost > budget) continue;
        // A bridge only helps where the backend reports its crossing edge closed.
        if (piece === "bridge" && !(s.edge_id && edgeBlocked.get(s.edge_id) === true)) continue;
        pads.push({ siteId: s.id, uv: s.board_uv, piece, rotation: s.rotation_deg ?? 0 });
      }
    }
  }

  return {
    active,
    stage: snapshot.simulation_stage,
    blocked: marks(snapshot.edges.filter((e) => e.blocked).map((e) => e.id)),
    open: marks(openIds),
    cut: marks(cutIds),
    populations,
    facilities,
    bridges,
    pads,
    ghost: snapshot.ghost_suggestion ?? null,
  };
}

/** Sum of a need across populations the backend reported; null if none reported. */
export function totalNeed(snapshot: WorldSnapshot, need: ServiceKind): number | null {
  if (!snapshot.population_demand.length) return null;
  const key = need === "medical" ? "need_medical" : need === "food" ? "need_food" : "need_refuge";
  return snapshot.population_demand.reduce((n, d) => n + d[key], 0);
}

export function unmetNeed(snapshot: WorldSnapshot, need: ServiceKind): number {
  const m = snapshot.metrics;
  return need === "medical" ? m.unmet_medical_model : need === "food" ? m.unmet_food_model : m.unmet_refuge_model;
}

export function peopleReachable(snapshot: WorldSnapshot, need: ServiceKind): number {
  const m = snapshot.metrics;
  return need === "medical" ? m.people_reachable_for_medical : need === "food" ? m.people_reachable_for_food : m.people_reachable_for_shelter;
}

export function totalPeople(snapshot: WorldSnapshot): number | null {
  return snapshot.population_demand.length ? snapshot.population_demand.reduce((n, d) => n + d.people_model, 0) : null;
}

/**
 * Crossings whose bridge carries a reachable service route, by the same definition
 * backend/world/game.py uses for the "restore_access" objective.
 */
export function crossingsCarryingRoutes(scenario: ScenarioGeometry, snapshot: WorldSnapshot): number {
  const sites = siteMap(scenario);
  const routes = snapshot.service_routes ?? [];
  return snapshot.tokens.filter((t) => {
    if (t.type !== "bridge" || !t.site_id) return false;
    const edge = sites.get(t.site_id)?.edge_id;
    return !!edge && routes.some((r) => r.reachable && r.edge_ids.includes(edge));
  }).length;
}
