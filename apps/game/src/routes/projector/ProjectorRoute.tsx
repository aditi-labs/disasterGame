import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLiveWorld } from "../../live/useLiveWorld";
import { openChannel, type ChannelMessage, type RejectionCue } from "../../game/channel";
import { CLOCK_STALE_MS, extrapolateClock, FREEZE_AT_MS, IDLE_VIEW, type ClockView } from "../../game/clock";
import { calibrationMatrix3d, DEFAULT_CALIBRATION, type Calibration } from "../../game/homography";
import { BoardSvg } from "../../game/overlays/BoardSvg";
import { buildResults } from "../../game/results";
import { BEATS, LIVE_DATA_UNAVAILABLE } from "../../game/story";
import { buildBoardModel } from "../../game/worldAdapter";

// /projector — fullscreen projection over the printed board. No diagnostics, no code
// labels, no sound. Retained keys (floodshift- ProjectionView):
//   F fullscreen · M overlay-only <-> screen basemap · C projector calibration
// plus T registration test pattern. In calibration: arrows move, [ ] rotate, - = scale,
// , . x-scale, ; ' y-scale, 1–4 pick a keystone corner (arrows then move that corner,
// 5 back to whole-image), shift ×10, 0 reset, Enter save.

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
  const [overlay, setOverlay] = useState(params.get("mode") !== "screen");
  const [calibrating, setCalibrating] = useState(false);
  const [testing, setTesting] = useState(false);
  const [corner, setCorner] = useState<number | null>(null);
  const [cal, setCal] = useState<Calibration>(loadCal);
  const [clock, setClock] = useState<{ view: ClockView; sentAt: number }>({ view: IDLE_VIEW, sentAt: performance.now() });
  const [syncing, setSyncing] = useState(false);
  const [rejections, setRejections] = useState<RejectionCue[]>([]);
  const [, setTick] = useState(0);
  const stageRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  const channel = useRef<ReturnType<typeof openChannel> | null>(null);
  const clearPending = world.clearPending;

  useEffect(() => saveCal(cal), [cal]);

  useEffect(() => {
    const onMessage = (m: ChannelMessage) => {
      switch (m.t) {
        case "clock":
          setClock({ view: m.view, sentAt: performance.now() });
          setSyncing(m.syncing);
          break;
        case "reject":
          setRejections((list) => [...list.filter((r) => r.until > Date.now()), m.cue]);
          window.setTimeout(() => setRejections((list) => list.filter((r) => r.id !== m.cue.id)), Math.max(0, m.cue.until - Date.now()));
          break;
        case "command":
          if (m.cmd === "calibrate") setCalibrating(true);
          else if (m.cmd === "test") setTesting((v) => !v);
          else if (m.cmd === "overlay") setOverlay(true);
          else if (m.cmd === "screen") setOverlay(false);
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
      channel.current?.post({ t: "projector-health", overlay, calibrating, testing, calibratedAt: cal.savedAt, sentAt: Date.now() });
    send();
    const id = window.setInterval(send, 1000);
    return () => window.clearInterval(id);
  }, [overlay, calibrating, testing, cal.savedAt]);

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
      if (k === "m") return setOverlay((v) => !v);
      if (k === "c") {
        setCorner(null);
        return setCalibrating((v) => !v);
      }
      if (k === "t") return setTesting((v) => !v);
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

  const { snapshot, scenario, scenarioError, scenarioMismatch, reactions, observations } = world;
  const view = extrapolateClock(clock.view, clock.sentAt, performance.now());
  const clockStale = view.sessionId != null && performance.now() - clock.sentAt > CLOCK_STALE_MS;
  const open = !clockStale && world.status === "live" && (view.mode === "running" || view.mode === "paused") && view.elapsedMs < FREEZE_AT_MS;
  const model = useMemo(
    () => (scenario && snapshot ? buildBoardModel(scenario, snapshot, BEATS[view.phase].pieces, open) : null),
    [scenario, snapshot, view.phase, open],
  );
  const results = useMemo(() => (scenario && snapshot && view.phase === "RESULTS" ? buildResults(scenario, snapshot) : null), [scenario, snapshot, view.phase]);
  const pending = [...observations.values()].filter((o) => o.vision_status === "pending" && !snapshot?.tokens.some((t) => t.id === o.token_id));
  const hold = !scenario || !snapshot ? LIVE_DATA_UNAVAILABLE : null;
  const transform = calibrationMatrix3d(cal, size.w, size.h);

  return (
    <div className={`projector ${overlay ? "projector-overlay" : "projector-screen"}`}>
      <div ref={stageRef} className="projector-stage" style={{ transform, transformOrigin: "0 0" }}>
        {scenario ? (
          <BoardSvg
            scenario={scenario}
            snapshot={snapshot}
            model={model}
            clock={view}
            reactions={reactions}
            rejections={rejections}
            pending={pending}
            surface={overlay ? "overlay" : "screen"}
            variant="projector"
            results={results}
            resultsSyncing={syncing || world.status !== "live" || clockStale}
            connectionLost={world.status !== "live" || clockStale}
            hold={hold}
            testPattern={testing || calibrating}
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
      {calibrating && (
        <div className="cal-panel">
          <b>PROJECTOR CALIBRATION</b> {corner == null ? "whole image" : `corner ${["TL", "TR", "BR", "BL"][corner]}`} · arrows move · [ ] rotate · - = scale · , . x · ; ' y · 1–4 corner · 5 whole · shift ×10 · 0 reset · Enter save · C close
          <br />
          dx {cal.dx} dy {cal.dy} rot {cal.rot}° sx {cal.sx} sy {cal.sy} · corners {cal.corners.map((p) => p.join(",")).join(" | ")} · {cal.savedAt ? `saved ${new Date(cal.savedAt).toLocaleTimeString()}` : "UNSAVED"}
        </div>
      )}
    </div>
  );
}
