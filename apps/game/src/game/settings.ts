// Gameplay settings that must not pull in API configuration (config.ts reads endpoints at import).
/**
 * Physical pieces the camera + Perceptron can recognise reliably (reference photos exist
 * for these in assets/piece_references). The guide only asks players to place these.
 * Set VITE_SHELTER_PIECE=1 once the shelter piece is verified on the board.
 */
export const RECOGNIZED_PIECES: readonly string[] = ["bridge", "hospital", "food_shelter", ...((import.meta.env.VITE_SHELTER_PIECE as string | undefined) === "1" ? ["shelter"] : [])];

/** Seconds into Mission 1 without a restored crossing before Matsya's Guidance is requested. */
export const MATSYA_DELAY_MS = 8000;
