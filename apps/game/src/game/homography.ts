// Projector-to-board registration (spec §8 "Coordinates / transforms"). The retained
// affine nudge (floodshift- ProjectionView `C`) composes with an optional four-corner
// correction for measured keystone; the result is one CSS matrix3d homography applied
// AFTER content is laid out in board space. Calibration never edits map geometry.

export type Pt = [number, number];

/** Normalized world-UV -> print-UV homography in an SVG's pixel coordinates. */
export function uvMatrix3d(m: number[], w: number, h: number): string {
  if (m.length !== 9 || !m.every(Number.isFinite)) throw new Error("Invalid measured mapping");
  const cols = [m[0], m[3]*h/w, 0, m[6]/w, m[1]*w/h, m[4], 0, m[7]/h,
    0, 0, 1, 0, m[2]*w, m[5]*h, 0, m[8]];
  return `matrix3d(${cols.join(",")})`;
}

export interface Calibration {
  dx: number;
  dy: number;
  sx: number;
  sy: number;
  rot: number;
  /** Per-corner pixel offsets TL, TR, BR, BL for keystone (all zero = pure affine). */
  corners: [Pt, Pt, Pt, Pt];
  /** Set when the operator confirmed this calibration against the printed board. */
  savedAt: string | null;
}

export const DEFAULT_CALIBRATION: Calibration = {
  dx: 0,
  dy: 0,
  sx: 1,
  sy: 1,
  rot: 0,
  corners: [
    [0, 0],
    [0, 0],
    [0, 0],
    [0, 0],
  ],
  savedAt: null,
};

/** Solve the 8 homography unknowns mapping src[i] -> dst[i] (Gaussian elimination). */
export function solveHomography(src: Pt[], dst: Pt[]): number[] {
  const A: number[][] = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i];
    const [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
  }
  for (let c = 0; c < 8; c++) {
    let p = c;
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]];
    if (Math.abs(A[c][c]) < 1e-12) throw new Error("degenerate calibration corners");
    for (let r = 0; r < 8; r++) {
      if (r === c) continue;
      const f = A[r][c] / A[c][c];
      for (let k = c; k < 9; k++) A[r][k] -= f * A[c][k];
    }
  }
  return A.map((row, i) => row[8] / row[i]);
}

export function applyHomography(h: number[], [x, y]: Pt): Pt {
  const w = h[6] * x + h[7] * y + 1;
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}

/** Where the calibration sends the stage corners TL, TR, BR, BL (stage size w×h px). */
export function targetCorners(c: Calibration, w: number, h: number): Pt[] {
  const cx = w / 2;
  const cy = h / 2;
  const a = (c.rot * Math.PI) / 180;
  const base: Pt[] = [
    [0, 0],
    [w, 0],
    [w, h],
    [0, h],
  ];
  return base.map(([x, y], i) => {
    const sx = (x - cx) * c.sx;
    const sy = (y - cy) * c.sy;
    return [cx + c.dx + sx * Math.cos(a) - sy * Math.sin(a) + c.corners[i][0], cy + c.dy + sx * Math.sin(a) + sy * Math.cos(a) + c.corners[i][1]];
  });
}

/** CSS matrix3d (column-major) for transform-origin 0 0 on a w×h element. */
export function calibrationMatrix3d(c: Calibration, w: number, h: number): string {
  const src: Pt[] = [
    [0, 0],
    [w, 0],
    [w, h],
    [0, h],
  ];
  const m = solveHomography(src, targetCorners(c, w, h));
  const cols = [m[0], m[3], 0, m[6], m[1], m[4], 0, m[7], 0, 0, 1, 0, m[2], m[5], 0, 1];
  return `matrix3d(${cols.map((v) => +v.toFixed(10)).join(",")})`;
}

export function isDefaultCalibration(c: Calibration): boolean {
  return c.dx === 0 && c.dy === 0 && c.sx === 1 && c.sy === 1 && c.rot === 0 && c.corners.every(([x, y]) => x === 0 && y === 0);
}
