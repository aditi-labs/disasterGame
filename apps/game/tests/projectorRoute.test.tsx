import { act, create } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProjectorRoute } from "../src/routes/projector/ProjectorRoute";
import { ProjectionScene } from "../src/game/overlays/ProjectionScene";
import { fixture } from "./fixtures";
import { IDLE_VIEW } from "../src/game/clock";

vi.mock("../src/live/useLiveWorld", () => ({ useLiveWorld: () => world }));
const world: any = { scenario: fixture.scenario, snapshot: fixture.states.connected, observations: new Map(), reactions: [], status: "live", clearPending: vi.fn() };
const mapped = { ready: true, mapping_ready: true, world_to_print: [1.3, 0, -0.02, 0, 1.58, -0.26, 0, 0, 1], board: { width_mm: 609.6, height_mm: 457.2 } };
let renderer: ReturnType<typeof create>;
let receive: (event: any) => void;
let messages: any[];
let location: { search: string };
let keydown: ((e: any) => void) | null;
beforeEach(() => {
  world.snapshot = fixture.states.connected;
  world.registration = null;
  world.physicalFeedback = [];
  world.footprints = {};
  keydown = null;
  vi.useFakeTimers(); location = { search: "" }; messages = [];
  vi.stubGlobal("window", { location, innerWidth: 1920, innerHeight: 1080, setInterval, clearInterval, setTimeout, clearTimeout, addEventListener: (t: string, f: any) => { if (t === "keydown") keydown = f; }, removeEventListener: vi.fn() });
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: vi.fn() });
  vi.stubGlobal("BroadcastChannel", class {
    set onmessage(callback: typeof receive) { receive = callback; }
    postMessage(message: unknown) { messages.push(message); }
    close() {}
  });
});
afterEach(() => { act(() => renderer?.unmount()); vi.unstubAllGlobals(); vi.useRealTimers(); });
const scene = () => renderer.root.findByType(ProjectionScene);

it("holds physical projection until the print/world mapping is supplied", () => {
  act(() => { renderer = create(<ProjectorRoute />); });
  expect(scene().props.hold).toBe("BOARD REGISTRATION REQUIRED");
  act(() => receive({ data: { t: "command", cmd: "test" } }));
  expect(scene().props.testPattern).toBe(false);
  expect(messages.find(m => m.t === "projector-health")).toMatchObject({ alignmentVerified: false, calibratedAt: null });
});
it("draws over the print with the artwork-derived mapping even before camera markers are measured", () => {
  world.registration = { ...mapped, ready: false };
  act(() => { renderer = create(<ProjectorRoute />); });
  expect(scene().props.hold).toBeNull();
  expect(scene().props.surface).toBe("overlay");
  const frame = renderer.root.findAllByType("div").find(g => g.props.className === "projection-frame")!;
  expect(frame.props.style.width).toBeCloseTo(1440, 6);
  expect(frame.props.style.height).toBeCloseTo(1080, 6);
  expect(frame.props.style.left).toBeCloseTo(240, 6);
});
it("projects the printed artwork while calibrating, so keystone is matched to the paper", () => {
  world.registration = mapped;
  act(() => { renderer = create(<ProjectorRoute />); });
  act(() => keydown!({ key: "c" }));
  expect(scene().props.surface).toBe("align");
  act(() => keydown!({ key: "c" }));
  act(() => keydown!({ key: "a" }));
  expect(scene().props.surface).toBe("align");
});
it("keeps the authoritative screen rehearsal available", () => {
  location.search = "?mode=screen";
  act(() => { renderer = create(<ProjectorRoute />); });
  expect(scene().props.hold).toBeNull();
  expect(scene().props.snapshot).toBe(fixture.states.connected);
});
it("uses the operator's captured backend snapshot for stable results after 70 seconds", () => {
  location.search = "?mode=screen";
  act(() => { renderer = create(<ProjectorRoute />); });
  act(() => receive({ data: { t: "clock", view: { ...IDLE_VIEW, sessionId: "run-final", phase: "RESULTS", mode: "finished", elapsedMs: 75000 }, syncing: false, finalSnapshot: fixture.states.connected } }));
  world.snapshot = fixture.states.services;
  act(() => { vi.advanceTimersByTime(250); });
  expect(scene().props.snapshot).toBe(fixture.states.connected);
  expect(scene().props.resultsSyncing).toBe(false);
  expect(scene().props.pending).toEqual([]);
  expect(scene().props.reactions).toEqual([]);
});
it("masks camera-measured pieces black over the print", () => {
  world.registration = mapped;
  world.footprints = { "test-camera:piece": [[.4,.4],[.5,.4],[.5,.5],[.4,.5]] };
  act(() => { renderer = create(<ProjectorRoute />); });
  const masks = renderer.root.findAllByType("g").find(g => g.props.className === "layer-piece-keepouts")!;
  expect(masks.findByType("polygon").props.fill).toBe("#000");
});
it("never ignores a placement: pending, positioned rejections and unpositioned rejections all show", () => {
  location.search = "?mode=screen";
  world.physicalFeedback = [
    { event_id: "pending", track_id: "t1", status: "pending", board_uv: [.3,.4], until: Date.now()+2000 },
    { event_id: "rejected", track_id: "t2", status: "rejected", piece_class: "bridge", board_uv: [.4,.5], rejection_reason: "outside_site", until: Date.now()+2000 },
    { event_id: "nowhere", track_id: "t3", status: "rejected", piece_class: "shelter", board_uv: null, rejection_reason: "camera_registration_required", until: Date.now()+2000 },
  ];
  act(() => { renderer = create(<ProjectorRoute />); });
  expect(scene().props.pending).toMatchObject([{ token_id: "t1", board_uv: [.3,.4] }]);
  expect(scene().props.rejections).toMatchObject([{ text: "MOVE BRIDGE CLOSER TO THE GLOWING CROSSING", uv: [.4,.5] }]);
  expect(scene().props.notices).toEqual(["CAMERA ALIGNING — HOLD STILL"]);
  expect(scene().props.snapshot).toBe(fixture.states.connected);
});
