import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createLiveTransport } from "../src/live/transport";

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 0;
  onopen?: () => Promise<void>;
  onclose?: () => void;
  onmessage?: (event: { data: string }) => void;
  onerror?: () => void;
  send = vi.fn();
  constructor(public url: string) { Socket.instances.push(this); }
  async open() { this.readyState = 1; await this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
}
beforeEach(() => {
  vi.useFakeTimers(); Socket.instances = [];
  vi.stubGlobal("window", globalThis); vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ world_version: 3 }))));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("live connection recovery", () => {
  it("reloads the world, sends heartbeats and identifies a stale socket", async () => {
    const onEnvelope = vi.fn(), onStatus = vi.fn();
    const close = createLiveTransport("http://localhost:8010/").connect(onEnvelope, onStatus);
    const socket = Socket.instances[0];
    expect(socket.url).toBe("ws://localhost:8010/ws");
    await socket.open();
    expect(onEnvelope).toHaveBeenCalledWith(expect.objectContaining({ type: "world.snapshot", payload: { world_version: 3 } }));
    vi.advanceTimersByTime(5000);
    expect(socket.send).toHaveBeenCalledWith("ping");
    vi.advanceTimersByTime(5000);
    expect(onStatus).toHaveBeenLastCalledWith("stale");
    close();
  });
  it("never reconnects after unmount and never overwrites offline with stale", async () => {
    const onStatus = vi.fn();
    const close = createLiveTransport("http://localhost:8010").connect(vi.fn(), onStatus);
    await Socket.instances[0].open();
    Socket.instances[0].close();
    expect(onStatus).toHaveBeenLastCalledWith("offline");
    close();
    vi.advanceTimersByTime(60000);
    expect(Socket.instances).toHaveLength(1);
    expect(onStatus).toHaveBeenLastCalledWith("offline");
    vi.stubGlobal("window", undefined);
    expect(() => Socket.instances[0].onclose?.()).not.toThrow();
  });
  it("drops the REST reload when the socket closes before it resolves", async () => {
    let resolve: (r: Response) => void;
    vi.mocked(fetch).mockReturnValue(new Promise(r => { resolve = r; }));
    const onEnvelope = vi.fn();
    const close = createLiveTransport("http://localhost:8010").connect(onEnvelope, vi.fn());
    const opening = Socket.instances[0].open();
    close();
    resolve!(new Response("{}"));
    await opening;
    expect(onEnvelope).not.toHaveBeenCalled();
  });
});
