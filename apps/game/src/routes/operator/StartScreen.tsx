import type { ClockMode, GamePhase } from "../../game/clock";
import { MatsyaMark } from "../../game/overlays/glyphs";
import { BEATS } from "../../game/story";

export interface StartScreenProps {
  mode: ClockMode;
  phase: GamePhase;
  remainingMs: number;
  ready: boolean;
  starting: boolean;
  physicalInputReady: boolean;
  error: string | null;
  onStart: () => void;
}

/** The normal laptop flow: one START control. Setup and manual actions live at ?tools=1. */
export function StartScreen({ mode, phase, remainingMs, ready, starting, physicalInputReady, error, onStart }: StartScreenProps) {
  const running = mode === "running" || mode === "paused";
  const seconds = Math.max(0, Math.ceil(remainingMs / 1000));
  const message = error ?? (!ready ? "Waiting for the live world…" : !physicalInputReady ? "Physical input is not ready. Check camera registration and classification." : "Physical input connected. The map follows accepted placements.");
  return (
    <main className="start-screen" data-ui="map-projection-v2">
      <div className="start-content">
        <svg className="start-mark" viewBox="-80 -45 160 100" aria-hidden="true"><MatsyaMark size={85} /></svg>
        <p className="start-brand">FLOODSHIFT</p>
        <h1>The last crossing.</h1>
        <p className="start-copy">{running ? BEATS[phase].line : mode === "finished" ? "Your response is complete. Ready for the next run." : "75 seconds. A crossing. A community."}</p>
        {running && <div className="start-time" aria-label="Mission time remaining">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}{mode === "paused" && <span>PAUSED</span>}</div>}
        <button className="start-button" disabled={!ready || running || starting} onClick={onStart}>
          {starting ? "STARTING…" : running ? "MISSION RUNNING" : "START"}
        </button>
        <p className={"start-status" + (error ? " start-error" : "")} role="status">{message}</p>
        <p className="start-tools">O · operator tools</p>
      </div>
    </main>
  );
}
