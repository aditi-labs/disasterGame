import { useId, useMemo } from "react";
import type { UV } from "../../types/contracts";
import type { ScenarioGeometry } from "../../types/scenario";
import { BOARD_HEIGHT, BOARD_WIDTH, uvToPathD } from "../../types/geometry";
import { PALETTE } from "../palette";

// Woodblock flood, ported from floodshift- frontend/src/components/FloodLayer.tsx
// (sky 5524335/e662b58) and refined to the spec's water: deep desaturated teal with
// fine moving engraved hatching, and a bright cyan lip only while a stage advances.
//
// Placement comes only from backend scenario geometry: hazard_zones (flood
// footprints) or, when a bundle has none, flood_corridors (mapped river reaches near
// that stage's simulated closures). Each stage group mounts once when the backend
// reports that stage, so the entrance plays once per accepted stage; a reset (stage 0
// or phase ready) unmounts the water. The art never decides which roads are closed.

const TILE_W = 96;
const TILE_H = 48;

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

export function floodShapesByStage(scenario: ScenarioGeometry): Map<number, Shape[]> {
  const out = new Map<number, Shape[]>();
  const add = (stage: number, s: Shape) => out.set(stage, [...(out.get(stage) ?? []), s]);
  const bounds = (pts: UV[], pad: number): Shape["bounds"] => {
    const xs = pts.map(([u]) => u * BOARD_WIDTH);
    const ys = pts.map(([, v]) => v * BOARD_HEIGHT);
    return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
  };
  for (const h of scenario.hazard_zones) {
    if (h.polygon.length >= 3) {
      const ring = smoothRing(h.polygon);
      add(h.stage, { kind: "polygon", d: uvToPathD(ring, true), width: 0, bounds: bounds(ring, 0) });
    }
  }
  for (const c of scenario.flood_corridors ?? []) {
    const width = c.width_uv * BOARD_WIDTH;
    if (c.path.length >= 2) add(c.stage, { kind: "corridor", d: uvToPathD(c.path), width, bounds: bounds(c.path, width / 2) });
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

function WaterDefs({ id }: { id: string }) {
  // The inherited woodblock band tile, recoloured to teal, plus a fine engraved ripple.
  const band = (x0: number) =>
    `M${x0} 30 C${x0 + 10} 26 ${x0 + 18} 12 ${x0 + 30} 12 C${x0 + 40} 12 ${x0 + 44} 20 ${x0 + 38} 25 C${x0 + 34} 28 ${x0 + 29} 24 ${x0 + 32} 21 C${x0 + 36} 26 ${x0 + 42} 30 ${x0 + 48} 30`;
  return (
    <defs>
      <pattern id={`${id}-bands`} width={TILE_W} height={TILE_H} patternUnits="userSpaceOnUse" patternTransform="rotate(-9) scale(0.7)">
        <path d={`${band(0)} ${band(48).replace(/^M[^C]+/, "")} L${TILE_W} ${TILE_H} L0 ${TILE_H} Z`} fill={PALETTE.water} stroke={PALETTE.ink} strokeWidth={2} strokeLinejoin="round" />
        <path d="M6 33 C14 29 20 18 30 17 M54 33 C62 29 68 18 78 17" fill="none" stroke={PALETTE.waterMid} strokeWidth={1.8} strokeLinecap="round" />
        <path d="M22 14.5 C30 11 39 12 41 18 M70 14.5 C78 11 87 12 89 18" fill="none" stroke={PALETTE.waterHatch} strokeWidth={1.4} strokeLinecap="round" opacity={0.8} />
      </pattern>
      <pattern id={`${id}-engrave`} width={24} height={7} patternUnits="userSpaceOnUse" patternTransform="rotate(-6)">
        <path d="M0 3.5 C4 1.5 8 1.5 12 3.5 C16 5.5 20 5.5 24 3.5" fill="none" stroke={PALETTE.waterHatch} strokeWidth={0.7} opacity={0.55} />
      </pattern>
    </defs>
  );
}

export function FloodLayer({ scenario, stage, active }: { scenario: ScenarioGeometry; stage: number; active: boolean }) {
  const id = `fl${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const byStage = useMemo(() => floodShapesByStage(scenario), [scenario]);
  const inset = scenario.board?.control_inset_uv;
  const stages = active ? [...byStage.keys()].filter((s) => s >= 1 && s <= stage).sort((a, b) => a - b) : [];
  if (!stages.length) return null;
  return (
    <g className="layer-flood" aria-label="Simulated flood from scenario hazard geometry">
      <WaterDefs id={id} />
      {stages.map((s) => (
        <FloodStage key={s} id={`${id}-s${s}`} patterns={id} shapes={byStage.get(s)!} earlier={stages.filter((e) => e < s).flatMap((e) => byStage.get(e)!)} inset={inset} />
      ))}
    </g>
  );
}

function FloodStage({ id, patterns, shapes, earlier, inset }: { id: string; patterns: string; shapes: Shape[]; earlier: Shape[]; inset?: [number, number, number, number] }) {
  const pad = TILE_W;
  const x0 = Math.min(...shapes.map((s) => s.bounds[0])) - pad;
  const y0 = Math.min(...shapes.map((s) => s.bounds[1])) - pad;
  const x1 = Math.max(...shapes.map((s) => s.bounds[2])) + pad;
  const y1 = Math.max(...shapes.map((s) => s.bounds[3])) + pad;
  const insetRect = inset ? (
    <rect x={inset[0] * BOARD_WIDTH} y={inset[1] * BOARD_HEIGHT} width={(inset[2] - inset[0]) * BOARD_WIDTH} height={(inset[3] - inset[1]) * BOARD_HEIGHT} fill="#000" />
  ) : null;
  // Only newly inundated area animates: earlier stages are cut out of this stage's mask.
  const exclusions = (
    <>
      <ShapePaint shapes={earlier} color="#000" />
      {insetRect}
    </>
  );
  return (
    <g className="flood-stage">
      <defs>
        <mask id={`${id}-water`} maskUnits="userSpaceOnUse" x={0} y={0} width={BOARD_WIDTH} height={BOARD_HEIGHT}>
          <rect width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="#000" />
          <ShapePaint shapes={shapes} color="#fff" />
          {exclusions}
        </mask>
        <mask id={`${id}-rim`} maskUnits="userSpaceOnUse" x={0} y={0} width={BOARD_WIDTH} height={BOARD_HEIGHT}>
          <rect width={BOARD_WIDTH} height={BOARD_HEIGHT} fill="#fff" />
          {/* The lip is a boundary, not a bright fill over the whole river corridor. */}
          <ShapePaint shapes={shapes} color="#000" />
          {exclusions}
        </mask>
        <clipPath id={`${id}-reveal`}>
          <rect className="flood-reveal" x={x0} y={y0} width={x1 - x0} height={y1 - y0} />
        </clipPath>
      </defs>

      <g clipPath={`url(#${id}-reveal)`}>
        <g mask={`url(#${id}-water)`}>
          <rect x={x0 - TILE_W * 2} y={y0} width={x1 - x0 + TILE_W * 4} height={y1 - y0} fill={PALETTE.waterDeep} />
          <g className="flood-drift">
            <rect x={x0 - TILE_W * 2} y={y0} width={x1 - x0 + TILE_W * 4} height={y1 - y0} fill={`url(#${patterns}-bands)`} opacity={0.7} />
          </g>
          <g className="flood-engrave">
            <rect x={x0 - TILE_W * 2} y={y0} width={x1 - x0 + TILE_W * 4} height={y1 - y0} fill={`url(#${patterns}-engrave)`} />
          </g>
        </g>
        {/* Ink rim, then a brief bright cyan lip that settles while the stage arrives. */}
        <g mask={`url(#${id}-rim)`}>
          <ShapePaint shapes={shapes} color={PALETTE.ink} grow={6} />
          <g className="flood-lip">
            <ShapePaint shapes={shapes} color={PALETTE.waterLip} grow={2.4} />
          </g>
        </g>
      </g>
    </g>
  );
}
