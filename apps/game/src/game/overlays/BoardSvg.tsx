import { useMemo } from "react";
import type { ObjectObservation, UV, WorldSnapshot } from "../../types/contracts";
import type { RoadGeometry, ScenarioGeometry } from "../../types/scenario";
import { BOARD_HEIGHT, BOARD_WIDTH, toSvgPoint, uvToPathD, uvToPoints } from "../../types/geometry";
import type { ActiveReaction } from "../../live/useLiveWorld";
import { BOARD_MARKERS, MARKER_KEEPOUT_HALF_UV } from "../board";
import type { RejectionCue } from "../channel";
import type { ClockView } from "../clock";
import { PALETTE } from "../palette";
import type { Cue } from "../reactions";
import type { Results } from "../results";
import { BEATS, FLOOD_UPDATE_UNAVAILABLE, PIECE_NAME, SUBTITLE, TITLE } from "../story";
import type { BoardModel, PopulationMark } from "../worldAdapter";
import { FloodLayer } from "./FloodLayer";
import { PIECE_COLOR, PieceGlyph, PopulationCluster } from "./glyphs";

// The projected board, used full-size on /projector and as the operator's mini map.
// Layers draw only the BoardModel (authoritative snapshot) plus short-lived cues.
// surface="overlay": over the printed map — no basemap, markers masked to black.
// surface="screen":  rehearsal on a screen — subdued basemap from /scenario geometry.

export interface BoardSvgProps {
  scenario: ScenarioGeometry;
  snapshot: WorldSnapshot | null;
  model: BoardModel | null;
  clock: ClockView;
  reactions: ActiveReaction[];
  rejections: RejectionCue[];
  pending: ObjectObservation[];
  surface: "overlay" | "screen";
  variant: "projector" | "operator";
  results: Results | null;
  resultsSyncing?: boolean;
  connectionLost?: boolean;
  /** Neutral hold-state text (no numbers): LIVE DATA UNAVAILABLE etc. */
  hold?: string | null;
  testPattern?: boolean;
  onSiteClick?: (siteId: string) => void;
  highlightSite?: string | null;
}

const S = (uv: UV) => toSvgPoint(uv[0], uv[1]);

function polylineLength(path: UV[]): number {
  let n = 0;
  for (let i = 1; i < path.length; i++) {
    const a = S(path[i - 1]);
    const b = S(path[i]);
    n += Math.hypot(b.x - a.x, b.y - a.y);
  }
  return n;
}

function fmtClock(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `0:${String(s).padStart(2, "0")}`;
}

export function BoardSvg(props: BoardSvgProps) {
  const { scenario, snapshot, model, clock, reactions, rejections, pending, surface, variant, results, hold, testPattern, onSiteClick, highlightSite } = props;
  const roads = useMemo(() => new Map(scenario.roads.map((r) => [r.id, r])), [scenario]);
  const phase = clock.phase;
  const idle = phase === "IDLE" || phase === "INTRO";
  const compact = variant === "operator";
  const now = Date.now();
  const live = reactions.filter((r) => r.until > now);
  const latest = live[live.length - 1];
  const W = BOARD_WIDTH;
  const H = BOARD_HEIGHT;

  return (
    <svg className={`board board-${surface} board-${variant}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" role={onSiteClick ? "group" : "img"} aria-label="FLOODSHIFT projected board">
      <defs>
        <pattern id="hatch-danger" width={7} height={7} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1={0} y1={0} x2={0} y2={7} stroke={PALETTE.dangerHatch} strokeWidth={1.2} opacity={0.75} />
        </pattern>
        <radialGradient id="vignette" cx="50%" cy="50%" r="72%">
          <stop offset="62%" stopColor="#000" stopOpacity={0} />
          <stop offset="100%" stopColor="#000" stopOpacity={0.55} />
        </radialGradient>
        <filter id="soft-glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="2.4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* 1 · Base: rehearsal basemap only; the printed board already carries the map. */}
      {surface === "screen" ? <Basemap scenario={scenario} /> : <rect width={W} height={H} fill="#000" />}
      <rect width={W} height={H} fill="url(#vignette)" pointerEvents="none" />

      {/* 2 · Idle: a restrained current along the actual mapped river; no flood is shown. */}
      {idle && (
        <g className="layer-current" pointerEvents="none">
          {scenario.rivers.map((r, i) => (
            <path key={i} d={uvToPathD(r)} className="river-current" style={{ animationDelay: `${(i % 4) * 0.6}s` }} />
          ))}
        </g>
      )}

      {/* 3 · Flood: backend stage + scenario geometry only. */}
      {snapshot && <FloodLayer scenario={scenario} stage={snapshot.simulation_stage} active={snapshot.phase === "disaster_active" && !idle} />}

      {model && !idle && (
        <>
          {/* 4 · Affected population markers: bounded halos at recorded points (no parcel footprints in this dataset). */}
          <g className="layer-danger" pointerEvents="none">
            {model.populations.filter((p) => p.status === "danger").map((p) => {
              const c = S(p.uv);
              return (
                <g key={p.siteId} transform={`translate(${c.x} ${c.y})`}>
                  <circle r={34} fill="url(#hatch-danger)" />
                  <circle r={34} fill={PALETTE.danger} opacity={0.18} />
                  <circle r={34} fill="none" stroke={PALETTE.danger} strokeWidth={1.4} opacity={0.8} />
                </g>
              );
            })}
          </g>

          {/* 5 · Routes: would-be paths dashed rust, blocked edges dashed rust, reachable routes mint. */}
          <g className="layer-routes" pointerEvents="none">
            {model.cut.map((e) => (
              <path key={`cut-${e.id}`} d={uvToPathD(e.path)} className="route-cut" />
            ))}
            {model.blocked.map((e) => (
              <path key={`blk-${e.id}`} d={uvToPathD(e.path)} className="road-blocked" />
            ))}
            {model.open.map((e) => (
              <path key={`ok-${e.id}`} d={uvToPathD(e.path)} className="route-open" />
            ))}
          </g>

          {/* 6 · Valid pads: corner brackets, only where the current mission could use them. */}
          <g className="layer-pads" pointerEvents="none">
            {model.pads.map((p) => {
              const c = S(p.uv);
              return (
                <g key={`${p.siteId}-${p.piece}`} transform={`translate(${c.x} ${c.y})`} className="pad">
                  <Brackets r={22} />
                  <circle r={3} className="pad-dot" />
                  {!compact && (
                    <text y={38} className="pad-label">
                      {PIECE_NAME[p.piece]}
                    </text>
                  )}
                </g>
              );
            })}
          </g>

          {/* 7 · Ghost bridge hint: violet, clearly SUGGESTED, at the backend's real pad. */}
          {model.ghost && <Ghost uv={model.ghost.board_uv} rotation={model.ghost.rotation_deg ?? 0} previewEdges={model.ghost.preview_edge_ids ?? []} roads={roads} />}

          {/* 8 · Accepted pieces: rings around the physical piece (never over it) + emblem badge. */}
          <g className="layer-pieces" pointerEvents="none">
            {model.bridges.map((b) => {
              const c = S(b.uv);
              return (
                <g key={b.tokenId} transform={`translate(${c.x} ${c.y})`}>
                  <circle r={30} className={`piece-ring ${b.connected ? "on" : "off"}`} style={{ stroke: b.connected ? PALETTE.route : PALETTE.bridge }} />
                  <g transform="translate(32 -30)">
                    <PieceGlyph type="bridge" size={14} color={b.connected ? PALETTE.routeBright : PALETTE.bridge} />
                  </g>
                </g>
              );
            })}
            {model.facilities.map((f) => {
              const c = S(f.uv);
              const on = f.active && f.supplied;
              const color = PIECE_COLOR[f.type] ?? PALETTE.text;
              return (
                <g key={f.tokenId} transform={`translate(${c.x} ${c.y})`}>
                  {on && <circle r={36} fill={color} opacity={0.1} filter="url(#soft-glow)" />}
                  <circle r={30} className={`piece-ring ${on ? "on" : "off"} ${f.full ? "full" : ""}`} style={{ stroke: color }} />
                  <g transform="translate(32 -30)">
                    <PieceGlyph type={f.type} size={14} />
                  </g>
                  <text y={48} className={`cap-label ${f.full ? "full" : ""}`} fontSize={compact ? 10 : 11}>
                    {!on ? "NO ACCESS" : f.full ? `FULL ${f.used}/${f.capacity}` : `${f.used}/${f.capacity}`}
                  </text>
                </g>
              );
            })}
          </g>
        </>
      )}

      {/* 9 · Population groups at their recorded points: cream (unknown), rose (danger), mint (access). */}
      {!idle && model && (
        <g className="layer-population" pointerEvents="none">
          {model.populations.map((p) => (
            <Population key={p.siteId} p={p} compact={compact} />
          ))}
        </g>
      )}
      {idle && (
        <g className="layer-idle-sites" pointerEvents="none">
          {scenario.sites
            .filter((s) => s.kind !== "control_start_pad")
            .map((s) => {
              const c = S(s.board_uv);
              return <circle key={s.id} cx={c.x} cy={c.y} r={s.kind === "population_node" ? 10 : 7} className={`idle-site idle-${s.kind}`} />;
            })}
        </g>
      )}

      {/* 10 · Camera candidates not yet accepted: dim pending contour, never a route. */}
      {!idle && (
        <g className="layer-pending" pointerEvents="none">
          {pending.map((o) => {
            const c = S(o.board_uv);
            return <circle key={o.token_id} cx={c.x} cy={c.y} r={26} className="pending-ring" />;
          })}
        </g>
      )}

      {/* 11 · Snapshot-diff cues (≤ ~2 s), then the static state above stays readable. */}
      {!idle && (
        <g className="layer-cues" pointerEvents="none">
          {live.map((set) => (
            <g key={set.key}>
              {set.cues.map((c) => (
                <CueMark key={c.id} c={c} roads={roads} />
              ))}
            </g>
          ))}
          {rejections.map((r) => {
            const c = S(r.uv);
            return (
              <g key={r.id} transform={`translate(${c.x} ${c.y})`} className="reject">
                <circle r={28} className="reject-ring" />
                <text y={-40} className="reject-text" fontSize={compact ? 11 : 13}>
                  {r.text}
                </text>
              </g>
            );
          })}
          {live.map((set) =>
            set.pieceLabel ? (
              <text key={`pl-${set.key}`} x={S(set.pieceLabel.uv).x} y={S(set.pieceLabel.uv).y + 66} className={`piece-label tone-${set.pieceLabel.tone}`} fontSize={compact ? 10 : 12}>
                {set.pieceLabel.text}
              </text>
            ) : null,
          )}
        </g>
      )}

      {/* 12 · Compact edge HUD: mission line top centre, timer top edge; never in marker keep-outs. */}
      {!compact && <Hud phase={phase} clock={clock} headline={latest?.headline ?? null} headlineKey={latest?.key ?? ""} />}

      {/* 13 · Results: map dims, real snapshot fields only. */}
      {phase === "RESULTS" && results && !compact && <ResultsCard results={results} syncing={props.resultsSyncing} />}
      {props.connectionLost && !hold && !compact && (
        <text x={W / 2} y={H - 60} className="hold-text">CONNECTION LOST · LAST CONFIRMED STATE</text>
      )}

      {/* 14 · Hold state when live data is missing: no numbers, no map consequences. */}
      {hold && (
        <g className="layer-hold">
          <rect width={W} height={H} fill="#000" opacity={surface === "overlay" ? 1 : 0.86} />
          <text x={W / 2} y={H / 2 - 18} className="title">
            {TITLE}
          </text>
          <text x={W / 2} y={H / 2 + 14} className="subtitle">
            {SUBTITLE}
          </text>
          <text x={W / 2} y={H / 2 + 56} className="hold-text">
            {hold}
          </text>
        </g>
      )}

      {/* 15 · Registration test: reticles and board outline only (not a game state). */}
      {testPattern && <TestPattern />}

      {/* 16 · ArUco keep-outs. Overlay: solid black (no projected light on markers). */}
      <g className="layer-markers" pointerEvents="none">
        {BOARD_MARKERS.map((m) => {
          const c = S(m.center);
          const h = MARKER_KEEPOUT_HALF_UV * W;
          return surface === "overlay" ? (
            <rect key={m.id} x={c.x - h} y={c.y - h} width={h * 2} height={h * 2} fill="#000" />
          ) : (
            <g key={m.id}>
              <rect x={c.x - h} y={c.y - h} width={h * 2} height={h * 2} className="marker-box" />
              <text x={c.x} y={c.y + 4} className="marker-id">
                {m.id}
              </text>
            </g>
          );
        })}
      </g>

      {/* Operator click-to-pad diagnostics: the same live action the camera would cause. */}
      {onSiteClick && (
        <g className="layer-hit">
          {scenario.sites
            .filter((s) => s.kind !== "control_start_pad" && s.kind !== "population_node")
            .map((s) => {
              const c = S(s.board_uv);
              return (
                <circle key={s.id} cx={c.x} cy={c.y} r={24} role="button" tabIndex={0} aria-label={`${s.label} (${s.id})`} className={`site-hit ${highlightSite === s.id ? "selected" : ""}`} onClick={() => onSiteClick(s.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSiteClick(s.id); } }}>
                  <title>{`${s.label} (${s.id})`}</title>
                </circle>
              );
            })}
        </g>
      )}
    </svg>
  );
}

function Basemap({ scenario }: { scenario: ScenarioGeometry }) {
  return (
    <g className="layer-basemap" pointerEvents="none">
      <rect width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="#10161c" />
      {scenario.rivers.map((r, i) => (
        <path key={i} d={uvToPathD(r)} className="base-river" />
      ))}
      {scenario.roads.map((r) => (
        <path key={r.id} d={uvToPathD(r.path)} className={`base-road base-${r.kind}`} />
      ))}
      {scenario.labels.map((l) => {
        const p = S(l.board_uv);
        return (
          <text key={l.text} x={p.x} y={p.y - 18} className="base-label">
            {l.text}
          </text>
        );
      })}
    </g>
  );
}

function Brackets({ r }: { r: number }) {
  const k = r * 0.45;
  return (
    <path
      className="pad-brackets"
      d={`M${-r} ${-r + k} V${-r} H${-r + k} M${r - k} ${-r} H${r} V${-r + k} M${r} ${r - k} V${r} H${r - k} M${-r + k} ${r} H${-r} V${r - k}`}
    />
  );
}

function Ghost({ uv, rotation, previewEdges, roads }: { uv: UV; rotation: number; previewEdges: string[]; roads: Map<string, RoadGeometry> }) {
  const c = S(uv);
  return (
    <g className="layer-ghost" pointerEvents="none">
      {previewEdges.map((id) => {
        const r = roads.get(id);
        return r ? <path key={id} d={uvToPathD(r.path)} className="ghost-route" /> : null;
      })}
      <g transform={`translate(${c.x} ${c.y}) rotate(${rotation})`} className="ghost-bridge">
        <rect x={-34} y={-11} width={68} height={22} rx={3} />
        <path d="M-28 -11 V11 M-9 -11 V11 M9 -11 V11 M28 -11 V11" />
      </g>
      <text x={c.x} y={c.y - 30} className="ghost-label">
        SUGGESTED
      </text>
    </g>
  );
}

function Population({ p, compact }: { p: PopulationMark; compact: boolean }) {
  const c = S(p.uv);
  const color = p.status === "danger" ? PALETTE.danger : p.status === "access" ? PALETTE.route : PALETTE.cream;
  return (
    <g transform={`translate(${c.x} ${c.y})`}>
      <PopulationCluster color={color} />
      {p.unmet != null && p.unmet > 0 && p.status === "access" && <circle r={16} className="need-ring" />}
      {!compact && p.peopleModel != null && (
        <>
          {p.status === "danger" && (
            <text y={48} className="pop-tag">
              AFFECTED POPULATION
            </text>
          )}
          <text y={p.status === "danger" ? 61 : 48} className="pop-count">
            {p.peopleModel} {p.headcountKnown ? "MODEL PEOPLE" : "MODEL GROUP"}
          </text>
        </>
      )}
    </g>
  );
}

function CueMark({ c, roads }: { c: Cue; roads: Map<string, RoadGeometry> }) {
  const at = c.uv ? S(c.uv) : null;
  switch (c.kind) {
    case "halo":
      return at ? (
        <g transform={`translate(${at.x} ${at.y})`}>
          <circle r={30} className="cue-halo" />
          <circle r={30} className="cue-rim" />
        </g>
      ) : null;
    case "removed":
      return at ? <circle cx={at.x} cy={at.y} r={30} className="cue-off" /> : null;
    case "edge_restored":
    case "edge_blocked":
      return (
        <g className={`cue-${c.kind}`}>
          {(c.edgeIds ?? []).map((id) => {
            const r = roads.get(id);
            return r ? <path key={id} d={uvToPathD(r.path)} className="cue-edge" /> : null;
          })}
        </g>
      );
    case "route_opened": {
      if (!c.path || c.path.length < 2) return null;
      const len = polylineLength(c.path);
      const d = uvToPathD(c.path);
      return (
        <g>
          <path d={d} className="cue-route-draw" style={{ ["--len" as string]: len.toFixed(1) }} />
          {/* One cosmetic dot travels the computed route once; it changes no state. */}
          <circle r={4.5} className="cue-dot">
            <animateMotion dur="1.4s" begin="0.15s" fill="freeze" path={d} />
          </circle>
        </g>
      );
    }
    case "route_lost":
      return c.path && c.path.length >= 2 ? <polyline points={uvToPoints(c.path)} className="cue-route-lost" /> : null;
    case "population_danger":
      return at ? <circle cx={at.x} cy={at.y} r={34} className="cue-pop-danger" /> : null;
    case "population_access":
      return at ? <circle cx={at.x} cy={at.y} r={30} className="cue-pop-access" /> : null;
    case "flood_advance":
      return null; // the FloodLayer stage mount carries its own lip animation
    default:
      return null;
  }
}

function Hud({ phase, clock, headline, headlineKey }: { phase: BoardSvgProps["clock"]["phase"]; clock: ClockView; headline: { text: string; tone: string } | null; headlineKey: string }) {
  const beat = BEATS[phase];
  const W = BOARD_WIDTH;
  if (phase === "IDLE") {
    return (
      <g className="hud" pointerEvents="none">
        <text x={W / 2} y={90} className="title">
          {TITLE}
        </text>
        <text x={W / 2} y={120} className="subtitle">
          {SUBTITLE}
        </text>
        <text x={W / 2} y={150} className="hud-line">
          {beat.line}
        </text>
      </g>
    );
  }
  if (phase === "INTRO") {
    return (
      <g className="hud hud-intro" pointerEvents="none">
        <rect width={W} height={BOARD_HEIGHT} fill="#000" opacity={0.7} />
        <text x={W / 2} y={BOARD_HEIGHT / 2} className="intro-line">
          {beat.line}
        </text>
        <FishCurrent key="intro" y={BOARD_HEIGHT / 2 + 40} />
      </g>
    );
  }
  const running = clock.mode === "running" || clock.mode === "paused";
  return (
    <g className="hud" pointerEvents="none">
      <text key={`h-${phase}`} x={W / 2} y={44} className={`mission ${phase === "WARNING" ? "warning" : ""}`}>
        {beat.headline}
      </text>
      <text key={`l-${phase}`} x={W / 2} y={70} className="hud-line">
        {beat.line}
      </text>
      {headline ? (
        <text key={headlineKey} x={W / 2} y={98} className={`cue-headline tone-${headline.tone}`}>
          {headline.text}
        </text>
      ) : beat.objective ? (
        <text x={W / 2} y={98} className="objective">
          {beat.objective}
        </text>
      ) : null}
      {phase === "SURGE" && clock.surge === "failed" && (
        <text x={W / 2} y={122} className="hud-note">
          {FLOOD_UPDATE_UNAVAILABLE}
        </text>
      )}
      {running && (
        <text x={880} y={44} className={`timer ${clock.mode === "paused" ? "paused" : ""}`}>
          {clock.mode === "paused" ? "PAUSED" : fmtClock(clock.remainingMs)}
        </text>
      )}
      {/* Matsya motif: a fish-tail current at each act transition, in the bottom margin. */}
      <FishCurrent key={`fish-${phase}`} y={BOARD_HEIGHT - 26} />
    </g>
  );
}

function FishCurrent({ y }: { y: number }) {
  const x0 = 170;
  const x1 = 780;
  const d = `M${x0} ${y} C${x0 + 120} ${y - 10} ${x0 + 220} ${y + 10} ${x0 + 330} ${y} S${x1 - 120} ${y - 8} ${x1} ${y}`;
  return (
    <g className="fish-current">
      <path d={d} className="fish-line" />
      <path d={`M${x1} ${y} l14 -9 l-4 9 l4 9 z`} className="fish-tail" />
    </g>
  );
}

function ResultsCard({ results, syncing }: { results: Results; syncing?: boolean }) {
  const W = BOARD_WIDTH;
  const H = BOARD_HEIGHT;
  const rows = results.rows;
  const cardW = 600;
  const cardH = 150 + rows.length * 34 + (results.score ? 30 : 0);
  const x = (W - cardW) / 2;
  const y = Math.max(140, (H - cardH) / 2);
  return (
    <g className="results" pointerEvents="none">
      <rect width={W} height={H} fill="#000" opacity={0.42} />
      <rect x={x} y={y} width={cardW} height={cardH} rx={6} className="results-card" />
      <text x={W / 2} y={y + 44} className="results-head">
        {syncing ? "SYNCING RESULTS" : results.headline}
      </text>
      {results.empty ? (
        <text x={W / 2} y={y + 84} className="hud-line">
          No mission state to report.
        </text>
      ) : (
        rows.map((r, i) => (
          <g key={r.id} transform={`translate(${x + 34} ${y + 92 + i * 34})`}>
            <text className="results-label">{r.label}</text>
            <text x={cardW - 68} className={`results-value tone-${r.tone ?? "info"}`}>
              {r.value}
            </text>
            {r.detail && (
              <text y={14} className="results-detail">
                {r.detail}
              </text>
            )}
          </g>
        ))
      )}
      {results.score && (
        <text x={W / 2} y={y + cardH - 22} className="results-score">
          GAME SCORE {results.score.value} · model comparison, not a real-world outcome
        </text>
      )}
    </g>
  );
}

function TestPattern() {
  const W = BOARD_WIDTH;
  const H = BOARD_HEIGHT;
  // Rehearsal reticles are inset beyond the photo-estimated print marker masks.
  const pts: UV[] = [
    [0.18, 0.18],
    [0.82, 0.18],
    [0.82, 0.82],
    [0.18, 0.82],
    [0.5, 0.5],
  ];
  return (
    <g className="layer-test" pointerEvents="none">
      <rect x={2} y={2} width={W - 4} height={H - 4} className="test-border" />
      {pts.map(([u, v], i) => {
        const c = toSvgPoint(u, v);
        return (
          <g key={i}>
            <path d={`M${c.x - 26} ${c.y} H${c.x + 26} M${c.x} ${c.y - 26} V${c.y + 26}`} className="test-cross" />
            <circle cx={c.x} cy={c.y} r={12} className="test-cross" fill="none" />
          </g>
        );
      })}
    </g>
  );
}
