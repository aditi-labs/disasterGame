// Projection palette (spec §9 "Visual language"): dark, woodblock, minimal glow.
//
// Camera safety: the legacy OpenCV bridge filter (floodshift- backend/perception/
// bridge_profile.json, inherited from sky e662b58) treats OpenCV hue 17–36 (34°–72°)
// at saturation ≥ 58/255 as a bridge candidate. No projected colour may fall in that
// window; palette.test.ts enforces it. Re-test against the new lane C classifier.

export const PALETTE = {
  ink: "#05080c",
  vignette: "#000000",
  // Water: deep desaturated teal with engraved hatching; cyan lip only while advancing.
  waterDeep: "#0b2f36",
  water: "#17575f",
  waterMid: "#2b7d84",
  waterHatch: "#6fb7b8",
  waterLip: "#8ff4ff",
  foam: "#dff6f4",
  // Danger / flooded population: muted rose, never bright red.
  danger: "#c4485a",
  dangerHatch: "#e07a8a",
  // Blocked route: rust red dashed.
  blocked: "#b8492f",
  // Safe accessible route: seafoam mint.
  route: "#62d9ad",
  routeBright: "#d8fff0",
  // Pending camera candidate: dark blue / white pulse.
  pending: "#9db4ff",
  // Services.
  hospital: "#e9eef6", // pearl
  shelter: "#3fbf9b", // sea green
  food: "#ff7d6e", // coral relief crate (warm but below the camera's hue window)
  bridge: "#cfd9e4",
  ghost: "#a98bff", // violet
  cream: "#efe6d6", // population pinpoints (low saturation)
  text: "#e8edf2",
  textDim: "#93a1ae",
  pad: "#b9d7ff",
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
