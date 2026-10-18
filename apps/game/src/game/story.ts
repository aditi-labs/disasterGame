import type { TokenType } from "../types/contracts";
import type { GamePhase } from "./clock";

// Copy strings and beat structure (spec §9 "The full 75-second story"). Nothing here
// holds a scenario value: counts, routes and outcomes always come from snapshots.

export const TITLE = "FLOODSHIFT";
export const SUBTITLE = "THE LAST CROSSING";
export const IDLE_LINE = "Ready to respond";
export const INTRO_LINE = "The flood was once a story of survival. Today, the choices are yours.";

export interface Beat {
  phase: GamePhase;
  /** Seconds of mission time this beat covers (null outside the clock). */
  window: [number, number] | null;
  headline: string;
  line: string;
  /** Pieces this beat asks for; pads of these kinds are highlighted when valid. */
  pieces: TokenType[];
  /** Short objective cue for the board's top edge. */
  objective: string | null;
}

export const BEATS: Record<GamePhase, Beat> = {
  IDLE: { phase: "IDLE", window: null, headline: `${TITLE} / ${SUBTITLE}`, line: IDLE_LINE, pieces: [], objective: null },
  INTRO: { phase: "INTRO", window: null, headline: "", line: INTRO_LINE, pieces: [], objective: null },
  WARNING: {
    phase: "WARNING",
    window: [0, 10],
    headline: "FLASH FLOOD WARNING",
    line: "Communities are losing access to safety.",
    pieces: [],
    objective: "RESTORE THE CROSSING",
  },
  CROSSING: {
    phase: "CROSSING",
    window: [10, 30],
    headline: "MISSION 01 — THE LAST CROSSING",
    line: "Reconnect the isolated community.",
    pieces: ["bridge"],
    objective: "PLACE THE BRIDGE ON A LIT CROSSING",
  },
  RELIEF: {
    phase: "RELIEF",
    window: [30, 50],
    headline: "MISSION 02 — THE PEOPLE",
    line: "Food, refuge, and care are running out.",
    pieces: ["shelter", "hospital", "food_shelter"],
    objective: "PLACE SHELTER OR HOSPITAL ON A LIT SITE",
  },
  SURGE: {
    phase: "SURGE",
    window: [50, 70],
    headline: "MISSION 03 — THE SURGE",
    line: "Another road may be lost. Act now.",
    pieces: ["bridge", "shelter", "hospital", "food_shelter"],
    objective: null,
  },
  RESULTS: {
    phase: "RESULTS",
    window: [70, 75],
    headline: "THE FLOOD SETTLES",
    line: "Your actions shaped the outcome.",
    pieces: [],
    objective: null,
  },
};

/** The game's physical inventory (no person or START piece: spec §2, §9 before-play). */
export const GAME_PIECES: TokenType[] = ["bridge", "shelter", "hospital", "food_shelter"];

export const PIECE_NAME: Partial<Record<TokenType, string>> = {
  bridge: "BRIDGE",
  shelter: "SHELTER",
  hospital: "HOSPITAL",
  food_shelter: "FOOD STATION",
};

/** Label shown beside a piece the backend accepted and reports as serving. */
export const ACTIVE_LABEL: Partial<Record<TokenType, string>> = {
  bridge: "BRIDGE CONNECTED",
  shelter: "SHELTER ACTIVE",
  hospital: "HOSPITAL ACTIVE",
  food_shelter: "FOOD STATION ACTIVE",
};

export const FLOOD_UPDATE_UNAVAILABLE = "FLOOD UPDATE UNAVAILABLE";
export const LIVE_DATA_UNAVAILABLE = "LIVE DATA UNAVAILABLE";
export const CONNECTION_LOST = "CONNECTION LOST";
export const RESPONSE_COMPLETE = "RESPONSE COMPLETE";

// Player-facing rejection copy (spec §9 "Invalid placement"). Codes are the ones
// backend/world/rules.py and service.py actually emit; anything unmapped is shown
// as its own words rather than guessed into a category.
const REJECTION_COPY: Record<string, string> = {
  crossing_already_open: "CROSSING UNAVAILABLE",
  flood_closure_not_restorable: "CROSSING UNAVAILABLE",
  invalid_crossing: "CROSSING UNAVAILABLE",
  site_exposed: "FLOOD RISK",
  site_in_flood_footprint: "FLOOD RISK",
  site_occupied: "SITE OCCUPIED",
  outside_site: "MOVE CLOSER",
  invalid_site: "NOT A SITE FOR THIS PIECE",
  site_not_approved: "SITE NOT APPROVED",
  resource_exhausted: "NO PIECE LEFT",
  insufficient_budget: "NOT ENOUGH BUDGET",
  no_supply_route: "NO SUPPLY ROUTE",
  start_first: "MISSION NOT STARTED",
  already_started: "ALREADY STARTED",
  stale_version: "WORLD CHANGED — TRY AGAIN",
  duplicate: "ALREADY APPLIED",
  token_already_placed: "PIECE ALREADY PLACED",
  unknown_token: "PIECE NOT ON BOARD",
  start_is_latched: "START STAYS UNTIL RESET",
  last_stage: "NO FURTHER FLOOD STAGE",
  piece_class_changed_remove_first: "LIFT PIECE AND RETRY",
  camera_registration_required: "CAMERA ALIGNMENT REQUIRED",
  camera_status_stale: "CAMERA CONNECTION LOST",
  mission_input_closed: "INPUT PAUSED",
  no_suggestion: "NO VALID SUGGESTION",
};

export function rejectionCopy(reason?: string | null): string {
  if (!reason) return "NOT ACCEPTED";
  return REJECTION_COPY[reason] ?? reason.replace(/_/g, " ").toUpperCase();
}
