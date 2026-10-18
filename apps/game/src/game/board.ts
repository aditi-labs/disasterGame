import type { UV } from "../types/contracts";
import registration from "../../../../perception/board_registration.json";

// Physical board registration the projector must respect (spec §9: "projector must
// mask/avoid marker areas so corner detection stays legible").
//
// Lane B's registration is the shared source for marker IDs and print-frame estimates.
// The landscape print and square world use DIFFERENT frames. These positions must
// never be treated as measured world UV or used to accept physical actions.

export interface BoardMarker {
  id: number;
  /** Marker centre in PRINT UV, not world UV. Positions remain photo estimates. */
  center: UV;
}

export const MARKER_PROVENANCE = "Lane B photo: TL 10 / TR 11 / BR 13 / BL 12; centres and paper dimensions UNMEASURED";
export const MARKERS_VERIFIED = registration.status === "MEASURED" && registration.markers.every((m) => m.verified);
export const MARKER_LAYOUT_VERIFIED = registration.markers.every((m) => m.id_and_layout_verified);
/** No print-to-world transform has been supplied; projector keystone cannot replace it. */
export const PRINT_WORLD_ALIGNMENT_VERIFIED = false;
export const BOARD_REGISTRATION_REQUIRED = "BOARD REGISTRATION REQUIRED";
export const PRINT_WORLD_ALIGNMENT_NOTE = "The photographed print is landscape and differs from the square world extent. A measured print-to-world transform is required; physical projection is held. Press M on the projector for screen rehearsal.";

export const BOARD_MARKERS: BoardMarker[] = registration.markers.map((m) => ({ id: m.id, center: m.center_uv as UV }));

/**
 * Half-width of a provisional marker mask in print UV. Generous
 * on purpose: the printed marker size is not measured yet, and light spilling onto a
 * marker costs the camera its homography.
 */
export const MARKER_KEEPOUT_HALF_UV = 0.08;

/** True when a print-frame point falls inside a provisional marker keep-out. */
export function insideMarkerKeepout([u, v]: UV, pad = 0): boolean {
  const h = MARKER_KEEPOUT_HALF_UV + pad;
  return BOARD_MARKERS.some(({ center: [cu, cv] }) => Math.abs(u - cu) <= h && Math.abs(v - cv) <= h);
}
