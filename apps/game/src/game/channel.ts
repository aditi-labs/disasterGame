import type { UV } from "../types/contracts";
import type { ClockView } from "./clock";

// Operator <-> projector link. Both windows read world state straight from the backend
// WebSocket; this channel carries only what the backend does not broadcast: the
// mission clock, operator action rejections, projector commands and projector health.
// BroadcastChannel is same-browser only: run /projector as a second window of the
// operator laptop's browser (docs/RUN_OF_SHOW.md).

export type ProjectorCommand = "calibrate" | "test" | "overlay" | "screen" | "exit-tools";

export interface RejectionCue {
  id: string;
  uv: UV;
  text: string;
  until: number;
}

export type ChannelMessage =
  | { t: "clock"; view: ClockView; sentAt: number; syncing: boolean }
  | { t: "reject"; cue: RejectionCue }
  | { t: "command"; cmd: ProjectorCommand }
  | { t: "clear-pending"; tokenIds: string[] }
  | { t: "projector-health"; overlay: boolean; calibrating: boolean; testing: boolean; calibratedAt: string | null; alignmentVerified: boolean; sentAt: number };

const NAME = "floodshift.game.v1";

export function openChannel(onMessage: (m: ChannelMessage) => void): { post: (m: ChannelMessage) => void; close: () => void } {
  if (typeof BroadcastChannel === "undefined") return { post: () => {}, close: () => {} };
  const ch = new BroadcastChannel(NAME);
  ch.onmessage = (ev: MessageEvent<ChannelMessage>) => onMessage(ev.data);
  return { post: (m) => ch.postMessage(m), close: () => ch.close() };
}
