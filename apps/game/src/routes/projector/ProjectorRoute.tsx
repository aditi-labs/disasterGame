import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLiveWorld } from "../../live/useLiveWorld";
import { openChannel, type ChannelMessage, type RejectionCue } from "../../game/channel";
import { CLOCK_STALE_MS, extrapolateClock, FREEZE_AT_MS, IDLE_VIEW, type ClockView } from "../../game/clock";
import { calibrationMatrix3d, DEFAULT_CALIBRATION, type Calibration } from "../../game/homography";
import { ProjectionScene } from "../../game/overlays/ProjectionScene";
import { buildGuide } from "../../game/guide";
import { PRINT_H, PRINT_W } from "../../game/printFrame";
import { buildResults } from "../../game/results";
import { BEATS, LIVE_DATA_UNAVAILABLE, MISSION1_REVEAL_MS, placementHint } from "../../game/story";
import { buildBoardModel } from "../../game/worldAdapter";
import { BOARD_REGISTRATION_REQUIRED } from "../../game/board";
import type { TokenType, WorldSnapshot } from "../../types/contracts";

// /projector — fullscreen projection over the printed board. No diagnostics, no code
// labels, no sound. Keys:
//   F fullscreen · M overlay <-> screen (artwork basemap) · A align mode (projects the
//   printed artwork itself so keystone can be matched to the paper) · C projector
//   calibration · T registration test pattern. In calibration: arrows move, [ ] rotate,
//   - = scale, , . x-scale, ; ' y-scale, 1–4 pick a keystone corner (arrows then move
//   that corner, 5 back to whole-image), shift ×10, 0 reset, Enter save.

type Surface = "overlay" | "screen" | "align";
const PIECE_OF_CLASS: Record<string, TokenType> = { bridge: "bridge", hospital: "hospital", shelter: "shelter", food_station: "food_shelter" };

const CAL_KEY = "floodshift.game.projector.calibration.v2";

function loadCal(): Calibration {
  try {
    const raw = localStorage.getItem(CAL_KEY);
    return raw ? { ...DEFAULT_CALIBRATION, ...JSON.parse(raw) } : DEFAULT_CALIBRATION;
  } catch {
    return DEFAULT_CALIBRATION;
  }
}

function saveCal(c: Calibration) {
  try {
    localStorage.setItem(CAL_KEY, JSON.stringify(c));
  } catch {
    /* private window: calibration lasts for this session only */
  }
}

export function ProjectorRoute() {
  const world = useLiveWorld();
  const params = new URLSearchParams(window.location.search);
  const [surface, setSurface] = useState<Surface>(params.get("mode") === "screen" ? "screen" : params.get("mode") === "align" ? "align" : "overlay");
  const overlay = surface === "overlay";
  const [calibrating, setCalibrating] = useState(false);
  const [testing, setTesting] = useState(false);
  // Mythic narrative layer (Matsya's Guidance, Boat of Hope): N toggles, ?narrative=0 hides.
  const [narrative, setNarrative] = useState(params.get("narrative") !== "0");
  const [corner, setCorner] = useState<number | null>(null);
  const [cal, setCal] = useState<Calibration>(loadCal);
  const [clock, setClock] = useState<{ view: ClockView; sentAt: number }>({ view: IDLE_VIEW, sentAt: performance.now() });
  const [syncing, setSyncing] = useState(false);
  const [finalSnapshot, setFinalSnapshot] = useState<WorldSnapshot | null>(null);
  const [rejections, setRejections] = useState<RejectionCue[]>([]);
  const [, setTick] = useState(0);
  const stageRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  const channel = useRef<ReturnType<typeof openChannel> | null>(null);
  const clearPending = world.clearPending;
  const alignmentReady = world.registration?.ready === true;
  // The projector needs only the measured print<->world mapping; camera actions need markers too.
  const mappingReady = !!world.registration?.world_to_print && (world.registration.mapping_ready === true || alignmentReady);

  useEffect(() => saveCal(cal), [cal]);

  useEffect(() => {
    const onMessage = (m: ChannelMessage) => {
      switch (m.t) {
        case "clock":
          setClock({ view: m.view, sentAt: performance.now() });
          setSyncing(m.syncing);
          setFinalSnapshot(m.finalSnapshot ?? null);
          break;
        case "reject":
          setRejections((list) => [...list.filter((r) => r.until > Date.now()), m.cue]);
          window.setTimeout(() => setRejections((list) => list.filter((r) => r.id !== m.cue.id)), Math.max(0, m.cue.until - Date.now()));
          break;
        case "command":
          if (m.cmd === "calibrate") setCalibrating(true);
          else if (m.cmd === "test") setTesting((v) => !v);
          else if (m.cmd === "overlay") setSurface("overlay");
          else if (m.cmd === "screen") setSurface("screen");
          else if (m.cmd === "narrative") setNarrative((v) => !v);
          else if (m.cmd === "align") setSurface((v) => (v === "align" ? "overlay" : "align"));
          else if (m.cmd === "exit-tools") {
            setCalibrating(false);
            setTesting(false);
          }
          break;
        case "clear-pending":
          clearPending(m.tokenIds.length ? m.tokenIds : undefined);
          break;
        default:
          break;
      }
    };
    channel.current = openChannel(onMessage);
    return () => channel.current?.close();
  }, [clearPending]);

  // Projector health for the operator status line.
  useEffect(() => {
    const send = () =>
      channel.current?.post({ t: "projector-health", overlay, calibrating, testing, calibratedAt: mappingReady ? cal.savedAt : null, alignmentVerified: mappingReady, sentAt: Date.now() });
    send();
    const id = window.setInterval(send, 1000);
    return () => window.clearInterval(id);
  }, [overlay, calibrating, testing, cal.savedAt, mappingReady]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 250);
    return () => window.clearInterval(id);
  }, []);

  useLayoutEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (k === "f") {
        if (document.fullscreenElement) void document.exitFullscreen();
        else document.documentElement.requestFullscreen().catch(() => {});
        return;
      }
      if (k === "m") return setSurface((v) => (v === "overlay" ? "screen" : "overlay"));
      if (k === "a") return setSurface((v) => (v === "align" ? "overlay" : "align"));
      if (k === "c") {
        setCorner(null);
        return setCalibrating((v) => !v);
      }
      if (k === "t") return setTesting((v) => !v);
      if (k === "n") return setNarrative((v) => !v);
      if (!calibrating) return;
      const step = e.shiftKey ? 10 : 1;
      if (["1", "2", "3", "4"].includes(e.key)) return setCorner(Number(e.key) - 1);
      if (e.key === "5") return setCorner(null);
      if (e.key === "Enter") return setCal((c) => ({ ...c, savedAt: new Date().toISOString() }));
      if (e.key === "0") return setCal(DEFAULT_CALIBRATION);
      if (corner != null && e.key.startsWith("Arrow")) {
        e.preventDefault();
        const [dx, dy] = e.key === "ArrowLeft" ? [-step, 0] : e.key === "ArrowRight" ? [step, 0] : e.key === "ArrowUp" ? [0, -step] : [0, step];
        return setCal((c) => {
          const corners = c.corners.map((p, i) => (i === corner ? [p[0] + dx, p[1] + dy] : p)) as Calibration["corners"];
          return { ...c, corners, savedAt: null };
        });
      }
      setCal((c) => {
        const n = (patch: Partial<Calibration>): Calibration => ({ ...c, ...patch, savedAt: null });
        switch (e.key) {
          case "ArrowLeft": return n({ dx: c.dx - step });
          case "ArrowRight": return n({ dx: c.dx + step });
          case "ArrowUp": return n({ dy: c.dy - step });
          case "ArrowDown": return n({ dy: c.dy + step });
          case "[": return n({ rot: +(c.rot - 0.1 * step).toFixed(2) });
          case "]": return n({ rot: +(c.rot + 0.1 * step).toFixed(2) });
          case "-": return n({ sx: +(c.sx - 0.002 * step).toFixed(4), sy: +(c.sy - 0.002 * step).toFixed(4) });
          case "=": return n({ sx: +(c.sx + 0.002 * step).toFixed(4), sy: +(c.sy + 0.002 * step).toFixed(4) });
          case ",": return n({ sx: +(c.sx - 0.002 * step).toFixed(4) });
          case ".": return n({ sx: +(c.sx + 0.002 * step).toFixed(4) });
          case ";": return n({ sy: +(c.sy - 0.002 * step).toFixed(4) });
          case "'": return n({ sy: +(c.sy + 0.002 * step).toFixed(4) });
          default: return c;
        }
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [calibrating, corner]);

  const { scenario, scenarioError, scenarioMismatch, reactions, observations } = world;
  const view = extrapolateClock(clock.view, clock.sentAt, performance.now());
  const snapshot = view.phase === "RESULTS" && finalSnapshot ? finalSnapshot : world.snapshot;
  const clockStale = view.sessionId != null && performance.now() - clock.sentAt > CLOCK_STALE_MS;
  const open = !clockStale && world.status === "live" && (view.mode === "running" || view.mode === "paused") && view.elapsedMs < FREEZE_AT_MS;
  const model = useMemo(
    () => (scenario && snapshot ? buildBoardModel(scenario, snapshot, BEATS[view.phase].pieces, open) : null),
    [scenario, snapshot, view.phase, open],
  );
  const results = useMemo(() => (scenario && snapshot && view.phase === "RESULTS" ? buildResults(scenario, snapshot) : null), [scenario, snapshot, view.phase]);
  const revealed = view.elapsedMs >= MISSION1_REVEAL_MS;
  const guide = useMemo(() => buildGuide(view, snapshot), [view.phase, view.surge, revealed, snapshot]);
  const recent = (world.physicalFeedback ?? []).filter(f => f.until > Date.now());
  const feedback = recent.filter(f => f.board_uv);
  const physicalPending = feedback.filter(f => f.status === "pending").map(f => ({ token_id: f.track_id, board_uv: f.board_uv!, label: f.rejection_reason === "detection_pending" ? "PIECE DETECTED" : "CHECKING PLACEMENT" }));
  const pending = [...[...observations.values()].filter((o) => o.vision_status === "pending" && !snapshot?.tokens.some((t) => t.id === o.token_id)), ...physicalPending];
  const hint = (f: (typeof recent)[number]) => placementHint(f.piece_class ? PIECE_OF_CLASS[f.piece_class] : null, f.rejection_reason);
  const physicalRejections = feedback.filter(f => f.status === "rejected").map(f => ({ id: f.event_id, uv: f.board_uv!, text: hint(f), until: f.until }));
  // A rejected placement without a usable position is still never silent.
  const notices = recent.filter(f => f.status === "rejected" && !f.board_uv).map(hint);
  const registrationBlocked = surface !== "screen" && !mappingReady;
  const hold = !scenario || !snapshot ? LIVE_DATA_UNAVAILABLE : registrationBlocked ? BOARD_REGISTRATION_REQUIRED : null;
  const transform = calibrationMatrix3d(cal, size.w, size.h);
  const print = world.registration?.board;
  const aspect = print ? print.width_mm / print.height_mm : PRINT_W / PRINT_H;
  const printWidth = Math.min(size.w, size.h * aspect);
  const printHeight = printWidth / aspect;
  const frame = surface !== "screen" && mappingReady ? { position: "absolute" as const, left: (size.w-printWidth)/2, top: (size.h-printHeight)/2, width: printWidth, height: printHeight } : { width: "100%", height: "100%" };

  return (
    <div className={`projector projector-${surface}`}>
      <div ref={stageRef} className="projector-stage" style={{ transform, transformOrigin: "0 0" }}>
        <div className="projection-frame" style={frame}>
        {scenario ? (
          <ProjectionScene
            scenario={scenario}
            snapshot={snapshot}
            model={model}
            guide={guide}
            clock={view}
            reactions={view.phase === "RESULTS" ? [] : reactions}
            rejections={view.phase === "RESULTS" ? [] : [...rejections, ...physicalRejections]}
            pending={view.phase === "RESULTS" ? [] : pending}
            surface={calibrating && surface === "overlay" ? "align" : surface}
            variant="projector"
            results={results}
            resultsSyncing={syncing || (view.phase === "RESULTS" && !finalSnapshot) || world.status !== "live" || clockStale}
            connectionLost={world.status !== "live" || clockStale}
            hold={hold}
            testPattern={!registrationBlocked && (testing || calibrating)}
            registration={world.registration}
            occlusions={Object.values(world.footprints ?? {})}
            notices={view.phase === "RESULTS" ? [] : notices}
            narrative={narrative}
          />
        ) : (
          <div className="projector-hold">
            <div className="title-html">FLOODSHIFT</div>
            <div className="subtitle-html">THE LAST CROSSING</div>
            <div className="hold-html" title={scenarioError ?? undefined}>
              {scenarioMismatch ? LIVE_DATA_UNAVAILABLE : LIVE_DATA_UNAVAILABLE}
            </div>
          </div>
        )}
        </div>
      </div>
      {calibrating && (
        <div className="cal-panel">
          <b>PROJECTOR CALIBRATION</b> the printed map is projected: line its rivers and roads up with the paper · {corner == null ? "whole image" : `corner ${["TL", "TR", "BR", "BL"][corner]}`} · arrows move · [ ] rotate · - = scale · , . x · ; ' y · 1–4 corner · 5 whole · shift ×10 · 0 reset · Enter save · C close
          <br />
          dx {cal.dx} dy {cal.dy} rot {cal.rot}° sx {cal.sx} sy {cal.sy} · corners {cal.corners.map((p) => p.join(",")).join(" | ")} · {cal.savedAt ? `saved ${new Date(cal.savedAt).toLocaleTimeString()}` : "UNSAVED"}
        </div>
      )}
    </div>
  );
}
