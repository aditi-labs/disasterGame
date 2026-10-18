import { act, create } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMission } from "../src/routes/operator/useMission";
import { fixture } from "./fixtures";

let renderer: ReturnType<typeof create>;
let mission: ReturnType<typeof useMission>;
let world: any;
let messages: any[];
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date", "performance"] });
  vi.stubGlobal("window", globalThis);
  messages = [];
  vi.stubGlobal("BroadcastChannel", class { postMessage(m: unknown) { messages.push(m); } close() {} });
  const accepted = { accepted: true, world_version: 1 };
  world = {
    scenario: fixture.scenario, snapshot: fixture.states.started, status: "live", inFlight: 0,
    knownVersion: () => fixture.states.started.world_version,
    reset: vi.fn().mockResolvedValue({ reset: true, world_version: 0 }),
    place: vi.fn().mockResolvedValue(accepted), move: vi.fn().mockResolvedValue(accepted), remove: vi.fn().mockResolvedValue(accepted),
    advanceStage: vi.fn().mockResolvedValue({ accepted: false, world_version: 1, rejection_reason: "last_stage" }),
    suggest: vi.fn().mockResolvedValue({ has_suggestion: false }), clearPending: vi.fn(), push: vi.fn(),
    controlRun: vi.fn().mockImplementation(async () => ({ snapshot: world.snapshot })),
  };
  function Harness() { mission = useMission(world); return null; }
  act(() => { renderer = create(<Harness />); });
});
afterEach(() => { act(() => renderer.unmount()); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("operator mission controller", () => {
  it("starts through real scenario START and every existing population site before clocking", async () => {
    await act(async () => { await mission.startGame(); });
    expect(world.reset).toHaveBeenCalledOnce();
    expect(world.place.mock.calls.map((c: any[]) => c[0])).toEqual(["disaster_start", "person", "person"]);
    expect(mission.phase).toBe("WARNING");
    expect(messages.some(m => m.t === "command" && m.cmd === "exit-tools")).toBe(true);
    await act(async () => { await mission.startGame(); });
    expect(world.reset).toHaveBeenCalledOnce();
  });
  it("asks the backend ghost planner for Matsya's Guidance once, 8 s into Mission 1", async () => {
    world.snapshot = fixture.states.game_start;
    await act(async () => { await mission.startGame(); });
    await act(async () => { vi.advanceTimersByTime(17000); });
    expect(world.suggest).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1500); });
    expect(world.suggest).toHaveBeenCalledTimes(1);
    expect(world.suggest).toHaveBeenCalledWith("access", "game_clock");
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(world.suggest).toHaveBeenCalledTimes(1);
  });
  it("never asks for guidance once the crossing is restored", async () => {
    world.snapshot = fixture.states.game_bridge;
    await act(async () => { await mission.startGame(); });
    await act(async () => { vi.advanceTimersByTime(25000); });
    expect(world.suggest).not.toHaveBeenCalled();
  });
  it("keeps setup out of the timer when one population action fails", async () => {
    world.place.mockResolvedValueOnce({ accepted: true }).mockResolvedValueOnce({ accepted: true }).mockResolvedValueOnce({ accepted: false, rejection_reason: "resource_exhausted" });
    await act(async () => { await mission.startGame(); });
    expect(mission.clock.mode).toBe("idle");
    expect(mission.startError).toContain("people_west");
    expect(mission.startError).toContain("Reset and retry");
  });
  it("sends the scheduled surge once across pause/resume and renders the real rejection", async () => {
    await act(async () => { await mission.startGame(); });
    await act(async () => { vi.advanceTimersByTime(50000); });
    expect(world.advanceStage).toHaveBeenCalledTimes(1);
    expect(world.advanceStage.mock.calls[0][1]).toBe("game_clock");
    expect(mission.clock.surge.status).toBe("failed");
    await act(async () => { await mission.pause(); });
    await act(async () => { vi.advanceTimersByTime(10000); await mission.resume(); });
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(world.advanceStage).toHaveBeenCalledTimes(1);
  });
  it("retains the running mission when reset fails, and clears it only on confirmation", async () => {
    await act(async () => { await mission.startGame(); });
    const sessionId = mission.clock.sessionId;
    world.reset.mockResolvedValueOnce(null);
    await act(async () => { await mission.resetGame(); });
    expect(mission.clock.sessionId).toBe(sessionId);
    expect(mission.clock.mode).toBe("running");
    expect(mission.notice).toContain("retained");
    await act(async () => { await mission.resetGame(); });
    expect(mission.clock.mode).toBe("idle");
    expect(mission.startedAt).toBeNull();
  });
  it("blocks late clicks at 70 seconds and marks in-flight results on both screens", async () => {
    await act(async () => { await mission.startGame(); });
    act(() => { vi.advanceTimersByTime(70000); });
    const before = world.place.mock.calls.length;
    await act(async () => { await mission.manual.place("bridge", "crossing_east", [0.5, 0.5]); });
    expect(world.place).toHaveBeenCalledTimes(before);
    world.inFlight = 1;
    act(() => { vi.advanceTimersByTime(100); });
    expect(mission.resultsSyncing).toBe(true);
    expect(messages.filter(m => m.t === "clock").at(-1).syncing).toBe(true);
  });
  it("blocks manual input while the socket is offline", async () => {
    await act(async () => { await mission.startGame(); });
    world.status = "offline";
    act(() => { vi.advanceTimersByTime(100); });
    await act(async () => { await mission.manual.remove("bridge"); });
    expect(world.remove).not.toHaveBeenCalled();
    expect(mission.inputOpen).toBe(false);
  });
  it("starts the next run with the same START control after results", async () => {
    await act(async () => { await mission.startGame(); });
    const previous = mission.clock.sessionId;
    act(() => mission.end());
    expect(mission.clock.mode).toBe("finished");
    await act(async () => { await mission.startGame(); });
    expect(mission.clock.mode).toBe("running");
    expect(mission.clock.sessionId).not.toBe(previous);
    expect(world.reset).toHaveBeenCalledTimes(2);
  });
  it("waits for an acknowledged snapshot, then preserves and broadcasts the final state", async () => {
    await act(async () => { await mission.startGame(); });
    world.knownVersion = () => fixture.states.connected.world_version;
    act(() => { vi.advanceTimersByTime(70000); });
    expect(mission.finalSnapshot).toBeNull();
    expect(mission.resultsSyncing).toBe(true);
    world.snapshot = fixture.states.connected;
    await act(async () => { vi.advanceTimersByTime(100); });
    expect(mission.finalSnapshot).toBe(fixture.states.connected);
    expect(messages.filter(m => m.t === "clock").at(-1).finalSnapshot).toBe(fixture.states.connected);
    world.snapshot = fixture.states.services;
    act(() => { vi.advanceTimersByTime(100); });
    expect(mission.finalSnapshot).toBe(fixture.states.connected);
    await act(async () => { await mission.resetGame(); });
    expect(mission.finalSnapshot).toBeNull();
  });
});
