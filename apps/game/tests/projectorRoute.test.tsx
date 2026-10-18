import { act, create } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProjectorRoute } from "../src/routes/projector/ProjectorRoute";
import { BoardSvg } from "../src/game/overlays/BoardSvg";
import { fixture } from "./fixtures";
import { IDLE_VIEW } from "../src/game/clock";

vi.mock("../src/live/useLiveWorld", () => ({ useLiveWorld: () => world }));
const world: any = { scenario: fixture.scenario, snapshot: fixture.states.connected, observations: new Map(), reactions: [], status: "live", clearPending: vi.fn() };
let renderer: ReturnType<typeof create>;
let receive: (event: any) => void;
let messages: any[];
let location: { search: string };
beforeEach(() => {
  world.snapshot = fixture.states.connected;
  world.registration = null;
  world.physicalFeedback = [];
  world.footprints = {};
  vi.useFakeTimers(); location = { search: "" }; messages = [];
  vi.stubGlobal("window", { location, innerWidth: 1920, innerHeight: 1080, setInterval, clearInterval, setTimeout, clearTimeout, addEventListener: vi.fn(), removeEventListener: vi.fn() });
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: vi.fn() });
  vi.stubGlobal("BroadcastChannel", class {
    set onmessage(callback: typeof receive) { receive = callback; }
    postMessage(message: unknown) { messages.push(message); }
    close() {}
  });
});
afterEach(() => { act(() => renderer?.unmount()); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("holds physical projection and reticles until print/world registration is supplied", () => {
  act(() => { renderer = create(<ProjectorRoute />); });
  expect(renderer.root.findByType(BoardSvg).props.hold).toBe("BOARD REGISTRATION REQUIRED");
  act(() => receive({ data: { t: "command", cmd: "test" } }));
  expect(renderer.root.findByType(BoardSvg).props.testPattern).toBe(false);
  expect(messages.find(m => m.t === "projector-health")).toMatchObject({ alignmentVerified: false, calibratedAt: null });
});
it("keeps the authoritative screen rehearsal available", () => {
  location.search = "?mode=screen";
  act(() => { renderer = create(<ProjectorRoute />); });
  expect(renderer.root.findByType(BoardSvg).props.hold).toBeNull();
  expect(renderer.root.findByType(BoardSvg).props.snapshot).toBe(fixture.states.connected);
});
it("uses the operator's captured backend snapshot for stable results after 70 seconds", () => {
  location.search = "?mode=screen";
  act(() => { renderer = create(<ProjectorRoute />); });
  act(() => receive({ data: { t: "clock", view: { ...IDLE_VIEW, sessionId: "run-final", phase: "RESULTS", mode: "finished", elapsedMs: 75000 }, syncing: false, finalSnapshot: fixture.states.connected } }));
  world.snapshot = fixture.states.services;
  act(() => { vi.advanceTimersByTime(250); });
  const board = renderer.root.findByType(BoardSvg);
  expect(board.props.snapshot).toBe(fixture.states.connected);
  expect(board.props.resultsSyncing).toBe(false);
  expect(board.props.pending).toEqual([]);
  expect(board.props.reactions).toEqual([]);
});
it("uses a supplied measured mapping and masks markers outside world geometry", () => {
  world.registration = { ready: true, world_to_print: [1,0,.1,0,1,0,0,0,1], board: { width_mm: 600, height_mm: 400 } };
  world.footprints = { "test-camera:piece": [[.4,.4],[.5,.4],[.5,.5],[.4,.5]] };
  act(() => { renderer = create(<ProjectorRoute />); });
  expect(renderer.root.findByType(BoardSvg).props.hold).toBeNull();
  const geometry = renderer.root.findAllByType("g").find(g => g.props.className === "world-geometry")!;
  expect(geometry.props.style.transform).toContain("matrix3d");
  const frame = renderer.root.findAllByType("div").find(g => g.props.className === "projection-frame")!;
  expect(frame.props.style).toMatchObject({ width: 1620, height: 1080, left: 150 });
  const masks = renderer.root.findAllByType("g").find(g => g.props.className === "layer-piece-keepouts")!;
  expect(masks.findByType("polygon").props.fill).toBe("#000");
});
it("shows physical pending and rejected cues without adding accepted world pieces", () => {
  location.search = "?mode=screen";
  world.physicalFeedback = [
    { event_id: "pending", track_id: "t1", status: "pending", board_uv: [.3,.4], until: Date.now()+2000 },
    { event_id: "rejected", track_id: "t2", status: "rejected", board_uv: [.4,.5], rejection_reason: "outside_site", until: Date.now()+2000 },
  ];
  act(() => { renderer = create(<ProjectorRoute />); });
  const board = renderer.root.findByType(BoardSvg);
  expect(board.props.pending).toMatchObject([{ token_id: "t1", board_uv: [.3,.4] }]);
  expect(board.props.rejections).toMatchObject([{ text: "MOVE CLOSER", uv: [.4,.5] }]);
  expect(board.props.snapshot).toBe(fixture.states.connected);
});
