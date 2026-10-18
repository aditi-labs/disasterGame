import type { UV, WorldSnapshot } from "../../types/contracts";
import type { ScenarioGeometry } from "../../types/scenario";
import { boatOfHope, manuCard } from "../narrative";
import { PALETTE } from "../palette";
import type { Frame } from "../printFrame";
import type { Results } from "../results";
import { BoatOfHopeMark } from "./NarrativeLayer";

// Final reveal: the no-response baseline network next to the network the players
// built, then the real impact numbers. BEFORE comes only from snapshot.mission.baseline
// (the backend's same-stage, no-pieces world); AFTER is the committed final snapshot.
// If the backend sent no baseline view, the comparison is omitted, not imitated.

interface NetworkView {
  cut: UV[][];
  open: UV[][];
  blocked: string[];
  villages: { uv: UV; ok: boolean }[];
  facilities: UV[];
  unmet: number | null;
  cutOff: number;
}

function beforeView(scenario: ScenarioGeometry, s: WorldSnapshot): NetworkView | null {
  const b = s.mission?.baseline;
  if (!b) return null;
  const at = new Map(scenario.sites.map((x) => [x.id, x.board_uv]));
  const unmet = b.populations.reduce((n, p) => n + Object.values(p.unmet).reduce<number>((a, v) => a + (v ?? 0), 0), 0);
  return {
    cut: b.lifelines.filter((l) => !l.reachable && l.board_uv.length > 1).map((l) => l.board_uv),
    open: [],
    blocked: b.blocked_edge_ids,
    villages: b.populations.filter((p) => at.has(p.id)).map((p) => ({ uv: at.get(p.id)!, ok: p.depot_reachable !== false })),
    facilities: [],
    unmet: s.game?.baseline_unmet_total_model ?? unmet,
    cutOff: b.populations.filter((p) => p.depot_reachable === false).length,
  };
}

function afterView(scenario: ScenarioGeometry, s: WorldSnapshot): NetworkView {
  const at = new Map(scenario.sites.map((x) => [x.id, x.board_uv]));
  const routes = (s.service_routes ?? []).filter((r) => (r.board_uv?.length ?? 0) > 1);
  const lifelines = (s.mission?.lifelines ?? []).filter((l) => l.board_uv.length > 1);
  return {
    cut: [...lifelines.filter((l) => !l.reachable).map((l) => l.board_uv), ...routes.filter((r) => !r.reachable).map((r) => r.board_uv!)],
    open: [...lifelines.filter((l) => l.reachable).map((l) => l.board_uv), ...routes.filter((r) => r.reachable).map((r) => r.board_uv!)],
    blocked: s.edges.filter((e) => e.blocked).map((e) => e.id),
    villages: s.population_demand.filter((d) => at.has(d.id)).map((d) => ({ uv: at.get(d.id)!, ok: d.depot_reachable !== false })),
    facilities: s.facilities.filter((f) => (f.active ?? true) && routesServe(s, f.id)).map((f) => at.get(f.site_id ?? "") ?? null).filter((uv): uv is UV => !!uv),
    unmet: s.game?.unmet_total_model ?? null,
    cutOff: s.population_demand.filter((d) => d.depot_reachable === false).length,
  };
}

const routesServe = (s: WorldSnapshot, id: string) => (s.service_routes ?? []).some((r) => r.reachable && r.facility_id === id);

function MiniMap({ frame, scenario, view, x, y, w, h, label, after }: { frame: Frame; scenario: ScenarioGeometry; view: NetworkView; x: number; y: number; w: number; h: number; label: string; after: boolean }) {
  // Crop to the playable area: every map site plus a margin, in print units.
  const pts = scenario.sites.filter((s) => s.kind !== "control_start_pad").map((s) => frame.pt(s.board_uv));
  const pad = 90;
  let bx = Math.min(...pts.map((p) => p.x)) - pad, by = Math.min(...pts.map((p) => p.y)) - pad;
  let bw = Math.max(...pts.map((p) => p.x)) + pad - bx, bh = Math.max(...pts.map((p) => p.y)) + pad - by;
  if (bw / bh > w / h) { const nh = (bw * h) / w; by -= (nh - bh) / 2; bh = nh; } else { const nw = (bh * w) / h; bx -= (nw - bw) / 2; bw = nw; }
  const roads = new Map(scenario.roads.map((r) => [r.id, r.path]));
  return (
    <g className={`mini mini-${after ? "after" : "before"}`}>
      <rect x={x} y={y} width={w} height={h} rx={18} className="mini-frame" />
      <svg x={x} y={y} width={w} height={h} viewBox={`${bx} ${by} ${bw} ${bh}`} preserveAspectRatio="xMidYMid meet">
        {scenario.rivers.map((r, i) => <path key={i} d={frame.d(r)} className="mini-river" />)}
        {scenario.roads.map((r) => <path key={r.id} d={frame.d(r.path)} className="mini-road" />)}
        {view.blocked.map((id) => roads.get(id) && <path key={id} d={frame.d(roads.get(id)!)} className="mini-blocked" />)}
        {view.cut.map((p, i) => <path key={`c${i}`} d={frame.d(p)} className="mini-cut" />)}
        {view.open.map((p, i) => (
          <g key={`o${i}`}>
            <path d={frame.d(p)} className="mini-open" style={{ animationDelay: `${0.6 + i * 0.15}s` }} />
            <path d={frame.d(p)} className="route-flow" />
          </g>
        ))}
        {view.facilities.map((uv, i) => { const c = frame.pt(uv); return <circle key={`f${i}`} cx={c.x} cy={c.y} r={20} className="mini-facility" />; })}
        {view.villages.map((v, i) => { const c = frame.pt(v.uv); return <circle key={`v${i}`} cx={c.x} cy={c.y} r={26} className={v.ok ? "mini-village-ok" : "mini-village-cut"} />; })}
      </svg>
      <text x={x + w / 2} y={y - 14} className={`mini-label ${after ? "tone-good" : "tone-danger"}`}>{label}</text>
      <text x={x + w / 2} y={y + h + 36} className="mini-caption">
        {`${view.unmet != null ? `${view.unmet} needs unmet` : ""}${view.unmet != null ? " · " : ""}${view.cutOff ? `${view.cutOff} village cut off` : "every village connected"}`}
      </text>
    </g>
  );
}

function twoLines(label: string): string[] {
  const words = label.split(" ");
  if (words.length < 3) return [label];
  const half = Math.ceil(words.length / 2);
  return [words.slice(0, half).join(" "), words.slice(half).join(" ")];
}

export function ImpactReveal({ frame, scenario, snapshot, results, syncing, narrative }: { frame: Frame; scenario: ScenarioGeometry; snapshot: WorldSnapshot | null; results: Results; syncing?: boolean; narrative: boolean }) {
  const x0 = frame.W * 0.13;
  const w = frame.W * 0.74;
  const cx = frame.W / 2;
  const before = snapshot ? beforeView(scenario, snapshot) : null;
  const after = snapshot ? afterView(scenario, snapshot) : null;
  const boat = narrative ? boatOfHope(snapshot) : null;
  const card = narrative ? manuCard(snapshot) : [];
  const mapW = (w - 90) / 2;
  const mapH = 330;
  const statsY = before ? 660 : 380;
  const col = w / Math.max(1, results.impact.length);
  return (
    <g className="results" pointerEvents="none">
      <rect width={frame.W} height={frame.H} fill={PALETTE.paper} opacity={0.88} />
      <rect x={x0} y={18} width={w} height={frame.H - 36} rx={28} className="hud-panel" />
      <text x={cx} y={62} className="hud-chapter" textAnchor="middle">CHAPTER V · THE NEW DAWN</text>
      <text x={cx} y={116} className="results-head">{syncing ? "SYNCING RESULTS…" : `${results.headline} · YOUR IMPACT`}</text>
      <text x={cx} y={156} className="results-line">Your decisions changed the outcome.</text>
      {results.empty ? (
        <text x={cx} y={300} className="results-line">No mission state to report.</text>
      ) : (
        <>
          {before && after && (
            <>
              <MiniMap frame={frame} scenario={scenario} view={before} x={x0 + 30} y={214} w={mapW} h={mapH} label="BEFORE · NO RESPONSE" after={false} />
              <MiniMap frame={frame} scenario={scenario} view={after} x={x0 + 60 + mapW} y={214} w={mapW} h={mapH} label="AFTER · YOUR PLAN" after />
              <path d={`M${cx - 18} ${214 + mapH / 2} l22 0 m-10 -12 l12 12 l-12 12`} className="reveal-arrow" />
            </>
          )}
          {results.impact.map((s, i) => (
            <g key={s.id} transform={`translate(${x0 + col * (i + 0.5)} ${statsY})`} className="impact-stat-svg" style={{ animationDelay: `${1.2 + i * 0.25}s` }}>
              <text className={`impact-value impact-${s.id}`}>{s.value}</text>
              {twoLines(s.label).map((l, j) => <text key={l} y={42 + j * 26} className="impact-label">{l}</text>)}
            </g>
          ))}
          {boat && card.length > 0 && (
            <g className="manu-card" transform={`translate(${x0 + 60} ${statsY + 120})`} style={{ animationDelay: "2s" }}>
              <g transform="translate(80 120)"><BoatOfHopeMark boat={boat} scale={1.5} /></g>
              <text x={200} y={36} className="manu-title">THE BOAT OF HOPE</text>
              {card.map((l, i) => (
                <text key={l.id} x={200} y={78 + i * 40} className="manu-line"><tspan className="manu-key">{l.title}</tspan>{`  ${l.text}`}</text>
              ))}
              <text x={200} y={78 + card.length * 40 + 16} className="results-manu" style={{ textAnchor: "start" }}>Like Manu, you were asked to protect life, family and knowledge.</text>
            </g>
          )}
        </>
      )}
      <text x={cx} y={frame.H - 34} className="results-note">Model figures from this educational scenario, compared with the same flood and no response.</text>
    </g>
  );
}
