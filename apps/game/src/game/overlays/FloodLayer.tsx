import { useId, useMemo } from "react";
import type { UV } from "../../types/contracts";
import type { ScenarioGeometry } from "../../types/scenario";
import type { Frame } from "../printFrame";
import { PALETTE } from "../palette";

// Floodwater from backend scenario geometry only: hazard_zones (flood footprints) or,
// when a bundle has none, flood_corridors (mapped river reaches near that stage's
// simulated closures). Each stage mounts once when the backend reports it, so the
// water visibly expands once per accepted stage; earlier stages are cut out of the
// newer stage's mask so only newly flooded water animates. The art never decides
// which roads are closed.

interface Shape {
  kind: "polygon" | "corridor";
  d: string;
  width: number;
  bounds: [number, number, number, number];
}

/** Chaikin corner cutting so raster-derived footprints read as drawn water, not stairs. */
export function smoothRing(ring: UV[], passes = 2): UV[] {
  let pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring;
  for (let p = 0; p < passes && pts.length >= 3; p++) {
    pts = pts.flatMap((a, i) => {
      const b = pts[(i + 1) % pts.length];
      return [
        [a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25] as UV,
        [a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75] as UV,
      ];
    });
  }
  return pts;
}

export function floodShapesByStage(scenario: ScenarioGeometry, frame: Frame): Map<number, Shape[]> {
  const out = new Map<number, Shape[]>();
  const add = (stage: number, s: Shape) => out.set(stage, [...(out.get(stage) ?? []), s]);
  const bounds = (pts: UV[], pad: number): Shape["bounds"] => {
    const q = pts.map(frame.pt);
    return [Math.min(...q.map((p) => p.x)) - pad, Math.min(...q.map((p) => p.y)) - pad, Math.max(...q.map((p) => p.x)) + pad, Math.max(...q.map((p) => p.y)) + pad];
  };
  for (const h of scenario.hazard_zones) {
    if (h.polygon.length >= 3) {
      const ring = smoothRing(h.polygon);
      add(h.stage, { kind: "polygon", d: frame.d(ring, true), width: 0, bounds: bounds(ring, 0) });
    }
  }
  for (const c of scenario.flood_corridors ?? []) {
    const width = c.width_uv * frame.scale;
    if (c.path.length >= 2) add(c.stage, { kind: "corridor", d: frame.d(c.path), width, bounds: bounds(c.path, width / 2) });
  }
  return out;
}

function ShapePaint({ shapes, color, grow = 0 }: { shapes: Shape[]; color: string; grow?: number }) {
  return (
    <>
      {shapes.map((s, i) =>
        s.kind === "polygon" ? (
          <path key={i} d={s.d} fill={grow ? "none" : color} stroke={grow ? color : "none"} strokeWidth={grow} strokeLinejoin="round" />
        ) : (
          <path key={i} d={s.d} fill="none" stroke={color} strokeWidth={s.width + grow} strokeLinecap="round" strokeLinejoin="round" />
        ),
      )}
    </>
  );
}

export function FloodLayer({ scenario, frame, stage, active }: { scenario: ScenarioGeometry; frame: Frame; stage: number; active: boolean }) {
  const id = `fl${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const byStage = useMemo(() => floodShapesByStage(scenario, frame), [scenario, frame]);
  const stages = active ? [...byStage.keys()].filter((s) => s >= 1 && s <= stage).sort((a, b) => a - b) : [];
  if (!stages.length) return null;
  return (
    <g className="layer-flood" aria-label="Simulated flood from scenario hazard geometry">
      <defs>
        <pattern id={`${id}-ripple`} width={34} height={12} patternUnits="userSpaceOnUse" patternTransform="rotate(-8)">
          <path d="M0 6 C6 2 11 2 17 6 C23 10 28 10 34 6" fill="none" stroke={PALETTE.foam} strokeWidth={1.6} opacity={0.75} />
        </pattern>
      </defs>
      {stages.map((s) => (
        <FloodStage key={s} id={`${id}-s${s}`} ripple={`${id}-ripple`} frame={frame} shapes={byStage.get(s)!} earlier={stages.filter((e) => e < s).flatMap((e) => byStage.get(e)!)} />
      ))}
    </g>
  );
}

function FloodStage({ id, ripple, frame, shapes, earlier }: { id: string; ripple: string; frame: Frame; shapes: Shape[]; earlier: Shape[] }) {
  const pad = 40;
  const x0 = Math.min(...shapes.map((s) => s.bounds[0])) - pad;
  const y0 = Math.min(...shapes.map((s) => s.bounds[1])) - pad;
  const x1 = Math.max(...shapes.map((s) => s.bounds[2])) + pad;
  const y1 = Math.max(...shapes.map((s) => s.bounds[3])) + pad;
  return (
    <g className="flood-stage">
      <defs>
        <mask id={`${id}-water`} maskUnits="userSpaceOnUse" x={0} y={0} width={frame.W} height={frame.H}>
          <rect width={frame.W} height={frame.H} fill="#000" />
          <ShapePaint shapes={shapes} color="#fff" />
          <ShapePaint shapes={earlier} color="#000" />
        </mask>
        <mask id={`${id}-rim`} maskUnits="userSpaceOnUse" x={0} y={0} width={frame.W} height={frame.H}>
          <rect width={frame.W} height={frame.H} fill="#fff" />
          <ShapePaint shapes={shapes} color="#000" />
          <ShapePaint shapes={earlier} color="#000" />
        </mask>
        <mask id={`${id}-edge`} maskUnits="userSpaceOnUse" x={0} y={0} width={frame.W} height={frame.H}>
          <rect width={frame.W} height={frame.H} fill="#000" />
          <ShapePaint shapes={shapes} color="#fff" grow={18} />
          <ShapePaint shapes={shapes} color="#000" />
          <ShapePaint shapes={earlier} color="#000" grow={18} />
        </mask>
        <clipPath id={`${id}-reveal`}>
          <rect className="flood-reveal" x={x0} y={y0} width={x1 - x0} height={y1 - y0} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-reveal)`}>
        {/* SOLID FLOOD FILL - covers the entire flooded area */}
        <g mask={`url(#${id}-water)`}>
          {/* Base solid blue - completely fills the flood zone */}
          <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="#0055bb" />
          {/* Lighter overlay for depth */}
          <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="#2288ff" opacity={0.5} />
          {/* Ripple pattern on top */}
          <g className="flood-drift">
            <rect x={x0 - 80} y={y0} width={x1 - x0 + 160} height={y1 - y0} fill={`url(#${ripple})`} />
          </g>
        </g>
        {/* Bright edge glow around flood boundary */}
        <g mask={`url(#${id}-rim)`} className="flood-lip">
          <ShapePaint shapes={shapes} color="#00ccff" grow={16} />
        </g>
      </g>
    </g>
  );
}
