import { describe, expect, it } from "vitest";
import { clockReducer, clockView, elapsedMs, extrapolateClock, INITIAL_CLOCK, inputOpen, phaseOf, surgeActionId, surgeDue } from "../src/game/clock";

const start = () => clockReducer(INITIAL_CLOCK, { type: "start", sessionId: "real-run", now: 1000 });

describe("75-second mission pacing", () => {
  it.each([[0, "WARNING"], [9999, "WARNING"], [10000, "CROSSING"], [30000, "RELIEF"], [50000, "SURGE"], [70000, "RESULTS"], [75000, "RESULTS"]])("at %i ms shows %s", (ms, phase) => {
    expect(phaseOf(start(), 1000 + Number(ms))).toBe(phase);
  });
  it("keeps intro outside the clock and ignores duplicate START", () => {
    const intro = clockReducer(INITIAL_CLOCK, { type: "intro" });
    expect(clockView(intro, 100000).elapsedMs).toBe(0);
    expect(phaseOf(intro, 100000)).toBe("INTRO");
    expect(clockReducer(start(), { type: "start", sessionId: "duplicate", now: 2000 })).toEqual(start());
  });
  it("banks paused time and resumes without counting the troubleshooting gap", () => {
    const paused = clockReducer(start(), { type: "pause", now: 11000 });
    expect(elapsedMs(paused, 90000)).toBe(10000);
    expect(surgeDue(paused, 90000)).toBe(false);
    expect(inputOpen(paused, 90000)).toBe(true);
    const resumed = clockReducer(paused, { type: "resume", now: 90000 });
    expect(elapsedMs(resumed, 95000)).toBe(15000);
  });
  it("requests the surge once and rejects late acknowledgments from a different run", () => {
    const s = start();
    expect(surgeDue(s, 50999)).toBe(false);
    expect(surgeDue(s, 51000)).toBe(true);
    const actionId = surgeActionId(s.sessionId!);
    const requested = clockReducer(s, { type: "surge_requested", actionId });
    expect(surgeDue(requested, 60000)).toBe(false);
    expect(clockReducer(requested, { type: "surge_requested", actionId: "duplicate" })).toEqual(requested);
    expect(clockReducer(requested, { type: "surge_result", actionId: "old-run", accepted: true })).toEqual(requested);
    const failed = clockReducer(requested, { type: "surge_result", actionId, accepted: false, reason: "last_stage" });
    expect(failed.surge.status).toBe("failed");
    expect(surgeDue(failed, 65000)).toBe(false);
  });
  it("closes input at 70 seconds and finishes at 75 without a player action", () => {
    expect(inputOpen(start(), 70999)).toBe(true);
    expect(inputOpen(start(), 71000)).toBe(false);
    const ended = clockReducer(start(), { type: "tick", now: 100000 });
    expect(ended.mode).toBe("finished");
    expect(clockView(ended, 200000).remainingMs).toBe(0);
    expect(surgeDue(start(), 80000)).toBe(false);
  });
  it("supports early end and clears all clock flags for replay", () => {
    const ended = clockReducer(start(), { type: "end", now: 16000 });
    expect(ended.endedEarly).toBe(true);
    expect(elapsedMs(ended, 100000)).toBe(15000);
    expect(clockReducer(ended, { type: "reset" })).toEqual(INITIAL_CLOCK);
  });
  it("freezes a stale projector clock without rewinding or relying on wall-clock time", () => {
    const view = clockView(start(), 11000);
    expect(extrapolateClock(view, 100, 2100).elapsedMs).toBe(12000);
    expect(extrapolateClock(view, 100, 6000).elapsedMs).toBe(13000);
    expect(extrapolateClock(view, 100, 100000).elapsedMs).toBe(13000);
    expect(extrapolateClock(view, 100, 50).elapsedMs).toBe(10000);
  });
});
