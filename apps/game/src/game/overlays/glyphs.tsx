import type { TokenType } from "../../types/contracts";
import { PALETTE } from "../palette";

// Projected piece emblems (spec §9): hospital cross with pearl glow, shelter roof /
// safe haven, food relief crate with leaf, bridge connection glyph. Each pairs a
// distinct shape with its colour so meaning never rests on colour alone.

export const PIECE_COLOR: Partial<Record<TokenType, string>> = {
  hospital: PALETTE.hospital,
  shelter: PALETTE.shelter,
  food_shelter: PALETTE.food,
  bridge: PALETTE.bridge,
};

/** Restrained Matsya engraving, used in the title margin rather than the mapped terrain. */
export function MatsyaMark({ size = 64 }: { size?: number }) {
  return (
    <g transform={"scale(" + size / 100 + ")"} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M-30 0 C-10 -23 21 -24 38 0 C21 24 -10 23 -30 0 L-48 -18 L-40 0 L-48 18 Z" />
      <path d="M23 -12 L30 -26 L33 -12 M-8 -17 Q-1 -29 9 -18 M-8 17 Q-1 29 9 18 M-21 -8 Q-1 -16 17 -9 M-23 0 Q-2 -7 17 0 M-21 8 Q-1 16 17 9 M22 -11 Q15 0 22 11" />
      <circle cx={29} cy={-2} r={1.2} fill="currentColor" stroke="none" />
      <path d="M-59 30 C-25 20 -10 39 19 30 S59 27 66 30 M-64 39 C-32 29 -12 47 18 39 S58 35 70 39" opacity={0.5} />
    </g>
  );
}

export function PieceGlyph({ type, size = 18, color }: { type: TokenType; size?: number; color?: string }) {
  const s = size / 2;
  const c = color ?? PIECE_COLOR[type] ?? PALETTE.text;
  const line = { stroke: c, strokeWidth: Math.max(1.4, size * 0.1), fill: "none", strokeLinejoin: "round" as const, strokeLinecap: "round" as const };
  switch (type) {
    case "hospital":
      return (
        <g>
          <path d={`M${-s * 0.32} ${-s} H${s * 0.32} V${-s * 0.32} H${s} V${s * 0.32} H${s * 0.32} V${s} H${-s * 0.32} V${s * 0.32} H${-s} V${-s * 0.32} H${-s * 0.32} Z`} {...line} />
        </g>
      );
    case "shelter":
      return (
        <g>
          <path d={`M${-s * 1.1} ${-s * 0.05} L0 ${-s} L${s * 1.1} ${-s * 0.05}`} {...line} />
          <path d={`M${-s * 0.75} ${-s * 0.3} V${s * 0.9} H${s * 0.75} V${-s * 0.3}`} {...line} />
          <path d={`M${-s * 0.22} ${s * 0.9} V${s * 0.3} H${s * 0.22} V${s * 0.9}`} {...line} />
        </g>
      );
    case "food_shelter":
      return (
        <g>
          <rect x={-s * 0.9} y={-s * 0.35} width={s * 1.8} height={s * 1.25} rx={s * 0.08} {...line} />
          <path d={`M${-s * 0.9} ${s * 0.25} H${s * 0.9} M0 ${-s * 0.35} V${s * 0.9}`} {...line} />
          <path d={`M${-s * 0.1} ${-s * 0.4} C${-s * 0.15} ${-s * 0.95} ${s * 0.45} ${-s * 1.1} ${s * 0.7} ${-s * 1.05} C${s * 0.65} ${-s * 0.65} ${s * 0.35} ${-s * 0.4} ${-s * 0.1} ${-s * 0.4} Z`} {...line} />
        </g>
      );
    case "bridge":
      return (
        <g>
          <path d={`M${-s * 1.3} ${s * 0.35} H${s * 1.3}`} {...line} />
          <path d={`M${-s * 1.3} ${-s * 0.35} H${s * 1.3}`} {...line} />
          <path d={`M${-s * 0.65} ${-s * 0.35} V${s * 0.35} M0 ${-s * 0.35} V${s * 0.35} M${s * 0.65} ${-s * 0.35} V${s * 0.35}`} {...line} strokeWidth={line.strokeWidth * 0.7} />
        </g>
      );
    default:
      return <circle r={s * 0.8} {...line} />;
  }
}

/** Inline HTML icon for operator buttons and legends. */
export function PieceIcon({ type, size = 16 }: { type: TokenType; size?: number }) {
  const box = size * 1.8;
  return (
    <svg width={box} height={box} viewBox={`${-box / 2} ${-box / 2} ${box} ${box}`} aria-hidden className="piece-icon">
      <PieceGlyph type={type} size={size} />
    </svg>
  );
}

/** Cluster of small pinpoints for one population record (spec: "cream pinpoints"). */
export function PopulationCluster({ color, r = 2.6 }: { color: string; r?: number }) {
  const pts: [number, number][] = [
    [0, 0],
    [-6, -3],
    [6, -3],
    [-4, 5],
    [4, 5],
    [0, -7],
  ];
  return (
    <g>
      {pts.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i === 0 ? r * 1.15 : r} fill={color} />
      ))}
    </g>
  );
}
