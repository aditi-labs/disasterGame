import { useMemo } from "react";
import type { MissionOption, ObjectObservation, ProjectionRegistration, ServiceKind, TokenType, UV, WorldSnapshot } from "../../types/contracts";
import type { ScenarioGeometry } from "../../types/scenario";
import type { ActiveReaction } from "../../live/useLiveWorld";
import { BOARD_MARKERS, MARKER_KEEPOUT_HALF_UV } from "../board";
import type { RejectionCue } from "../channel";
import type { ClockView } from "../clock";
import { MISSION_MS } from "../clock";
import type { Focus, Guide } from "../guide";
import { PALETTE } from "../palette";
import { makeFrame, polylineLength, SAFE, type Frame } from "../printFrame";
import type { Cue } from "../reactions";
import type { Results } from "../results";
import { BEATS, CHAPTERS, HOW_TO_PLAY, MANU_STORY, MANU_TODAY, PIECE_NAME, SUBTITLE, TITLE } from "../story";
import type { GamePhase } from "../clock";
import type { BoardModel, PopulationMark } from "../worldAdapter";
import { FloodLayer } from "./FloodLayer";
import { MatsyaMark, PIECE_COLOR, PieceGlyph, PopulationCluster } from "./glyphs";
import { BoatOfHopeMark, MatsyaGuide } from "./NarrativeLayer";
import { ImpactReveal } from "./ImpactReveal";
import { boatOfHope } from "../narrative";
import mapArtwork from "../../../../../nepalmap.png";

// The projected board, laid out in PRINT space (see printFrame.ts) on a white field.
//   surface="overlay": over the printed map. White light, no basemap; markers and
//                      camera-measured pieces are masked black so the camera keeps seeing them.
//   surface="screen":  rehearsal on a monitor: the printed artwork itself is the basemap.
//   surface="align":   the artwork at full strength so the projector can be keystoned
//                      until projected rivers and roads sit exactly on the printed ones.
// Layers draw only the BoardModel (authoritative snapshot), the Guide (clock + the
// backend's mission previews) and short-lived snapshot-diff cues.

export interface ProjectionSceneProps {
  scenario: ScenarioGeometry;
  snapshot: WorldSnapshot | null;
  model: BoardModel | null;
  guide: Guide;
  clock: ClockView;
  reactions: ActiveReaction[];
  rejections: RejectionCue[];
  /** Camera candidates not yet accepted; label = "PIECE DETECTED" / "CHECKING PLACEMENT". */
  pending: (Pick<ObjectObservation, "token_id" | "board_uv"> & { label?: string })[];
  surface: "overlay" | "screen" | "align";
  variant: "projector" | "operator";
  results: Results | null;
  resultsSyncing?: boolean;
  connectionLost?: boolean;
  /** Neutral hold-state text (no numbers): LIVE DATA UNAVAILABLE etc. */
  hold?: string | null;
  testPattern?: boolean;
  onSiteClick?: (siteId: string) => void;
  highlightSite?: string | null;
  registration?: ProjectionRegistration | null;
  /** Camera-measured piece footprints, print UV. */
  occlusions?: UV[][];
  /** Rehearsal note when an accepted rejection carried no board position. */
  notices?: string[];
  /** Mythic narrative layer (Matsya's Guidance, Boat of Hope, Manu card). Default on. */
  narrative?: boolean;
}

const NEED_ICON: { need: ServiceKind; piece: TokenType }[] = [
  { need: "refuge", piece: "shelter" },
  { need: "medical", piece: "hospital" },
  { need: "food", piece: "food_shelter" },
];

export function ProjectionScene(props: ProjectionSceneProps) {
  const { scenario, snapshot, model, guide, clock, reactions, rejections, pending, surface, variant, results, hold, testPattern, onSiteClick, highlightSite } = props;
  const frame = useMemo(() => makeFrame(props.registration?.world_to_print ?? null), [props.registration?.world_to_print]);
  const phase = clock.phase;
  const idle = phase === "IDLE" || phase === "INTRO";
  const compact = variant === "operator";
  const now = Date.now();
  const live = reactions.filter((r) => r.until > now);
  const latest = live[live.length - 1];
  const roads = useMemo(() => new Map(scenario.roads.map((r) => [r.id, r])), [scenario]);
  const names = new Map((snapshot?.mission?.populations ?? []).map((p) => [p.id, p.name]));
  const footprints = props.occlusions ?? [];
  const showResults = phase === "RESULTS" && !!results && !compact;
  const narrative = props.narrative !== false;
  const boat = narrative ? boatOfHope(snapshot) : null;
  const P = frame.pt;

  /** Ring radius around a piece: its camera footprint when measured, else the pad tolerance. */
  const pieceRadius = (uv: UV) => {
    const at = P(uv);
    let radius = 48;
    for (const f of footprints) {
      const pts = f.map(frame.printPt);
      const c = { x: pts.reduce((n, p) => n + p.x, 0) / pts.length, y: pts.reduce((n, p) => n + p.y, 0) / pts.length };
      const extent = Math.max(...pts.map((p) => Math.hypot(p.x - c.x, p.y - c.y)));
      if (Math.hypot(at.x - c.x, at.y - c.y) <= extent) radius = Math.max(radius, ...pts.map((p) => Math.hypot(p.x - at.x, p.y - at.y) + 10));
    }
    return radius;
  };

  return (
    <svg className={`scene scene-${surface} scene-${variant}`} data-projector-design="print-white-v4" viewBox={`0 0 ${frame.W} ${frame.H}`} preserveAspectRatio="xMidYMid meet" role={onSiteClick ? "group" : "img"} aria-label="FLOODSHIFT projected board">
      <defs>
        <filter id="soft-light" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
        <filter id="text-halo" x="-10%" y="-30%" width="120%" height="160%">
          <feMorphology in="SourceAlpha" operator="dilate" radius="3" result="d" />
          <feFlood floodColor="#fff" />
          <feComposite in2="d" operator="in" result="halo" />
          <feMerge>
            <feMergeNode in="halo" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* 1 · Base: white light over the print, or the printed artwork on a screen. */}
      <rect width={frame.W} height={frame.H} fill={PALETTE.paper} />
      {surface !== "overlay" && (frame.aligned ? <image href={mapArtwork} width={frame.W} height={frame.H} preserveAspectRatio="none" className="layer-basemap" opacity={surface === "align" ? 1 : 0.92} /> : <VectorBasemap scenario={scenario} frame={frame} />)}

      {surface === "align" && <AlignGuide frame={frame} />}

      {surface !== "align" && (
        <>
          {/* 2 · Flood: backend stage + scenario geometry only. */}
          {snapshot && !idle && <FloodLayer scenario={scenario} frame={frame} stage={snapshot.simulation_stage} active={snapshot.phase === "disaster_active"} />}

          {model && snapshot && !idle && (
            <>
              <Routes frame={frame} model={model} snapshot={snapshot} roads={roads} />
              <Populations frame={frame} model={model} names={names} compact={compact} />
              <WanderingPeople frame={frame} model={model} />
              <Travellers frame={frame} snapshot={snapshot} />
              {!showResults && <FocusTargets frame={frame} focus={guide.focus} compact={compact} pulse={phase === "WARNING"} />}
              <Pieces frame={frame} model={model} radius={pieceRadius} compact={compact} />
              {narrative && guide.matsya && !showResults && <MatsyaGuide frame={frame} guidance={guide.matsya} compact={compact} />}
              {/* Camera candidates not yet accepted: violet "checking" ring, never a route. */}
              <g className="layer-pending" pointerEvents="none">
                {pending.map((o) => {
                  const c = P(o.board_uv);
                  return (
                    <g key={o.token_id} transform={`translate(${c.x} ${c.y})`}>
                      <circle r={pieceRadius(o.board_uv)} className="pending-ring" />
                      {!compact && <text y={-pieceRadius(o.board_uv) - 14} className="pending-text">{o.label ?? "CHECKING PLACEMENT"}</text>}
                    </g>
                  );
                })}
              </g>
              <g className="layer-cues" pointerEvents="none">
                {live.map((set) => <g key={set.key}>{set.cues.map((c) => <CueMark key={c.id} c={c} frame={frame} roads={roads} radius={c.uv ? pieceRadius(c.uv) : 48} />)}</g>)}
                {/* PLACEMENT ACCEPTED / MOVE CONFIRMED beside the piece the backend just accepted. */}
                {!compact && live.map((set) => set.pieceLabel && (
                  <Label key={`pl-${set.key}`} x={P(set.pieceLabel.uv).x} y={P(set.pieceLabel.uv).y + pieceRadius(set.pieceLabel.uv) + 64} text={set.pieceLabel.text} className={`piece-cue tone-${set.pieceLabel.tone}`} size={24} />
                ))}
                {rejections.map((r) => {
                  const c = P(r.uv);
                  const radius = pieceRadius(r.uv);
                  return (
                    <g key={r.id} transform={`translate(${c.x} ${c.y})`} className="reject">
                      <circle r={radius} className="reject-ring" />
                      <Label y={-radius - 18} text={r.text} className="reject-text" size={compact ? 18 : 26} />
                    </g>
                  );
                })}
              </g>
            </>
          )}

          {idle && !compact && !hold && <IdleScreen frame={frame} />}
          {!idle && !compact && !showResults && <Hud guide={guide} clock={clock} boat={boat} />}
          {/* Big dramatic stage overlay text */}
          {!idle && !compact && !showResults && model && (
            <StageOverlay
              frame={frame}
              phase={guide.phase}
              remainingMs={clock.remainingMs}
              hasBridge={model.bridges.length > 0}
              hasFacility={model.facilities.length > 0}
            />
          )}
          {/* Game over overlay when majority cut off */}
          {!idle && !compact && !showResults && model && (
            <GameOverOverlay frame={frame} model={model} />
          )}
          {!idle && !compact && !showResults && (latest?.headline || props.notices?.length) && (
            <Toast frame={frame} key={latest?.key ?? props.notices?.[0]} text={latest?.headline?.text ?? props.notices![0]} tone={latest?.headline?.tone ?? "bad"} />
          )}
          {showResults && <ImpactReveal frame={frame} scenario={scenario} snapshot={snapshot} results={results!} syncing={props.resultsSyncing} narrative={narrative} />}
          {props.connectionLost && !hold && !compact && <Label x={frame.W / 2} y={SAFE.toastY - 70} text="CONNECTION LOST · SHOWING LAST CONFIRMED STATE" className="hold-note" size={24} />}
        </>
      )}

      {hold && (
        <g className="layer-hold">
          <rect width={frame.W} height={frame.H} fill={PALETTE.paper} opacity={surface === "overlay" ? 1 : 0.92} />
          <g transform={`translate(${frame.W / 2} ${frame.H / 2 - 170})`} color={PALETTE.water}><MatsyaMark size={90} /></g>
          <text x={frame.W / 2} y={frame.H / 2 - 60} className="hold-brand">{TITLE}</text>
          <text x={frame.W / 2} y={frame.H / 2} className="hold-heading">{SUBTITLE}</text>
          <text x={frame.W / 2} y={frame.H / 2 + 70} className="hold-text">{hold}</text>
          <text x={frame.W / 2} y={frame.H / 2 + 112} className="hold-hint">Press M for the screen experience · A to align the projector</text>
        </g>
      )}

      {testPattern && <TestPattern frame={frame} />}

      {/* Keep-outs, last: no projected light on camera-measured pieces or ArUco markers. */}
      {surface === "overlay" && (
        <g className="layer-piece-keepouts" pointerEvents="none">
          {footprints.map((p, i) => <polygon key={i} points={p.map((q) => { const s = frame.printPt(q); return `${s.x.toFixed(1)},${s.y.toFixed(1)}`; }).join(" ")} fill="#000" />)}
        </g>
      )}
      {(surface === "overlay" || compact) && (
        <g className="layer-markers" pointerEvents="none">
          {(props.registration?.markers?.map((m) => ({ id: m.id, center: m.center_uv })) ?? BOARD_MARKERS).map((m) => {
            const c = frame.printPt(m.center);
            const board = props.registration?.board;
            // Use per-marker size if available, else global marker_size_mm, else fallback
            const markerSizes = props.registration?.marker_sizes_mm as Record<string, number> | undefined;
            const size = markerSizes?.[String(m.id)] ?? props.registration?.marker_size_mm;
            // Calculate keepout size: half marker + 6mm margin, converted to print space
            const h = board && size ? ((size / 2 + 6) / board.width_mm) * frame.W : MARKER_KEEPOUT_HALF_UV * frame.W;
            const v = board && size ? ((size / 2 + 6) / board.height_mm) * frame.H : MARKER_KEEPOUT_HALF_UV * frame.H;
            return surface === "overlay" ? (
              <rect key={m.id} x={c.x - h} y={c.y - v} width={h * 2} height={v * 2} fill="#000" />
            ) : (
              <g key={m.id}>
                <rect x={c.x - h} y={c.y - v} width={h * 2} height={v * 2} className="marker-box" />
                <text x={c.x} y={c.y + 6} className="marker-id">{m.id}</text>
              </g>
            );
          })}
        </g>
      )}

      {/* Operator click-to-pad fallback: the same live action the camera would cause. */}
      {onSiteClick && (
        <g className="layer-hit">
          {scenario.sites.filter((s) => s.kind !== "control_start_pad" && s.kind !== "population_node").map((s) => {
            const c = P(s.board_uv);
            return (
              <circle key={s.id} cx={c.x} cy={c.y} r={40} role="button" tabIndex={0} aria-label={`${s.label} (${s.id})`} className={`site-hit ${highlightSite === s.id ? "selected" : ""}`} onClick={() => onSiteClick(s.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSiteClick(s.id); } }}>
                <title>{`${s.label} (${s.id})`}</title>
              </circle>
            );
          })}
        </g>
      )}
    </svg>
  );
}

/** Text with a white halo so it reads over the printed map and over projected colour. */
function Label({ x = 0, y = 0, text, className, size, anchor = "middle" }: { x?: number; y?: number; text: string; className: string; size: number; anchor?: "start" | "middle" | "end" }) {
  return <text x={x} y={y} className={className} fontSize={size} textAnchor={anchor} filter="url(#text-halo)">{text}</text>;
}

function VectorBasemap({ scenario, frame }: { scenario: ScenarioGeometry; frame: Frame }) {
  return (
    <g className="layer-basemap layer-vector-basemap" pointerEvents="none">
      {scenario.rivers.map((r, i) => <path key={i} d={frame.d(r)} className="base-river" />)}
      {scenario.roads.map((r) => <path key={r.id} d={frame.d(r.path)} className={`base-road base-${r.kind}`} />)}
    </g>
  );
}

function Routes({ frame, model, snapshot, roads }: { frame: Frame; model: BoardModel; snapshot: WorldSnapshot; roads: Map<string, { path: UV[] }> }) {
  const mission = snapshot.mission;
  const lifelines = (mission?.lifelines ?? []).filter((l) => l.board_uv.length >= 2);
  return (
    <g className="layer-routes" pointerEvents="none">
      {/* Closed roads and crossings: red dashes plus an X where a crossing is out. */}
      {model.blocked.map((e) => <path key={`blk-${e.id}`} d={frame.d(e.path)} className="road-blocked" />)}
      {model.blocked.filter((e) => roads.get(e.id) && e.path.length >= 2).map((e) => {
        const mid = frame.pt(e.path[Math.floor(e.path.length / 2)]);
        return <path key={`x-${e.id}`} d={`M${mid.x - 9} ${mid.y - 9} L${mid.x + 9} ${mid.y + 9} M${mid.x + 9} ${mid.y - 9} L${mid.x - 9} ${mid.y + 9}`} className="blocked-x" />;
      })}
      {/* The village's lifeline to supplies: pulsing red while cut, green once open. */}
      {lifelines.map((l) => <path key={`life-${l.population_id}`} d={frame.d(l.board_uv)} className={l.reachable ? "lifeline-open" : "lifeline-cut"} />)}
      {model.cut.map((e) => <path key={`cut-${e.id}`} d={frame.d(e.path)} className="route-cut" />)}
      {model.open.map((e) => <path key={`ok-${e.id}`} d={frame.d(e.path)} className="route-open" />)}
      {/* Directional flow along every open route, in the direction people travel (village → help). */}
      {(snapshot.service_routes ?? []).filter((r) => r.reachable && (r.board_uv?.length ?? 0) > 1).map((r) => <path key={`flow-${r.population_id}-${r.service}`} d={frame.d(r.board_uv!)} className="route-flow" />)}
      {lifelines.filter((l) => l.reachable).map((l) => <path key={`lflow-${l.population_id}`} d={frame.d(l.board_uv)} className="route-flow" />)}
    </g>
  );
}

/** Population dots wandering randomly when they have nowhere to go */
function WanderingPeople({ frame, model }: { frame: Frame; model: BoardModel }) {
  // Show wandering people at populations that are cut off or have unmet needs
  const cutOffPops = model.populations.filter((p) => p.depotReachable === false || p.status === "danger");
  const peoplePerPop = 8; // Number of wandering dots per population

  // Generate random wander paths for each person
  const wanderPath = (cx: number, cy: number, radius: number, seed: number) => {
    const points: string[] = [];
    const steps = 6;
    for (let i = 0; i <= steps; i++) {
      const angle = (seed + i * 60) * (Math.PI / 180);
      const r = radius * (0.3 + 0.7 * Math.sin(seed + i * 1.5));
      const x = cx + r * Math.cos(angle + seed * 0.1);
      const y = cy + r * Math.sin(angle + seed * 0.1);
      points.push(i === 0 ? `M${x} ${y}` : `L${x} ${y}`);
    }
    points.push("Z");
    return points.join(" ");
  };

  return (
    <g className="layer-wandering" pointerEvents="none">
      {cutOffPops.map((p) => {
        const c = frame.pt(p.uv);
        return (
          <g key={`wander-${p.siteId}`}>
            {Array.from({ length: peoplePerPop }, (_, i) => {
              const seed = (p.siteId.charCodeAt(0) * 7 + i * 37) % 360;
              const radius = 50 + (i % 3) * 25;
              const d = wanderPath(c.x, c.y, radius, seed);
              const dur = 2.5 + (i % 4) * 0.5;
              return (
                <circle key={i} r={16} className="wanderer" style={{ animationDelay: `${i * 0.3}s` }}>
                  <animateMotion dur={`${dur}s`} repeatCount="indefinite" path={d} />
                </circle>
              );
            })}
          </g>
        );
      })}
    </g>
  );
}

/** Large population markers walking along every route that is open, toward help. */
function Travellers({ frame, snapshot }: { frame: Frame; snapshot: WorldSnapshot }) {
  const routes = (snapshot.service_routes ?? []).filter((r) => r.reachable && (r.board_uv?.length ?? 0) >= 2).map((r) => ({ key: `${r.population_id}-${r.service}`, path: r.board_uv! }));
  const lifelines = (snapshot.mission?.lifelines ?? []).filter((l) => l.reachable && l.board_uv.length >= 2 && !routes.some((r) => r.key.startsWith(l.population_id))).map((l) => ({ key: `life-${l.population_id}`, path: l.board_uv }));
  return (
    <g className="layer-travellers" pointerEvents="none">
      {[...routes, ...lifelines].map(({ key, path }) => {
        const d = frame.d(path);
        const seconds = Math.max(2.5, Math.min(7, polylineLength(frame, path) / 140));
        return (
          <g key={key}>
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <circle key={i} r={18} className="traveller-large">
                <animateMotion dur={`${seconds}s`} begin={`${(i * seconds) / 7}s`} repeatCount="indefinite" path={d} />
              </circle>
            ))}
          </g>
        );
      })}
    </g>
  );
}

function Populations({ frame, model, names, compact }: { frame: Frame; model: BoardModel; names: Map<string, string>; compact: boolean }) {
  return (
    <g className="layer-population" pointerEvents="none">
      {model.populations.map((p) => <Population key={p.siteId} p={p} frame={frame} name={names.get(p.siteId)} compact={compact} />)}
    </g>
  );
}

const SERVICE_WORD: Record<ServiceKind, string> = { refuge: "SHELTER", medical: "MEDICAL", food: "FOOD" };

function Population({ p, frame, name, compact }: { p: PopulationMark; frame: Frame; name?: string; compact: boolean }) {
  const c = frame.pt(p.uv);
  const cutOff = p.depotReachable === false;
  const lost = (Object.entries(p.services) as [ServiceKind, boolean][]).filter(([, ok]) => !ok).map(([k]) => SERVICE_WORD[k]);
  const color = cutOff || p.status === "danger" ? PALETTE.danger : p.status === "access" ? PALETTE.route : PALETTE.inkSoft;
  const tag = cutOff ? "CUT OFF" : lost.length ? `NO ${lost.join(" / ")} ACCESS` : null;
  return (
    <g transform={`translate(${c.x} ${c.y})`} className={`population population-${p.status}`}>
      {cutOff ? <circle r={62} className="pop-danger-glow" /> : p.status === "danger" ? <circle r={50} className="pop-warn-glow" /> : p.status === "access" && <circle r={50} className="pop-access-glow" />}
      <g transform="scale(2)"><PopulationCluster color={color} /></g>
      {!compact && (
        <>
          <Label y={50} text={`${name ?? "Village"}${p.peopleModel != null ? ` · ${p.peopleModel} residents` : ""}`} className={`pop-name tone-${cutOff ? "danger" : p.status}`} size={22} />
          {tag && <Label y={76} text={tag} className="pop-tag" size={19} />}
          <NeedBadges p={p} y={tag ? 110 : 84} />
        </>
      )}
    </g>
  );
}

/** Unmet needs at a village: one glyph per need with its remaining count. */
function NeedBadges({ p, y }: { p: PopulationMark; y: number }) {
  const shown = NEED_ICON.filter(({ need }) => (p.unmetBy?.[need] ?? 0) > 0);
  if (!shown.length) return null;
  const w = 58;
  return (
    <g transform={`translate(${(-(shown.length - 1) * w) / 2} ${y})`}>
      {shown.map(({ need, piece }, i) => (
        <g key={need} transform={`translate(${i * w} 0)`}>
          <rect x={-26} y={-17} width={52} height={34} rx={17} className="need-badge" />
          <g transform="translate(-10 0)"><PieceGlyph type={piece} size={15} /></g>
          <text x={13} y={7} className="need-count">{p.unmetBy![need]}</text>
        </g>
      ))}
    </g>
  );
}

function FocusTargets({ frame, focus, compact, pulse }: { frame: Frame; focus: Focus[]; compact: boolean; pulse: boolean }) {
  return (
    <g className="layer-focus" pointerEvents="none">
      {focus.map((f) => {
        const c = frame.pt(f.option.board_uv);
        const color = f.tone === "danger" ? PALETTE.danger : f.tone === "good" ? PALETTE.route : PIECE_COLOR[f.option.piece] ?? PALETTE.highlight;
        return (
          <g key={`${f.kind}-${f.option.site_id}`} transform={`translate(${c.x} ${c.y})`} className={`focus focus-${f.kind} ${pulse ? "focus-alert" : ""}`} style={{ color }}>
            <circle r={58} className="focus-glow" />
            <circle r={44} className="focus-ring" />
            <Brackets r={64} />
            {f.option.piece === "bridge" && <BridgeGhost option={f.option} frame={frame} />}
            {f.option.piece !== "bridge" && <PieceGlyph type={f.option.piece} size={30} color={color} />}
            {/* Crossing labels sit above (the village label is below); site labels sit below. */}
            {!compact && <Label y={f.kind === "crossing" ? -82 : 98} text={f.label} className="focus-label" size={26} />}
            {!compact && f.detail && <Label y={f.kind === "crossing" ? 96 : 126} text={f.detail} className="focus-detail" size={21} />}
          </g>
        );
      })}
    </g>
  );
}

function printAngle(frame: Frame, uv: UV, deg: number): number {
  const r = (deg * Math.PI) / 180;
  const a = frame.pt(uv);
  const b = frame.pt([uv[0] + 0.01 * Math.cos(r), uv[1] + 0.01 * Math.sin(r)]);
  return (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI;
}

function BridgeGhost({ option, frame }: { option: MissionOption; frame: Frame }) {
  const angle = printAngle(frame, option.board_uv, option.rotation_deg ?? 0);
  return (
    <g transform={`rotate(${angle})`} className="bridge-ghost">
      <rect x={-46} y={-15} width={92} height={30} rx={6} />
      <path d="M-34 -15 V15 M-11 -15 V15 M11 -15 V15 M34 -15 V15" />
    </g>
  );
}

function Pieces({ frame, model, radius, compact }: { frame: Frame; model: BoardModel; radius: (uv: UV) => number; compact: boolean }) {
  return (
    <g className="layer-pieces" pointerEvents="none">
      {model.bridges.map((b) => {
        const c = frame.pt(b.uv);
        const r = radius(b.uv);
        const angle = printAngle(frame, b.uv, b.rotation);
        const color = b.connected ? PALETTE.route : PALETTE.inkSoft;
        return (
          <g key={b.tokenId} transform={`translate(${c.x} ${c.y})`} className={`piece piece-bridge ${b.connected ? "on" : "off"}`}>
            {/* Dramatic green glow when bridge is connected - VERY BIG */}
            {b.connected && (
              <>
                <circle r={r + 100} className="piece-glow-outer" style={{ fill: PALETTE.route }} />
                <circle r={r + 70} className="piece-glow-inner" style={{ fill: PALETTE.route }} />
              </>
            )}
            <g transform={`rotate(${angle})`}>
              <rect x={-r - 14} y={-r * 0.55 - 14} width={(r + 14) * 2} height={(r * 0.55 + 14) * 2} rx={22} fill={color} opacity={0.22} filter="url(#soft-light)" />
              <rect x={-r - 6} y={-r * 0.55 - 6} width={(r + 6) * 2} height={(r * 0.55 + 6) * 2} rx={18} className={`bridge-outline ${b.connected ? "glow-green" : ""}`} style={{ stroke: color }} />
            </g>
            {!compact && <Label y={-r - 30} text={b.connected ? "BRIDGE CONNECTED" : "BRIDGE PLACED"} className={`piece-label tone-${b.connected ? "good" : "info"}`} size={22} />}
          </g>
        );
      })}
      {model.facilities.map((f) => {
        const c = frame.pt(f.uv);
        const r = radius(f.uv);
        const on = f.active && f.serving;
        const color = on ? PIECE_COLOR[f.type] ?? PALETTE.ink : PALETTE.danger;
        return (
          <g key={f.tokenId} transform={`translate(${c.x} ${c.y})`} className={`piece piece-facility ${on ? "on" : "off"}`}>
            {/* Dramatic glow when facility is active - green for working, red for not - VERY BIG */}
            {on ? (
              <>
                <circle r={r + 90} className="piece-glow-outer" style={{ fill: PALETTE.route }} />
                <circle r={r + 60} className="piece-glow-inner" style={{ fill: PALETTE.route }} />
              </>
            ) : (
              <>
                <circle r={r + 80} className="piece-glow-danger" style={{ fill: PALETTE.danger }} />
              </>
            )}
            <circle r={r + 16} fill={color} opacity={0.25} filter="url(#soft-light)" />
            <circle r={r + 4} className={`piece-ring ${on ? "on glow-green" : "off glow-red"}`} style={{ stroke: color }} />
            <g transform={`translate(${r + 26} ${-r})`}><PieceGlyph type={f.type} size={26} color={color} /></g>
            {!compact && <Label y={r + 34} text={!f.supplied || !f.serving ? `${PIECE_NAME[f.type]} · NO ONE CAN REACH IT` : f.full ? `${PIECE_NAME[f.type]} · FULL ${f.used}/${f.capacity}` : `${PIECE_NAME[f.type]} · ${f.used}/${f.capacity}`} className={`cap-label tone-${on ? "good" : "danger"}`} size={21} />}
          </g>
        );
      })}
    </g>
  );
}

function Brackets({ r }: { r: number }) {
  const k = r * 0.38;
  return <path className="focus-brackets" d={`M${-r} ${-r + k} V${-r} H${-r + k} M${r - k} ${-r} H${r} V${-r + k} M${r} ${r - k} V${r} H${r - k} M${-r + k} ${r} H${-r} V${r - k}`} />;
}

function CueMark({ c, frame, roads, radius }: { c: Cue; frame: Frame; roads: Map<string, { path: UV[] }>; radius: number }) {
  const at = c.uv ? frame.pt(c.uv) : null;
  switch (c.kind) {
    case "halo":
      return at ? <g transform={`translate(${at.x} ${at.y})`}><circle r={radius} className="cue-halo" /></g> : null;
    case "removed":
      return at ? <circle cx={at.x} cy={at.y} r={radius} className="cue-off" /> : null;
    case "edge_restored":
    case "edge_blocked":
      return <g className={`cue-${c.kind}`}>{(c.edgeIds ?? []).map((id) => { const r = roads.get(id); return r ? <path key={id} d={frame.d(r.path)} className="cue-edge" /> : null; })}</g>;
    case "route_opened": {
      if (!c.path || c.path.length < 2) return null;
      return <path d={frame.d(c.path)} className="cue-route-draw" style={{ ["--len" as string]: polylineLength(frame, c.path).toFixed(1) }} />;
    }
    case "route_lost":
      return c.path && c.path.length >= 2 ? <path d={frame.d(c.path)} className="cue-route-lost" /> : null;
    case "population_danger":
      return at ? <circle cx={at.x} cy={at.y} r={70} className="cue-pop-danger" /> : null;
    case "population_access":
      return at ? <circle cx={at.x} cy={at.y} r={60} className="cue-pop-access" /> : null;
    default:
      return null;
  }
}

function Hud({ guide, clock, boat }: { guide: Guide; clock: ClockView; boat: ReturnType<typeof boatOfHope> }) {
  const top = SAFE.top;
  const bottom = SAFE.bottom;
  const seconds = Math.max(0, Math.ceil(clock.remainingMs / 1000));
  const current = CHAPTERS.indexOf(guide.phase);
  const chip = (bottom.w - 170) / CHAPTERS.length;
  const accent = guide.tone === "danger" ? PALETTE.danger : guide.tone === "good" ? PALETTE.route : PALETTE.highlight;
  return (
    <g className="hud" pointerEvents="none">
      <rect x={top.x} y={top.y} width={top.w} height={top.h} rx={18} className="hud-panel" />
      <rect x={top.x} y={top.y} width={12} height={top.h} rx={6} fill={accent} />
      <text x={top.x + 40} y={top.y + 36} className="hud-chapter">{`CHAPTER ${guide.chapter} · ${guide.chapterName}`}</text>
      <text key={guide.title} x={top.x + 40} y={top.y + 84} className="hud-title" style={{ fill: accent, fontSize: fit(guide.title, top.w - 140, 46, 0.66) }}>{guide.title}</text>
      <text x={top.x + 40} y={top.y + 122} className="hud-story" style={{ fontSize: fit(guide.story, top.w - 140, 27, 0.5) }}>{guide.story}</text>
      {boat ? (
        <g transform={`translate(${top.x + top.w - 66} ${top.y + 82})`}><BoatOfHopeMark boat={boat} scale={0.95} /></g>
      ) : (
        <g transform={`translate(${top.x + top.w - 40} ${top.y + 70})`} color={PALETTE.water} opacity={0.8}><MatsyaMark size={46} /></g>
      )}

      <rect x={bottom.x} y={bottom.y} width={bottom.w} height={bottom.h} rx={18} className="hud-panel" />
      <rect x={bottom.x + 18} y={bottom.y + 12} width={bottom.w - 36} height={56} rx={28} fill={accent} className="hud-step-pill" />
      <text key={guide.step} x={bottom.x + bottom.w / 2} y={bottom.y + 50} className="hud-step" style={{ fontSize: fit(guide.step, bottom.w - 90, 29, 0.74) }}>{guide.step}</text>
      {CHAPTERS.map((p, i) => {
        const x = bottom.x + 24 + i * chip;
        const state = i < current ? "done" : i === current ? "now" : "next";
        return (
          <g key={p} transform={`translate(${x} ${bottom.y + 82})`} className={`chip chip-${state}`}>
            <rect width={chip - 10} height={28} rx={14} />
            <text x={(chip - 10) / 2} y={20}>{`${state === "done" ? "✓ " : ""}${BEATS[p].chapter} ${BEATS[p].name}`}</text>
          </g>
        );
      })}
      <text x={bottom.x + bottom.w - 30} y={bottom.y + 104} className="hud-timer">{`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</text>
      <rect x={bottom.x + 24} y={bottom.y + bottom.h - 6} width={(bottom.w - 48) * Math.min(1, clock.elapsedMs / MISSION_MS)} height={3} fill={accent} opacity={0.6} />
    </g>
  );
}

/** Font size that keeps `text` within `width` (em-width estimate per character). */
function fit(text: string, width: number, max: number, em: number): number {
  return Math.max(14, Math.min(max, width / Math.max(1, text.length * em)));
}

function Toast({ frame, text, tone }: { frame: Frame; text: string; tone: "good" | "bad" | "info" }) {
  const size = fit(text, frame.W * 0.66 - 80, 32, 0.78);
  const w = Math.min(frame.W * 0.66, 80 + text.length * size * 0.78);
  return (
    <g className={`toast toast-${tone}`} pointerEvents="none">
      <rect x={(frame.W - w) / 2} y={SAFE.toastY - 40} width={w} height={72} rx={36} />
      <text x={frame.W / 2} y={SAFE.toastY + 8} style={{ fontSize: size }}>{text}</text>
    </g>
  );
}

function IdleScreen({ frame }: { frame: Frame }) {
  const x = frame.W / 2;
  return (
    <g className="idle" pointerEvents="none">
      <rect x={frame.W * 0.16} y={frame.H * 0.15} width={frame.W * 0.68} height={frame.H * 0.7} rx={28} className="hud-panel" />
      <g transform={`translate(${x} ${frame.H * 0.24})`} color={PALETTE.water}><MatsyaMark size={92} /></g>
      <text x={x} y={frame.H * 0.33} className="idle-brand">{TITLE}</text>
      <text x={x} y={frame.H * 0.38} className="idle-heading">{SUBTITLE}</text>
      {MANU_STORY.map((l, i) => <text key={l} x={x} y={frame.H * 0.45 + i * 36} className="idle-story">{l}</text>)}
      {MANU_TODAY.split(": ").map((l, i, all) => <text key={l} x={x} y={frame.H * 0.55 + i * 32} className="idle-today">{i < all.length - 1 ? `${l}:` : l}</text>)}
      <text x={x} y={frame.H * 0.63} className="idle-howto-title">HOW TO PLAY</text>
      {HOW_TO_PLAY.map((l, i) => <text key={l} x={x} y={frame.H * 0.67 + i * 34} className="idle-howto">{`${i + 1}. ${l}`}</text>)}
      <text x={x} y={frame.H * 0.82} className="idle-start">PRESS START ON THE LAPTOP</text>
    </g>
  );
}

function AlignGuide({ frame }: { frame: Frame }) {
  return (
    <g className="layer-align" pointerEvents="none">
      <rect x={2} y={2} width={frame.W - 4} height={frame.H - 4} className="align-border" />
      {[0.25, 0.5, 0.75].map((u) => <path key={`v${u}`} d={`M${u * frame.W} 0 V${frame.H}`} className="align-grid" />)}
      {[0.25, 0.5, 0.75].map((v) => <path key={`h${v}`} d={`M0 ${v * frame.H} H${frame.W}`} className="align-grid" />)}
      <rect x={frame.W * 0.2} y={frame.H * 0.42} width={frame.W * 0.6} height={110} rx={20} className="hud-panel" />
      <text x={frame.W / 2} y={frame.H * 0.42 + 46} className="align-title">ALIGN THE PROJECTOR TO THE PRINT</text>
      <text x={frame.W / 2} y={frame.H * 0.42 + 84} className="align-text">C → 1–4 pick a corner · arrows move it until projected rivers and roads sit on the printed ones · Enter save · A exit</text>
    </g>
  );
}

function TestPattern({ frame }: { frame: Frame }) {
  const pts: UV[] = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8], [0.5, 0.5]];
  return (
    <g className="layer-test" pointerEvents="none">
      <rect x={2} y={2} width={frame.W - 4} height={frame.H - 4} className="test-border" />
      {pts.map(([u, v], i) => {
        const c = frame.printPt([u, v]);
        return (
          <g key={i}>
            <path d={`M${c.x - 34} ${c.y} H${c.x + 34} M${c.x} ${c.y - 34} V${c.y + 34}`} className="test-cross" />
            <circle cx={c.x} cy={c.y} r={16} className="test-cross" fill="none" />
          </g>
        );
      })}
    </g>
  );
}

/** Game over overlay when majority of populations are cut off */
function GameOverOverlay({ frame, model }: { frame: Frame; model: BoardModel }) {
  // Count populations in danger vs total
  const total = model.populations.length;
  const cutOff = model.populations.filter((p) => p.depotReachable === false).length;
  const inDanger = model.populations.filter((p) => p.status === "danger").length;
  const affected = Math.max(cutOff, inDanger);
  const percentAffected = total > 0 ? (affected / total) * 100 : 0;

  // Only show game over when majority (>50%) are affected
  if (percentAffected <= 50) return null;

  const cx = frame.W / 2;
  const cy = frame.H / 2;

  return (
    <g className="layer-game-over" pointerEvents="none">
      {/* Red overlay */}
      <rect width={frame.W} height={frame.H} className="game-over-bg" />
      {/* Big game over text */}
      <text x={cx} y={cy - 40} className="game-over-text">FLOOD CRISIS</text>
      <text x={cx} y={cy + 30} className="game-over-subtext">
        {`${affected} of ${total} communities cut off`}
      </text>
      <text x={cx} y={cy + 80} className="game-over-hint">
        Place pieces to restore access!
      </text>
    </g>
  );
}

/** Big dramatic stage overlay text showing current objective + timer */
function StageOverlay({ frame, phase, remainingMs, hasBridge, hasFacility }: {
  frame: Frame;
  phase: GamePhase;
  remainingMs: number;
  hasBridge: boolean;
  hasFacility: boolean;
}) {
  const seconds = Math.max(0, Math.ceil(remainingMs / 1000));
  const timeStr = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  // Determine what big text to show based on phase and state
  let stageText: string | null = null;
  let stageColor = PALETTE.highlight;

  if (phase === "WARNING") {
    stageText = "FLOOD WARNING!";
    stageColor = PALETTE.danger;
  } else if (phase === "CROSSING" && !hasBridge) {
    stageText = "PLACE THE BRIDGE!";
    stageColor = PALETTE.highlight;
  } else if (phase === "RELIEF" && !hasFacility) {
    stageText = "CHOOSE: HOSPITAL OR FOOD";
    stageColor = PALETTE.route;
  } else if (phase === "SURGE") {
    stageText = "BRACE FOR SURGE!";
    stageColor = PALETTE.danger;
  }

  // Don't show during IDLE, INTRO, RESULTS, or when objectives are met
  if (!stageText) return null;

  const cx = frame.W / 2;
  const cy = frame.H * 0.35;

  return (
    <g className="layer-stage-overlay" pointerEvents="none">
      {/* Big centered stage text */}
      <text
        x={cx}
        y={cy}
        className="stage-text"
        style={{ fill: stageColor }}
      >
        {stageText}
      </text>

      {/* Large timer in top-right corner */}
      <g className="stage-timer" transform={`translate(${frame.W - 120} 80)`}>
        <rect x={-70} y={-45} width={140} height={70} rx={12} className="stage-timer-bg" />
        <text x={0} y={12} className="stage-timer-text">{timeStr}</text>
      </g>
    </g>
  );
}
