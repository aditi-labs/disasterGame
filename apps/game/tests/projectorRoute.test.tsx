import { act, create } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProjectorRoute } from "../src/routes/projector/ProjectorRoute";
import { BoardSvg } from "../src/game/overlays/BoardSvg";
import { fixture } from "./fixtures";

vi.mock("../src/live/useLiveWorld", () => ({ useLiveWorld: () => world }));
const world = { scenario: fixture.scenario, snapshot: fixture.states.connected, observations: new Map(), reactions: [], status: "live", clearPending: vi.fn() };
let renderer: ReturnType<typeof create>;
let receive: (event: any) => void;
let messages: any[];
let location: { search: string };
beforeEach(() => {
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
