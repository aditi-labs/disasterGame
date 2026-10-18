import type { ClockMode, GamePhase } from "../../game/clock";
import type { Guide } from "../../game/guide";
import { optionDetail } from "../../game/guide";
import { MatsyaMark, PieceIcon } from "../../game/overlays/glyphs";
import type { Results } from "../../game/results";
import { BEATS, CHAPTERS, HOW_TO_PLAY, MANU_STORY, MANU_TODAY, PIECE_NAME } from "../../game/story";
import type { MissionOption } from "../../types/contracts";
import { manuCard } from "../../game/narrative";
import type { WorldSnapshot } from "../../types/contracts";

export interface StartScreenProps {
  mode: ClockMode;
  phase: GamePhase;
  remainingMs: number;
  ready: boolean;
  starting: boolean;
  physicalInputReady: boolean;
  error: string | null;
  onStart: () => void;
  /** Same guide the projector shows; absent before the live world loads. */
  guide?: Guide | null;
  results?: Results | null;
  /** Laptop fallback: place a piece for the players when the camera misses it. */
  onFallback?: (option: MissionOption) => void;
  fallbackBusy?: boolean;
  /** Ask the backend ghost planner for Matsya's Guidance (shown only if it has one). */
  onAskMatsya?: () => void;
  /** Final committed snapshot, for the Boat of Hope card. */
  finalSnapshot?: WorldSnapshot | null;
}

/** The normal laptop flow: START, then the same mission guide the board shows. Tools live behind O. */
export function StartScreen({ mode, phase, remainingMs, ready, starting, physicalInputReady, error, onStart, guide, results, onFallback, fallbackBusy, onAskMatsya, finalSnapshot }: StartScreenProps) {
  const card = manuCard(finalSnapshot ?? null);
  const running = mode === "running" || mode === "paused";
  const seconds = Math.max(0, Math.ceil(remainingMs / 1000));
  const message = error ?? (!ready ? "Waiting for the live world…" : !physicalInputReady ? "Physical input is not ready. Check camera registration and classification — the laptop fallback below still works." : "Camera connected. The map follows the pieces you place.");
  const current = CHAPTERS.indexOf(phase);
  const tone = guide?.tone ?? "info";
  return (
    <main className={`start-screen start-${running ? "running" : mode}`} data-ui="mission-guide-v3">
      <div className="start-content">
        <svg className="start-mark" viewBox="-80 -45 160 100" aria-hidden="true"><MatsyaMark size={85} /></svg>
        <p className="start-brand">FLOODSHIFT · THE LAST CROSSING</p>

        {!running && mode !== "finished" && (
          <>
            <h1>Be Manu. Carry them through the flood.</h1>
            <div className="start-story">{MANU_STORY.map((l) => <p key={l}>{l}</p>)}<p className="start-today">{MANU_TODAY}</p></div>
            <ol className="start-howto">{HOW_TO_PLAY.map((l) => <li key={l}>{l}</li>)}</ol>
          </>
        )}

        {running && guide && (
          <section className={`guide guide-${tone}`} aria-live="polite">
            <ol className="guide-chapters">
              {CHAPTERS.map((p, i) => (
                <li key={p} className={i < current ? "done" : i === current ? "now" : ""}>{BEATS[p].chapter} · {BEATS[p].name}</li>
              ))}
            </ol>
            <p className="guide-chapter">Chapter {guide.chapter} · {guide.chapterName}</p>
            <h1 className="guide-title">{guide.title}</h1>
            <p className="guide-story">{guide.story}</p>
            <div className="guide-step"><span>NEXT STEP</span>{guide.step}</div>
            <div className="start-time" aria-label="Mission time remaining">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}{mode === "paused" && <span>PAUSED</span>}</div>
            {onFallback && guide.fallback.length > 0 && (
              <div className="fallback">
                <p>Camera didn&apos;t catch the piece? Place it from the laptop:</p>
                {guide.fallback.map((o) => (
                  <button key={`${o.piece}-${o.site_id}`} className="fallback-button" disabled={fallbackBusy} onClick={() => onFallback(o)}>
                    <PieceIcon type={o.piece} size={14} /> {o.move_token_id ? "Move " : ""}{PIECE_NAME[o.piece]} → glowing site{optionDetail(o) ? ` (${optionDetail(o)})` : ""}
                  </button>
                ))}
              </div>
            )}
            {guide.matsya ? (
              <p className="matsya-note">MATSYA&apos;S GUIDANCE · {guide.matsya.hint}</p>
            ) : onAskMatsya && guide.phase === "CROSSING" && guide.focus.some((f) => f.kind === "crossing") ? (
              <button className="matsya-button" disabled={fallbackBusy} onClick={onAskMatsya}>Ask Matsya for guidance</button>
            ) : null}
          </section>
        )}

        {mode === "finished" && results && !results.empty && (
          <section className="impact" aria-label="Mission impact">
            <p className="guide-chapter">Chapter V · The new dawn</p>
            <h1>Mission complete. Your decisions changed the outcome.</h1>
            <div className="impact-row">
              {results.impact.map((s) => (
                <div key={s.id} className={`impact-stat impact-${s.id}`}><b>{s.value}</b><span>{s.label}</span></div>
              ))}
            </div>
            {card.length > 0 && (
              <div className="boat-card" aria-label="The Boat of Hope">
                {card.map((l) => <p key={l.id}><b>{l.title}</b>{l.text}</p>)}
                <p className="start-today">Like Manu, you were asked to protect life, family and knowledge.</p>
              </div>
            )}
            <ul className="impact-decisions">{results.decisions.map((d, i) => <li key={d.label + i} className={d.effective ? "good" : "bad"}>{d.effective ? "✓" : "✕"} {d.label}: {d.text}</li>)}</ul>
            <p className="impact-note">Model figures from this educational scenario, compared with the same flood and no response.</p>
          </section>
        )}

        <button className="start-button" disabled={!ready || running || starting} onClick={onStart}>
          {starting ? "STARTING…" : running ? "MISSION RUNNING" : "START"}
        </button>
        <p className={"start-status" + (error ? " start-error" : "")} role="status">{message}</p>
        <p className="start-tools">O · operator tools</p>
      </div>
    </main>
  );
}
