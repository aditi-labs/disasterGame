import { act, create } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useLiveWorld } from "../src/live/useLiveWorld";
import { fixture } from "./fixtures";

vi.mock("../src/live/transport", async original => ({ ...await original(), createLiveTransport: () => transport }));
let receive: (event: any) => void;
let renderer: ReturnType<typeof create>;
let world: ReturnType<typeof useLiveWorld>;
const transport = {
  baseUrl: "http://local.test", connect: (cb: typeof receive, status: (s: string) => void) => { receive = cb; status("live"); return () => {}; },
  sendAction: vi.fn(), getWorld: vi.fn(), reset: vi.fn(),
};
beforeEach(async () => {
  vi.useFakeTimers(); vi.stubGlobal("window", globalThis);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture.scenario))));
  function Harness() { world = useLiveWorld(); return null; }
  await act(async () => { renderer = create(<Harness />); });
});
afterEach(() => { act(() => renderer.unmount()); vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
const hello = () => receive({ type: "server.hello", seq: 1, payload: { status: "connected" } });
const snapshot = (version: number) => receive({ type: "world.snapshot", seq: version + 10, payload: { ...fixture.states.started, world_version: version } });

it("recovers a server restarted at a nonzero lower version, then discards older deliveries", () => {
  act(() => { hello(); snapshot(20); });
  expect(world.knownVersion()).toBe(20);
  act(() => { hello(); snapshot(3); });
  expect(world.knownVersion()).toBe(3);
  expect(world.snapshot!.world_version).toBe(3);
  // A late REST response has seq -1, so version order must also be checked.
  act(() => receive({ type: "world.snapshot", seq: -1, payload: { ...fixture.states.started, world_version: 0 } }));
  expect(world.snapshot!.world_version).toBe(3);
});

it("reconciles stale actions once using the same action id and latest backend version", async () => {
  act(() => { hello(); snapshot(3); });
  const sent: any[] = [];
  transport.getWorld.mockResolvedValue({ ...fixture.states.started, world_version: 4 });
  transport.sendAction.mockImplementation(async action => {
    sent.push({ ...action });
    return sent.length === 1 ? { accepted: false, world_version: 4, rejection_reason: "stale_version" } : { accepted: true, world_version: 5 };
  });
  await act(async () => { await world.place("bridge", "crossing_east", [0.5, 0.44], "manual-piece"); });
  expect(sent).toHaveLength(2);
  expect(sent[0].action_id).toBe(sent[1].action_id);
  expect(sent.map(a => a.expected_world_version)).toEqual([3, 4]);
  expect(world.knownVersion()).toBe(5);
  expect(world.snapshot!.world_version).toBe(3); // Never paint an acknowledgment as a snapshot.
  expect(world.run.at(-1)).toMatchObject({ provenance: "operator_manual", accepted: true, versionAfter: 5 });
  act(() => snapshot(4));
  expect(world.snapshot!.world_version).toBe(4);
  expect(world.knownVersion()).toBe(5); // Results keep syncing until the acknowledged version arrives.
});
it("receives physical feedback separately and clears it on authoritative reset", () => {
  act(() => { hello(); snapshot(3); });
  act(() => receive({ type: "vision.status", seq: 20, payload: { observations: [], physical_feedback: {
    event_id: "test-observation", track_id: "test-track", status: "pending", board_uv: [.3,.4], accepted: false,
  } } }));
  expect(world.physicalFeedback).toHaveLength(1);
  expect(world.snapshot!.world_version).toBe(3);
  act(() => receive({ type: "world.snapshot", seq: 21, payload: fixture.states.ready }));
  // Lower-version snapshots on the same branch are discarded; a server reset advances its version.
  act(() => receive({ type: "world.snapshot", seq: 22, payload: { ...fixture.states.ready, world_version: 4 } }));
  expect(world.physicalFeedback).toEqual([]);
});
