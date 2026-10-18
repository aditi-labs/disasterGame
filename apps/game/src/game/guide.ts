import { RECOGNIZED_PIECES } from "./settings";
import type { GhostSuggestion, MissionOption, ServiceKind, TokenType, WorldSnapshot } from "../types/contracts";
import type { ClockView, GamePhase } from "./clock";
import { BEATS, FLOOD_UPDATE_UNAVAILABLE, MISSION1_REVEAL_MS, PIECE_NAME } from "./story";

// What the players should know and do right now, derived only from the clock and the
// latest authoritative snapshot (including backend/world/mission.py previews and the
// ghost planner's ghost_suggestion). The projector and the laptop render the same
// Guide, so both always agree.

export type Tone = "info" | "danger" | "good";

export interface Focus {
  kind: "crossing" | "service" | "opportunity";
  option: MissionOption;
  /** Short label beside the glowing site, e.g. "BROKEN CROSSING". */
  label: string;
  detail?: string;
  tone: Tone;
}

/** Matsya's Guidance: the backend ghost planner's real suggestion, never invented here. */
export interface MatsyaGuidance {
  suggestion: GhostSuggestion;
  title: string;
  hint: string;
}

export interface Guide {
  phase: GamePhase;
  chapter: string;
  chapterName: string;
  title: string;
  story: string;
  /** The single next physical action, in imperative words. */
  step: string;
  tone: Tone;
  focus: Focus[];
  /** Pieces the laptop fallback may place (or move) for the players this beat. */
  fallback: MissionOption[];
  matsya: MatsyaGuidance | null;
}

const NEED_OF: Partial<Record<TokenType, ServiceKind>> = { shelter: "refuge", hospital: "medical", food_shelter: "food" };
const NEED_WORD: Record<ServiceKind, string> = { refuge: "refuge", medical: "medical", food: "food" };

export function optionDetail(o: MissionOption): string {
  const need = NEED_OF[o.piece];
  if (o.piece === "bridge") return o.communities_gain ? `reconnects ${o.communities_gain} community` : "";
  if (!need || !o.needs_met) return "";
  return `meets ${o.needs_met[need]} ${NEED_WORD[need]} needs`;
}

function names(list: string[], joiner = "OR"): string {
  return list.length <= 1 ? list.join("") : `${list.slice(0, -1).join(", ")} ${joiner} ${list[list.length - 1]}`;
}

export function matsyaGuidance(snapshot: WorldSnapshot | null): MatsyaGuidance | null {
  const g = snapshot?.phase === "disaster_active" ? snapshot.ghost_suggestion : null;
  if (!g) return null;
  const piece = (PIECE_NAME[g.token_type] ?? g.token_type).toLowerCase();
  return { suggestion: g, title: "MATSYA'S GUIDANCE", hint: `Try placing the ${piece} here.` };
}

export function buildGuide(clock: ClockView, snapshot: WorldSnapshot | null, pieces: readonly string[] = RECOGNIZED_PIECES): Guide {
  const phase = clock.phase;
  const beat = BEATS[phase];
  const matsya = phase === "RESULTS" ? null : matsyaGuidance(snapshot);
  const base: Guide = { phase, chapter: beat.chapter, chapterName: beat.name, title: beat.headline, story: beat.line, step: "", tone: "info", focus: [], fallback: [], matsya };
  const m = snapshot?.phase === "disaster_active" ? snapshot.mission ?? null : null;
  if (phase === "IDLE" || phase === "INTRO") return { ...base, step: "Press START on the laptop to begin." };
  if (!snapshot || !m) return { ...base, step: "Waiting for the live world…" };

  const usable = (o: MissionOption) => pieces.includes(o.piece);
  const isolated = m.isolated.map((p) => p.name);
  const restored = !!m.crossing_restored;
  const crossing = m.crossing && usable(m.crossing) ? m.crossing : null;
  const moving = !!crossing?.move_token_id;
  const crossingFocus = (label: string, tone: Tone): Focus[] => (crossing ? [{ kind: "crossing", option: crossing, label, tone }] : []);
  const servicesPlaced = m.services_placed;

  switch (phase) {
    case "WARNING": {
      const who = isolated.length ? `Families in ${names(isolated, "and")} are cut off from emergency services.` : "Every community can still reach help — for now.";
      const story = `Flash floods have destroyed the main crossing. ${who}`;
      if (clock.elapsedMs < MISSION1_REVEAL_MS || !crossing) return { ...base, story, step: "Watch the map: blue is floodwater, red is cut off.", tone: "danger" };
      return { ...base, title: "MISSION 1: RESTORE THE CROSSING", story, step: "Get ready: pick up the BRIDGE piece.", tone: "danger", focus: crossingFocus("BROKEN CROSSING", "danger") };
    }
    case "CROSSING": {
      if (restored) {
        return { ...base, title: "CROSSING RESTORED — ACCESS IMPROVED", story: `The families can reach ${m.depot?.name ?? "help"} again. Their route is open.`, step: "Next: choose which service to deploy.", tone: "good" };
      }
      if (!crossing) return { ...base, story: "No crossing can be restored with the pieces left.", step: "Hold on — help is coming in the next mission.", tone: "info" };
      if (moving) {
        return { ...base, story: "That crossing does not reconnect anyone yet.", step: "MOVE THE BRIDGE TO THE GLOWING CROSSING", tone: "danger", focus: crossingFocus("MOVE BRIDGE HERE", "danger"), fallback: [crossing] };
      }
      return { ...base, story: isolated.length ? `Reconnect ${names(isolated, "and")}: place the bridge over the glowing crossing.` : beat.line, step: "PLACE THE BRIDGE ON THE GLOWING CROSSING", tone: "danger", focus: crossingFocus("PLACE BRIDGE HERE", "danger"), fallback: [crossing] };
    }
    case "RELIEF": {
      // A meaningful choice: the best previewed site for each recognised service piece.
      const choices = m.services.filter((o) => o.piece !== "bridge" && usable(o));
      const story = restored ? beat.line : "The crossing is still down. You can still restore it, or help the families you can reach.";
      const title = choices.length >= 2 ? `MISSION 2: ${names(choices.map((o) => PIECE_NAME[o.piece] ?? o.piece))}?` : "MISSION 2: DEPLOY A SERVICE";
      if (servicesPlaced.length) {
        const placed = servicesPlaced.map((s) => PIECE_NAME[s.piece]).join(" + ");
        return { ...base, title: `${placed} DEPLOYED`, story: "Watch the routes light up as people reach the service. Moving a piece updates the outcome.", step: "Hold on — the river is rising…", tone: "good" };
      }
      const focus: Focus[] = choices.map((o) => ({ kind: "service", option: o, label: PIECE_NAME[o.piece] ?? o.piece, detail: optionDetail(o), tone: "info" }));
      if (!restored && crossing) focus.push(...crossingFocus(moving ? "MOVE BRIDGE HERE" : "BRIDGE STILL NEEDED", "danger"));
      return {
        ...base,
        title,
        story,
        step: choices.length ? `CHOOSE ONE: ${names(choices.map((o) => PIECE_NAME[o.piece] ?? o.piece))} ON ITS GLOWING SITE` : "No service site can help right now.",
        tone: "info",
        focus,
        fallback: [...choices, ...(!restored && crossing ? [crossing] : [])],
      };
    }
    case "SURGE": {
      const story = clock.surge === "failed" ? `${FLOOD_UPDATE_UNAVAILABLE}. Your infrastructure is still being tested.` : m.stage >= 2 ? beat.line : "Floodwater is building upstream…";
      if (clock.surge !== "accepted" && clock.surge !== "failed") return { ...base, story, step: "Brace — watch which roads turn red.", tone: "danger" };
      // The remaining response: the best backend preview among pieces the camera can see.
      const candidates = [m.opportunity, ...m.services, ...(crossing ? [crossing] : [])].filter((o): o is MissionOption => !!o && usable(o) && !!o.helps && o.allowed);
      const opp = candidates.reduce<MissionOption | null>((best, o) => (!best || (o.score_gain ?? 0) > (best.score_gain ?? 0) ? o : best), null);
      if (!opp) return { ...base, title: "HOLD THE LINE", story, step: "No more pieces can help. Watch whether your decisions hold.", tone: "info" };
      const name = PIECE_NAME[opp.piece] ?? opp.piece;
      return {
        ...base,
        title: "MISSION 3: ONE LAST CHANCE",
        story,
        step: opp.piece === "bridge" ? (opp.move_token_id ? "MOVE THE BRIDGE TO THE GLOWING CROSSING" : "PLACE THE BRIDGE ON THE GLOWING CROSSING") : `PLACE THE ${name} ON THE GLOWING SITE`,
        tone: "danger",
        focus: [{ kind: "opportunity", option: opp, label: `${name} HERE`, detail: optionDetail(opp), tone: "good" }],
        fallback: [opp],
      };
    }
    case "RESULTS":
      return { ...base, step: "The flood settles. Press START for another run." };
  }
}
