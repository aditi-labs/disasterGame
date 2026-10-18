import type { TokenType } from "../types/contracts";
import type { GamePhase } from "./clock";

// Copy and beat structure for the 75-second mission. Nothing here holds a scenario
// value: names, counts, routes and outcomes always come from backend snapshots.
//
// Framing: the Matsya story. Manu protected a small fish; the fish grew, warned him of
// the coming deluge, and Manu's boat carried his family, the sages and the Vedas
// through the flood. Here the players are Manu: small, well-placed acts of care
// carry a community through the water.

export const TITLE = "FLOODSHIFT";
export const SUBTITLE = "THE LAST CROSSING";
export const IDLE_LINE = "Ready to respond";

export const MANU_STORY = [
  "Long ago, Manu saved a small fish.",
  "The fish, Matsya, warned him of the great flood.",
  "Manu's boat carried his family, the sages and the Vedas to safety.",
];
export const MANU_TODAY = "Today the waters rise again in Rasuwa, Nepal. Be Manu: protect the people before the flood takes the road.";

export const HOW_TO_PLAY = [
  "Watch the flood: red means cut off.",
  "Place the BRIDGE on the glowing crossing.",
  "Choose ONE service to deploy. Move it to change the outcome.",
  "Survive the surge with what you have left.",
];

export interface Beat {
  phase: GamePhase;
  /** Seconds of mission time this beat covers (null outside the clock). */
  window: [number, number] | null;
  chapter: string;
  name: string;
  /** Default lines; the guide replaces them with state-specific text. */
  headline: string;
  line: string;
  /** Pieces this beat asks for. */
  pieces: TokenType[];
}

export const BEATS: Record<GamePhase, Beat> = {
  IDLE: { phase: "IDLE", window: null, chapter: "", name: "", headline: `${TITLE} · ${SUBTITLE}`, line: IDLE_LINE, pieces: [] },
  INTRO: { phase: "INTRO", window: null, chapter: "", name: "", headline: "", line: MANU_TODAY, pieces: [] },
  WARNING: {
    phase: "WARNING", window: [0, 10], chapter: "I", name: "THE WARNING",
    headline: "FLASH FLOOD WARNING",
    line: "Flash floods have destroyed the main crossing.",
    pieces: [],
  },
  CROSSING: {
    phase: "CROSSING", window: [10, 30], chapter: "II", name: "THE CROSSING",
    headline: "MISSION 1: RESTORE THE CROSSING",
    line: "Place the bridge over the glowing crossing.",
    pieces: ["bridge"],
  },
  RELIEF: {
    phase: "RELIEF", window: [30, 50], chapter: "III", name: "THE REFUGE",
    headline: "MISSION 2: SHELTER OR HOSPITAL?",
    line: "The road is open, but families still need food, shelter, and medical care.",
    pieces: ["shelter", "hospital"],
  },
  SURGE: {
    phase: "SURGE", window: [50, 70], chapter: "IV", name: "THE SURGE",
    headline: "THE RIVER IS RISING AGAIN",
    line: "One of the evacuation roads is now impassable.",
    pieces: ["bridge", "shelter", "hospital", "food_shelter"],
  },
  RESULTS: {
    phase: "RESULTS", window: [70, 75], chapter: "V", name: "THE NEW DAWN",
    headline: "MISSION COMPLETE",
    line: "Your decisions changed the outcome.",
    pieces: [],
  },
};

/** The chapter strip along the bottom of the board. */
export const CHAPTERS: GamePhase[] = ["WARNING", "CROSSING", "RELIEF", "SURGE", "RESULTS"];

/** At this mission second the broken crossing is highlighted and Mission 1 is announced. */
export const MISSION1_REVEAL_MS = 8000;

/** The game's physical inventory (no person or START piece). */
export const GAME_PIECES: TokenType[] = ["bridge", "shelter", "hospital", "food_shelter"];

export const PIECE_NAME: Partial<Record<TokenType, string>> = {
  bridge: "BRIDGE",
  shelter: "SHELTER",
  hospital: "HOSPITAL",
  food_shelter: "FOOD STATION",
};

/** What each piece gives people, in plain words. */
export const PIECE_PURPOSE: Partial<Record<TokenType, string>> = {
  bridge: "reconnects a cut-off village",
  shelter: "refuge for displaced residents",
  hospital: "medical care",
  food_shelter: "food and water",
};

/** Label shown beside a piece the backend accepted and reports as serving. */
export const ACTIVE_LABEL: Partial<Record<TokenType, string>> = {
  bridge: "BRIDGE CONNECTED",
  shelter: "SHELTER OPEN",
  hospital: "HOSPITAL OPEN",
  food_shelter: "FOOD STATION OPEN",
};

export const FLOOD_UPDATE_UNAVAILABLE = "FLOOD UPDATE UNAVAILABLE";
export const LIVE_DATA_UNAVAILABLE = "LIVE DATA UNAVAILABLE";
export const CONNECTION_LOST = "CONNECTION LOST";
export const RESPONSE_COMPLETE = "MISSION COMPLETE";

// Player-facing rejection copy. Codes are the ones backend/world/rules.py, service.py and
// physical.py actually emit; anything unmapped is shown as its own words.
const REJECTION_COPY: Record<string, string> = {
  crossing_already_open: "THIS CROSSING IS ALREADY OPEN",
  flood_closure_not_restorable: "TOO MUCH WATER HERE — TRY ANOTHER CROSSING",
  invalid_crossing: "NOT A CROSSING",
  site_exposed: "FLOOD RISK — CHOOSE ANOTHER SITE",
  site_in_flood_footprint: "UNDER WATER — CHOOSE ANOTHER SITE",
  site_occupied: "SITE ALREADY IN USE",
  outside_site: "MOVE CLOSER TO A HIGHLIGHTED SITE",
  invalid_site: "THIS PIECE DOES NOT GO HERE",
  site_not_approved: "SITE NOT APPROVED",
  resource_exhausted: "THAT PIECE IS ALREADY ON THE MAP",
  insufficient_budget: "NOT ENOUGH RESOURCES LEFT",
  no_supply_route: "NO SUPPLY ROUTE TO THIS SITE",
  start_first: "PRESS START FIRST",
  already_started: "ALREADY STARTED",
  stale_version: "MAP CHANGED — PLACE AGAIN",
  duplicate: "ALREADY APPLIED",
  token_already_placed: "PIECE ALREADY PLACED",
  unknown_token: "PIECE NOT ON THE MAP",
  start_is_latched: "START STAYS UNTIL RESET",
  last_stage: "NO FURTHER FLOOD STAGE",
  piece_class_changed_remove_first: "LIFT THE PIECE AND PLACE IT AGAIN",
  camera_registration_required: "CAMERA ALIGNING — HOLD STILL",
  board_registration_required: "BOARD ALIGNMENT REQUIRED",
  camera_status_stale: "CAMERA CONNECTION LOST",
  mission_input_closed: "WAIT FOR THE MISSION TO RUN",
  outside_board: "PLACE THE PIECE ON THE MAP",
  class_not_verified: "CHECKING PLACEMENT",
  detection_pending: "PIECE DETECTED",
  no_suggestion: "NO VALID SUGGESTION",
};

export function rejectionCopy(reason?: string | null): string {
  if (!reason) return "NOT ACCEPTED";
  return REJECTION_COPY[reason] ?? reason.replace(/_/g, " ").toUpperCase();
}

/** Piece-specific rejection copy: tells the player exactly what to do next. */
export function placementHint(piece: TokenType | null | undefined, reason?: string | null): string {
  const name = piece ? PIECE_NAME[piece] : undefined;
  if (reason === "outside_site" && name) return piece === "bridge" ? "MOVE BRIDGE CLOSER TO THE GLOWING CROSSING" : `MOVE ${name} CLOSER TO A HIGHLIGHTED SITE`;
  if (reason === "crossing_already_open") return "THIS CROSSING IS OPEN — USE THE GLOWING ONE";
  return rejectionCopy(reason);
}
