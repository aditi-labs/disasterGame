import type { ActionResult, Envelope, HealthResponse, SuggestResponse, WorldAction, WorldSnapshot } from "../types/contracts";
import type { ScenarioGeometry } from "../types/scenario";

// The only way the game talks to the world: the retained FastAPI gateway
// (backend/main.py). The UI never mutates world state itself; it sends a WorldAction
// and draws the next world.snapshot. There is no offline, demo or mock transport.

export type ConnectionStatus = "connecting" | "live" | "stale" | "offline";

/** Free-form status the perception process posts to /perception/status (lanes B/C). */
export type PerceptionStatus = Record<string, unknown>;

export interface WorldTransport {
  readonly baseUrl: string;
  connect(onEnvelope: (e: Envelope) => void, onStatus: (s: ConnectionStatus) => void): () => void;
  getWorld(): Promise<WorldSnapshot>;
  getScenario(): Promise<ScenarioGeometry>;
  health(): Promise<HealthResponse>;
  perceptionStatus(): Promise<PerceptionStatus>;
  sendAction(action: WorldAction): Promise<ActionResult>;
  /** POST /reset: the gateway reads the current version itself, so reset never goes stale. */
  reset(): Promise<{ reset: boolean; world_version: number }>;
  suggest(goalId: string): Promise<SuggestResponse>;
}

const STALE_AFTER_MS = 10_000;

let counter = 0;
export function newActionId(prefix = "ui"): string {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter}`;
}

export function nowUtc(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify((await res.json()).detail ?? "");
    } catch {
      /* body was not JSON */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? " " + detail : ""}`);
  }
  return (await res.json()) as T;
}

export function createLiveTransport(baseUrl: string): WorldTransport {
  const http = baseUrl.replace(/\/$/, "");
  const wsUrl = http.replace(/^http/, "ws") + "/ws";
  const get = <T>(path: string) => fetch(http + path).then(json<T>);
  const post = <T>(path: string, body: unknown) =>
    fetch(http + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(json<T>);

  return {
    baseUrl: http,

    connect(onEnvelope, onStatus) {
      let ws: WebSocket | null = null;
      let closed = false;
      let retry = 0;
      let staleTimer: number | undefined;
      let heartbeat: number | undefined;
      let reconnectTimer: number | undefined;

      const markFresh = () => {
        window.clearTimeout(staleTimer);
        onStatus("live");
        staleTimer = window.setTimeout(() => onStatus("stale"), STALE_AFTER_MS);
      };

      const open = () => {
        if (closed) return;
        onStatus("connecting");
        const socket = new WebSocket(wsUrl);
        ws = socket;
        socket.onopen = async () => {
          if (closed || socket !== ws) return;
          retry = 0;
          markFresh();
          heartbeat = window.setInterval(() => socket.readyState === WebSocket.OPEN && socket.send("ping"), 5000);
          // After any (re)connect, pull the current snapshot rather than trusting old state.
          try {
            const payload = await get<WorldSnapshot>("/world");
            if (!closed && socket === ws && socket.readyState === WebSocket.OPEN) onEnvelope({ type: "world.snapshot", seq: -1, sent_at: nowUtc(), payload });
          } catch {
            /* the socket still delivers snapshots */
          }
        };
        socket.onmessage = (ev) => {
          if (closed || socket !== ws) return;
          markFresh();
          try {
            onEnvelope(JSON.parse(ev.data) as Envelope);
          } catch {
            /* "pong" heartbeats are not JSON */
          }
        };
        socket.onclose = () => {
          if (closed || socket !== ws) return;
          window.clearTimeout(staleTimer);
          window.clearInterval(heartbeat);
          onStatus("offline");
          retry = Math.min(retry + 1, 5);
          reconnectTimer = window.setTimeout(open, 500 * 2 ** retry);
        };
        socket.onerror = () => socket.close();
      };

      open();
      return () => {
        closed = true;
        window.clearTimeout(staleTimer);
        window.clearTimeout(reconnectTimer);
        window.clearInterval(heartbeat);
        ws?.close();
      };
    },

    getWorld: () => get<WorldSnapshot>("/world"),
    // No fallback geometry: if the gateway is down the UI says so instead of drawing a board.
    getScenario: () => get<ScenarioGeometry>("/scenario"),
    health: () => get<HealthResponse>("/health"),
    perceptionStatus: () => get<PerceptionStatus>("/perception/status"),
    sendAction: (action) => post<ActionResult>("/action", action),
    reset: () => post<{ reset: boolean; world_version: number }>("/reset", {}),
    // The ghost itself arrives in the next snapshot's ghost_suggestion.
    suggest: (goalId) => post<SuggestResponse>("/plan/suggest", { goal_id: goalId }),
  };
}
