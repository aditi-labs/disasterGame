import type { UV } from "../types/contracts";
import { applyHomography } from "./homography";

// The projection is laid out in PRINT space: the physical board is nepalmap.png printed
// full-bleed at 24 × 18 in, so print UV (0,0)–(1,1) is the artwork's own frame. World
// geometry (scenario board_uv) is carried into print space by the measured
// world→print matrix from /projection/registration (scripts/register_print_artwork.py).
// Projector keystone then only has to lay this frame onto the paper.

export const PRINT_W = 1600;
export const PRINT_H = 1200;

export interface Frame {
  W: number;
  H: number;
  /** True when world geometry uses the measured print mapping (not the square fallback). */
  aligned: boolean;
  /** World UV -> SVG units in print space. */
  pt: (uv: UV) => { x: number; y: number };
  /** Print UV -> SVG units. */
  printPt: (uv: UV) => { x: number; y: number };
  d: (path: UV[], closed?: boolean) => string;
  points: (path: UV[]) => string;
  /** SVG units per world UV unit (for widths given in world UV). */
  scale: number;
}

export function makeFrame(worldToPrint: number[] | null | undefined): Frame {
  const m = worldToPrint && worldToPrint.length === 9 && worldToPrint.every(Number.isFinite) ? worldToPrint.map((n) => n / worldToPrint[8]) : null;
  // Without a measured mapping, fit the square world into the print frame (screen preview only).
  const side = Math.min(PRINT_W, PRINT_H);
  const pt = m
    ? (uv: UV) => {
        const [u, v] = applyHomography(m, uv);
        return { x: u * PRINT_W, y: v * PRINT_H };
      }
    : (uv: UV) => ({ x: (PRINT_W - side) / 2 + uv[0] * side, y: (PRINT_H - side) / 2 + uv[1] * side });
  const a = pt([0, 0]);
  const b = pt([1, 0]);
  const c = pt([0, 1]);
  const scale = Math.sqrt(Math.hypot(b.x - a.x, b.y - a.y) * Math.hypot(c.x - a.x, c.y - a.y));
  const f = (n: number) => n.toFixed(1);
  return {
    W: PRINT_W,
    H: PRINT_H,
    aligned: !!m,
    pt,
    printPt: ([u, v]) => ({ x: u * PRINT_W, y: v * PRINT_H }),
    d: (path, closed = false) => {
      const s = path.map((p, i) => {
        const q = pt(p);
        return `${i ? "L" : "M"}${f(q.x)} ${f(q.y)}`;
      }).join(" ");
      return closed ? `${s} Z` : s;
    },
    points: (path) => path.map((p) => {
      const q = pt(p);
      return `${f(q.x)},${f(q.y)}`;
    }).join(" "),
    scale,
  };
}

/** Print UV rectangles kept free of game graphics (marker corners); text bands sit between them. */
export const SAFE = {
  top: { x: 0.14 * PRINT_W, y: 0.012 * PRINT_H, w: 0.72 * PRINT_W, h: 0.118 * PRINT_H },
  bottom: { x: 0.14 * PRINT_W, y: 0.872 * PRINT_H, w: 0.72 * PRINT_W, h: 0.116 * PRINT_H },
  toastY: 0.8 * PRINT_H,
} as const;

export function polylineLength(frame: Frame, path: UV[]): number {
  let n = 0;
  for (let i = 1; i < path.length; i++) {
    const a = frame.pt(path[i - 1]);
    const b = frame.pt(path[i]);
    n += Math.hypot(b.x - a.x, b.y - a.y);
  }
  return n;
}
