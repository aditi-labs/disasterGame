// One place for the game's live-data configuration (spec §3 rule 6: secrets and
// endpoints come from the environment, never from committed code).

/** Retained FastAPI WorldService. */
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8010";

/**
 * The one locked scenario (spec §8 "Locked single scenario"). The server, the UI and
 * the integration tests must agree; a snapshot for any other id is treated as
 * LIVE DATA UNAVAILABLE rather than rendered.
 */
export const SCENARIO_ID = (import.meta.env.VITE_SCENARIO_ID as string | undefined) ?? "nepal_rasuwa_hot_v1";

