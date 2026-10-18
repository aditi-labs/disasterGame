import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { LiveWorld } from "../../live/useLiveWorld";
import type { ActionResult, TokenType, UV, WorldSnapshot } from "../../types/contracts";
import { openChannel, type ChannelMessage, type ProjectorCommand, type RejectionCue } from "../../game/channel";
import { clockReducer, clockView, INITIAL_CLOCK, phaseOf, surgeActionId, surgeDue, inputOpen as clockInputOpen } from "../../game/clock";
import { play, unlockAudio } from "../../game/sound";
import { FLOOD_UPDATE_UNAVAILABLE, rejectionCopy } from "../../game/story";
import { BOUNDARIES_S } from "../../game/clock";
import { MATSYA_DELAY_MS } from "../../game/settings";

// Operator-side mission controller: owns the 75-second clock, the one-time surge
// action, digital START and the link to the projector window. Every world change it
// makes goes through the same authoritative /action and /reset endpoints the camera
// path uses; the clock itself never changes world state except via those actions.

export interface ProjectorHealth {
  overlay: boolean;
  calibrating: boolean;
  testing: boolean;
  calibratedAt: string | null;
  alignmentVerified: boolean;
  seenAt: number;
}

const REJECT_MS = 1800;

function newSessionId(): string {
  const d = new Date();
  const stamp = `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}${String(d.getUTCDate()).padStart(2, "0")}T${String(d.getUTCHours()).padStart(2, "0")}${String(d.getUTCMinutes()).padStart(2, "0")}${String(d.getUTCSeconds()).padStart(2, "0")}`;
  return `run-${stamp}-${Math.random().toString(36).slice(2, 6)}`;
}

export function useMission(world: LiveWorld) {
  const [clock, dispatch] = useReducer(clockReducer, INITIAL_CLOCK);
  const [now, setNow] = useState(() => performance.now());
  const [projector, setProjector] = useState<ProjectorHealth | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [rejections, setRejections] = useState<RejectionCue[]>([]);
  const channel = useRef<ReturnType<typeof openChannel> | null>(null);
  const surgeSent = useRef<string | null>(null);
  const clockRef = useRef(clock);
  clockRef.current = clock;
  const worldRef = useRef(world);
  worldRef.current = world;
  const operationPending = useRef(false);
  const phase = phaseOf(clock, now);
  const [finalState, setFinalState] = useState<{ sessionId: string; snapshot: WorldSnapshot } | null>(null);
  const closing = useRef(false);
  const closeRetryAt = useRef(0);
  const finalSnapshot = phase === "RESULTS" && finalState?.sessionId === clock.sessionId ? finalState.snapshot : null;
  const awaitingWorld = world.inFlight > 0 || world.status !== "live" || (world.snapshot?.world_version ?? -1) < world.knownVersion();
  const resultsSyncing = awaitingWorld || (phase === "RESULTS" && !finalSnapshot);
  const finalRef = useRef(finalSnapshot);
  finalRef.current = finalSnapshot;
  const syncingRef = useRef(resultsSyncing);
  syncingRef.current = resultsSyncing;

  // Close physical input under the backend mutation lock, then capture its snapshot.
  useEffect(() => {
    if (phase !== "RESULTS") {
      setFinalState(null);
    } else if (!finalSnapshot && !closing.current && now >= closeRetryAt.current && !awaitingWorld && clock.sessionId) {
      const sessionId = clock.sessionId;
      closing.current = true;
      void world.controlRun(sessionId, "close").then(result => {
        if (!result.snapshot) throw new Error("Final snapshot unavailable");
        if (clockRef.current.sessionId === sessionId) setFinalState({ sessionId, snapshot: result.snapshot });
      }).catch(() => { closeRetryAt.current = performance.now() + 2000; setNotice("Final state not confirmed. Reconnect to complete results."); })
        .finally(() => { closing.current = false; });
    }
  }, [phase, clock.sessionId, awaitingWorld, world.snapshot, finalSnapshot, now]);

  useEffect(() => {
    const onMessage = (m: ChannelMessage) => {
      if (m.t === "projector-health") setProjector({ overlay: m.overlay, calibrating: m.calibrating, testing: m.testing, calibratedAt: m.calibratedAt, alignmentVerified: m.alignmentVerified, seenAt: Date.now() });
    };
    channel.current = openChannel(onMessage);
    return () => channel.current?.close();
  }, []);

  // Monotonic tick: drives the countdown, the 75 s end and the one-time surge.
  useEffect(() => {
    const id = window.setInterval(() => {
      const t = performance.now();
      setNow(t);
      dispatch({ type: "tick", now: t });
    }, 100);
    return () => window.clearInterval(id);
  }, []);

  // Broadcast the clock to the projector (on change and every 250 ms).
  useEffect(() => {
    const id = window.setInterval(() => channel.current?.post({ t: "clock", view: clockView(clockRef.current, performance.now()), sentAt: Date.now(), syncing: syncingRef.current, finalSnapshot: finalRef.current }), 250);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    channel.current?.post({ t: "clock", view: clockView(clock, performance.now()), sentAt: Date.now(), syncing: resultsSyncing, finalSnapshot });
  }, [clock, resultsSyncing, finalSnapshot]);

  const lastPhase = useRef(phase);
  useEffect(() => {
    if (phase === lastPhase.current) return;
    lastPhase.current = phase;
    if (phase === "RESULTS") play("chord");
  }, [phase]);

  // One-time surge at 50 s: stable action id + reducer guard + ref guard, so a
  // re-render, StrictMode double effect or pause/resume cannot advance twice. No new
  // flood is drawn until the backend accepts and broadcasts the next snapshot.
  useEffect(() => {
    if (!clock.sessionId || !surgeDue(clock, now) || surgeSent.current === clock.sessionId) return;
    const actionId = surgeActionId(clock.sessionId);
    surgeSent.current = clock.sessionId;
    dispatch({ type: "surge_requested", actionId });
    void world.advanceStage(actionId, "game_clock").then((r) => {
      dispatch({ type: "surge_result", actionId, accepted: !!r?.accepted, worldVersion: r?.world_version, reason: r ? r.rejection_reason : "request_failed" });
      if (r?.accepted) play("swell");
      else world.push("warning", `${FLOOD_UPDATE_UNAVAILABLE}: surge advance_stage ${r ? `rejected (${r.rejection_reason})` : "request failed"}`);
    });
  }, [clock, now, world]);

  // Matsya's Guidance reuses the backend ghost planner (/plan/suggest, goal "access"). It is
  // requested once per run when Mission 1 has gone MATSYA_DELAY_MS without a restored
  // crossing; the fish appears only if the backend returns a real ghost_suggestion.
  const guidanceAsked = useRef<string | null>(null);
  useEffect(() => {
    const m = world.snapshot?.mission;
    const t = clock.mode === "running" ? now : null;
    if (!clock.sessionId || t == null || guidanceAsked.current === clock.sessionId || !m || m.crossing_restored || world.snapshot?.ghost_suggestion) return;
    const elapsed = clockView(clock, t).elapsedMs;
    if (elapsed < BOUNDARIES_S.CROSSING * 1000 + MATSYA_DELAY_MS || elapsed >= BOUNDARIES_S.RESULTS * 1000) return;
    guidanceAsked.current = clock.sessionId;
    void world.suggest("access", "game_clock");
  }, [clock, now, world]);

  const askMatsya = useCallback(async () => {
    if (!clockInputOpen(clockRef.current, performance.now()) || worldRef.current.status !== "live") return null;
    return world.suggest("access", "operator_manual");
  }, [world]);

  const command = useCallback((cmd: ProjectorCommand) => channel.current?.post({ t: "command", cmd }), []);

  /** Rejections are not broadcast by the backend, so the operator forwards them as a short cue. */
  const cueResult = useCallback((r: ActionResult | null, uv?: UV | null) => {
    if (!r || r.accepted || !uv) return;
    const cue = { id: `rej-${r.action_id}`, uv, text: rejectionCopy(r.rejection_reason), until: Date.now() + REJECT_MS };
    channel.current?.post({ t: "reject", cue });
    setRejections((list) => [...list.filter((x) => x.until > Date.now()), cue]);
    window.setTimeout(() => setRejections((list) => list.filter((x) => x.id !== cue.id)), REJECT_MS);
  }, []);
  const clearAll = useCallback(() => {
    world.clearPending();
    channel.current?.post({ t: "clear-pending", tokenIds: [] });
  }, [world]);

  /**
   * START GAME: authoritative reset, then the existing START-first rule is satisfied
   * by placing the scenario's own control START token digitally, then the scenario's
   * real population records are placed as projected groups (no person piece). The
   * clock only starts once every setup action was accepted.
   */
  const startGame = useCallback(async () => {
    const { scenario } = world;
    if (operationPending.current || !["idle", "intro", "finished"].includes(clockRef.current.mode)) return;
    unlockAudio();
    setStartError(null);
    setNotice(null);
    if (!scenario || world.status !== "live") return setStartError("Live scenario and world connection required.");
    const pad = scenario.sites.find((s) => s.kind === "control_start_pad");
    if (!pad) return setStartError("Scenario has no control_start_pad: digital START cannot satisfy the START-first rule.");
    setStarting(true);
    operationPending.current = true;
    const sessionId = newSessionId();
    try {
      const reset = await world.reset("game_setup");
      if (!reset?.reset) throw new Error("authoritative reset was not accepted");
      const start = await world.place("disaster_start", pad.id, pad.board_uv, `start-${sessionId}`, "game_setup", `start-${sessionId}`);
      if (!start?.accepted) throw new Error(`START rejected: ${start?.rejection_reason ?? "request failed"}`);
      let populated = 0;
      for (const site of scenario.sites.filter((s) => s.kind === "population_node")) {
        const r = await world.place("person", site.id, site.board_uv, `population-${site.id}`, "game_setup", `pop-${sessionId}-${site.id}`);
        if (r?.accepted) populated += 1;
        else throw new Error(`Population ${site.id} not placed: ${r?.rejection_reason ?? "request failed"}. Reset and retry START.`);
      }
      if (!populated) throw new Error("no scenario population record could be placed");
      await world.controlRun(sessionId, "start");
      surgeSent.current = null;
      setRejections([]);
      clearAll();
      command("exit-tools");
      if (clockRef.current.mode === "finished") dispatch({ type: "reset" });
      dispatch({ type: "start", sessionId, now: performance.now() });
      setStartedAt(new Date().toISOString());
      play("bell");
    } catch (err) {
      setStartError((err as Error).message);
    } finally {
      setStarting(false);
      operationPending.current = false;
    }
  }, [world, clearAll, command]);

  const resetGame = useCallback(async () => {
    if (operationPending.current || world.inFlight > 0) return null;
    operationPending.current = true;
    const r = await world.reset("operator_manual");
    operationPending.current = false;
    if (!r?.reset) {
      setNotice("RESET was not confirmed by the backend. Mission state retained; reconnect and retry.");
      return r;
    }
    dispatch({ type: "reset" });
    surgeSent.current = null;
    setRejections([]);
    setStartedAt(null);
    setStartError(null);
    clearAll();
    command("exit-tools");
    setNotice(r?.reset ? null : "RESET was not confirmed by the backend.");
    return r;
  }, [world, clearAll, command]);

  // Check monotonic time at the actual click, including the gap between timer renders.
  const canAct = () => clockInputOpen(clockRef.current, performance.now()) && worldRef.current.status === "live" && worldRef.current.inFlight === 0;

  const manual = {
    place: async (type: TokenType, siteId: string, uv: UV) => {
      if (!canAct()) return null;
      const r = await world.place(type, siteId, uv, `manual-${type}-${Date.now().toString(36)}`);
      cueResult(r, uv);
      if (r?.accepted) play("chime");
      return r;
    },
    move: async (tokenId: string, siteId: string, uv: UV) => {
      if (!canAct()) return null;
      const r = await world.move(tokenId, siteId, uv);
      cueResult(r, uv);
      return r;
    },
    remove: async (tokenId: string, uv?: UV) => {
      if (!canAct()) return null;
      const r = await world.remove(tokenId);
      cueResult(r, uv);
      return r;
    },
  };

  const advanceFlood = useCallback(async () => {
    if (!canAct()) return null;
    const r = await world.advanceStage(undefined, "operator_manual");
    setNotice(r?.accepted ? null : `${FLOOD_UPDATE_UNAVAILABLE} (${r ? r.rejection_reason : "request failed"})`);
    if (r?.accepted) play("swell");
    return r;
  }, [world]);

  const suggestBridge = useCallback(async () => {
    if (!canAct()) return null;
    const r = await world.suggest();
    setNotice(r?.has_suggestion ? null : "NO VALID SUGGESTION");
    return r;
  }, [world]);

  const transition = async (state: "pause" | "resume") => {
    const sessionId = clockRef.current.sessionId;
    if (!sessionId || operationPending.current) return;
    operationPending.current = true;
    try {
      await worldRef.current.controlRun(sessionId, state);
      dispatch({ type: state, now: performance.now() });
      setNotice(null);
    } catch {
      setNotice(`${state.toUpperCase()} was not confirmed by the backend.`);
    } finally { operationPending.current = false; }
  };

  return {
    clock,
    now,
    phase,
    view: clockView(clock, now),
    inputOpen: clockInputOpen(clock, now) && world.status === "live" && world.inFlight === 0,
    resultsSyncing,
    finalSnapshot,
    projector,
    startError,
    starting,
    notice,
    startedAt,
    rejections,
    startGame,
    resetGame,
    pause: () => transition("pause"),
    resume: () => transition("resume"),
    end: () => dispatch({ type: "end", now: performance.now() }),
    advanceFlood,
    suggestBridge,
    askMatsya,
    manual,
    command,
    clearPending: clearAll,
  };
}

export type Mission = ReturnType<typeof useMission>;
