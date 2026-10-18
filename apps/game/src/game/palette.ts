// Projection palette: a WHITE projection over the printed map. White light lets the
// print read through; game state is drawn in saturated ink colours on top of it.
//
//   blue  = floodwater         red   = cut off / blocked / affected
//   green = open route / access violet = camera checking a piece
//
// Camera safety: the legacy OpenCV bridge filter (floodshift- backend/perception/
// bridge_profile.json, inherited from sky e662b58) treats OpenCV hue 17–36 (34°–72°)
// at saturation ≥ 58/255 as a bridge candidate. No projected colour may fall in that
// window; palette tests enforce it. Re-test against the Perceptron classifier.

export const PALETTE = {
  paper: "#ffffff",
  ink: "#0f1b2d",
  inkSoft: "#46566b",
  inkFaint: "#8a96a6",
  rule: "#d5dbe3",
  // Water.
  water: "#2f7fe0",
  waterDeep: "#1a56a8",
  waterLip: "#0b3d91",
  foam: "#e6f1ff",
  // Danger / cut off / blocked.
  danger: "#d62839",
  dangerSoft: "#f6c9cf",
  // Open route / access restored.
  route: "#119a4b",
  routeSoft: "#c9f0d8",
  // Camera candidate.
  pending: "#6a4fd8",
  // Services (shape + colour, never colour alone).
  hospital: "#c2187a",
  shelter: "#0b8f86",
  food: "#e8590c",
  bridge: "#119a4b",
  highlight: "#1554c9",
  // Matsya / Boat of Hope "gold": amber at hue ~31° (below the 34° camera window) and a
  // pale gold whose saturation stays under the filter's 58/255 threshold.
  gold: "#cf7f2a",
  goldPale: "#efe3c4",
  cream: "#0f1b2d",
  text: "#0f1b2d",
  textDim: "#46566b",
} as const;

export type PaletteKey = keyof typeof PALETTE;

/** HSV of a #rrggbb colour: hue in degrees, saturation and value 0..1. */
export function hsv(hex: string): { h: number; s: number; v: number } {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return { h, s: max ? d / max : 0, v: max };
}

/** Matches the legacy bridge colour filter (hue 34°–72°, sat ≥ 58/255, val ≥ 59/255). */
export function looksLikeBridgeToCamera(hex: string): boolean {
  const { h, s, v } = hsv(hex);
  return h >= 34 && h <= 72 && s >= 58 / 255 && v >= 59 / 255;
}
