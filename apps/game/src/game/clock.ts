// 75-second mission clock: a pure reducer over monotonic time (spec §9 "Game phase logic").
//
//   IDLE -> INTRO (optional, outside clock) -> WARNING -> CROSSING -> RELIEF -> SURGE -> RESULTS -> IDLE/REPLAY
//
// The clock only paces the story. World consequences come from backend snapshots; the
// clock never decides a route, a flood footprint or a score. `now` is always a
// monotonic timestamp (performance.now()), never wall-clock time.

export type GamePhase = "IDLE" | "INTRO" | "WARNING" | "CROSSING" | "RELIEF" | "SURGE" | "RESULTS";
export type ClockMode = "idle" | "intro" | "running" | "paused" | "finished";

/** Phase boundaries in seconds of mission elapsed time. */
export const BOUNDARIES_S = { CROSSING: 10, RELIEF: 30, SURGE: 50, RESULTS: 70, END: 75 } as const;
export const MISSION_MS = BOUNDARIES_S.END * 1000;
export const SURGE_AT_MS = BOUNDARIES_S.SURGE * 1000;
/** Design choice (spec allows it): operator input freezes when the results window opens. */
export const FREEZE_AT_MS = BOUNDARIES_S.RESULTS * 1000;

export type SurgeState =
  | { status: "not_due" }
  | { status: "requested"; actionId: string }
  | { status: "accepted"; actionId: string; worldVersion: number }
  | { status: "failed"; actionId: string; reason: string };

export interface ClockState {
  mode: ClockMode;
  /** One id per mission run; also the idempotency root for that run's one-time actions. */
  sessionId: string | null;
  /** Elapsed ms banked before the current running segment. */
  bankedMs: number;
  /** Monotonic time the current running segment began; null unless running. */
  segmentStart: number | null;
  surge: SurgeState;
  endedEarly: boolean;
}

export type ClockEvent =
  | { type: "intro" }
  | { type: "start"; sessionId: string; now: number }
  | { type: "pause"; now: number }
  | { type: "resume"; now: number }
  | { type: "tick"; now: number }
  | { type: "end"; now: number }
  | { type: "reset" }
  | { type: "surge_requested"; actionId: string }
  | { type: "surge_result"; actionId: string; accepted: boolean; worldVersion?: number; reason?: string | null };

export const INITIAL_CLOCK: ClockState = {
  mode: "idle",
  sessionId: null,
  bankedMs: 0,
  segmentStart: null,
  surge: { status: "not_due" },
  endedEarly: false,
};

export function elapsedMs(s: ClockState, now: number): number {
  const live = s.mode === "running" && s.segmentStart != null ? Math.max(0, now - s.segmentStart) : 0;
  return Math.min(MISSION_MS, s.bankedMs + live);
}

export function remainingMs(s: ClockState, now: number): number {
  return MISSION_MS - elapsedMs(s, now);
}

export function phaseAt(ms: number): GamePhase {
  const t = ms / 1000;
  if (t < BOUNDARIES_S.CROSSING) return "WARNING";
  if (t < BOUNDARIES_S.RELIEF) return "CROSSING";
  if (t < BOUNDARIES_S.SURGE) return "RELIEF";
  if (t < BOUNDARIES_S.RESULTS) return "SURGE";
  return "RESULTS";
}

export function phaseOf(s: ClockState, now: number): GamePhase {
  switch (s.mode) {
    case "idle":
      return "IDLE";
    case "intro":
      return "INTRO";
    case "finished":
      return "RESULTS";
    default:
      return phaseAt(elapsedMs(s, now));
  }
}

/** Operator placements are open while the mission runs (or is paused) and before the results window. */
export function inputOpen(s: ClockState, now: number): boolean {
  return (s.mode === "running" || s.mode === "paused") && elapsedMs(s, now) < FREEZE_AT_MS;
}

/** The one-time surge flood advance is due exactly once per session. */
export function surgeDue(s: ClockState, now: number): boolean {
  const t = elapsedMs(s, now);
  return s.mode === "running" && s.surge.status === "not_due" && t >= SURGE_AT_MS && t < FREEZE_AT_MS;
}

/** Stable idempotency key: a re-render, pause/resume or retry can never advance twice. */
export function surgeActionId(sessionId: string): string {
  return `surge-${sessionId}`;
}

export function clockReducer(s: ClockState, e: ClockEvent): ClockState {
  switch (e.type) {
    case "intro":
      return s.mode === "idle" ? { ...s, mode: "intro" } : s;
    case "start":
      if (s.mode !== "idle" && s.mode !== "intro") return s;
      return { ...INITIAL_CLOCK, mode: "running", sessionId: e.sessionId, segmentStart: e.now };
    case "pause":
      return s.mode === "running" ? { ...s, mode: "paused", bankedMs: elapsedMs(s, e.now), segmentStart: null } : s;
    case "resume":
      return s.mode === "paused" ? { ...s, mode: "running", segmentStart: e.now } : s;
    case "tick":
      return s.mode === "running" && elapsedMs(s, e.now) >= MISSION_MS
        ? { ...s, mode: "finished", bankedMs: MISSION_MS, segmentStart: null }
        : s;
    case "end": {
      if (s.mode !== "running" && s.mode !== "paused") return s;
      const t = elapsedMs(s, e.now);
      return { ...s, mode: "finished", bankedMs: t, segmentStart: null, endedEarly: t < MISSION_MS };
    }
    case "reset":
      return INITIAL_CLOCK;
    case "surge_requested":
      return s.mode === "running" && s.surge.status === "not_due" ? { ...s, surge: { status: "requested", actionId: e.actionId } } : s;
    case "surge_result":
      if (s.surge.status !== "requested" || s.surge.actionId !== e.actionId) return s;
      return {
        ...s,
        surge: e.accepted
          ? { status: "accepted", actionId: e.actionId, worldVersion: e.worldVersion ?? 0 }
          : { status: "failed", actionId: e.actionId, reason: e.reason ?? "rejected" },
      };
  }
}

/** Serializable view the operator broadcasts to the projector window. */
export interface ClockView {
  mode: ClockMode;
  phase: GamePhase;
  elapsedMs: number;
  remainingMs: number;
  surge: SurgeState["status"];
  surgeReason: string | null;
  sessionId: string | null;
  endedEarly: boolean;
}

export function clockView(s: ClockState, now: number): ClockView {
  return {
    mode: s.mode,
    phase: phaseOf(s, now),
    elapsedMs: elapsedMs(s, now),
    remainingMs: remainingMs(s, now),
    surge: s.surge.status,
    surgeReason: s.surge.status === "failed" ? s.surge.reason : null,
    sessionId: s.sessionId,
    endedEarly: s.endedEarly,
  };
}

export const IDLE_VIEW: ClockView = clockView(INITIAL_CLOCK, 0);
