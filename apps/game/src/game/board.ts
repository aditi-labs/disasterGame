import type { UV } from "../types/contracts";

// Physical board registration the projector must respect (spec §9: "projector must
// mask/avoid marker areas so corner detection stays legible").
//
// These IDs/positions are the LEGACY TENTATIVE values from floodshift-
// backend/calibration/board.py (DICT_4X4_100, ids 10–13 at 0.04/0.96). They are NOT
// verified against the current physical board. Lane B (Dev 1) owns measuring the real
// printed markers; update docs/BOARD_REGISTRATION.md and this table together.

export interface BoardMarker {
  id: number;
  /** Marker centre in board UV (0,0 = printed-map top-left). */
  center: UV;
}

export const MARKER_PROVENANCE = "legacy board.py tentative ids 10–13 · UNVERIFIED on physical board";
export const MARKERS_VERIFIED = false;

export const BOARD_MARKERS: BoardMarker[] = [
  { id: 10, center: [0.04, 0.04] },
  { id: 11, center: [0.96, 0.04] },
  { id: 12, center: [0.96, 0.96] },
  { id: 13, center: [0.04, 0.96] },
];

/**
 * Half-width of the dark keep-out square around each marker, in board UV. Generous
 * on purpose: the printed marker size is not measured yet, and light spilling onto a
 * marker costs the camera its homography.
 */
export const MARKER_KEEPOUT_HALF_UV = 0.045;

/** True when a board point falls inside any marker keep-out (used to place HUD text). */
export function insideMarkerKeepout([u, v]: UV, pad = 0): boolean {
  const h = MARKER_KEEPOUT_HALF_UV + pad;
  return BOARD_MARKERS.some(({ center: [cu, cv] }) => Math.abs(u - cu) <= h && Math.abs(v - cv) <= h);
}
