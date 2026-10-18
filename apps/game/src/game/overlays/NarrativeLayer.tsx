import type { MatsyaGuidance } from "../guide";
import type { BoatOfHope } from "../narrative";
import { PALETTE } from "../palette";
import type { Frame } from "../printFrame";

// Mythic narrative layer: Matsya's Guidance and the Boat of Hope. Both are drawn from
// backend state only (ghost_suggestion; measured outcomes vs. the no-response baseline)
// and carry no numbers of their own. The projector can hide this layer (key N) without
// touching any simulation visual.
//
// "Gold" here is amber below the camera's legacy bridge hue window (34°–72°) plus a
// low-saturation pale gold, so the glow never looks like a bridge piece to OpenCV.

/** A small swimming fish: the Matsya avatar used by the guidance marker. */
function Fish({ size = 1 }: { size?: number }) {
  return (
    <g transform={`scale(${size})`} className="matsya-fish">
      <path d="M-26 0 C-12 -14 12 -15 24 0 C12 15 -12 14 -26 0 Z" fill={PALETTE.goldPale} stroke={PALETTE.gold} strokeWidth={2.4} strokeLinejoin="round" />
      <path d="M-24 0 L-38 -11 L-33 0 L-38 11 Z" fill={PALETTE.gold} />
      <path d="M-6 -9 Q0 -1 -6 9 M4 -10 Q10 -1 4 10" fill="none" stroke={PALETTE.gold} strokeWidth={1.6} strokeLinecap="round" />
      <circle cx={15} cy={-2} r={2.2} fill={PALETTE.ink} />
    </g>
  );
}

/** Matsya's Guidance: a golden fish circling the backend-recommended site. */
export function MatsyaGuide({ frame, guidance, compact }: { frame: Frame; guidance: MatsyaGuidance; compact: boolean }) {
  const c = frame.pt(guidance.suggestion.board_uv);
  const r = 66;
  const orbit = `M${r} 0 A${r} ${r} 0 1 1 ${-r} 0 A${r} ${r} 0 1 1 ${r} 0`;
  return (
    <g className="layer-matsya" transform={`translate(${c.x} ${c.y})`} pointerEvents="none" aria-label={guidance.title}>
      <circle r={r + 18} className="matsya-glow" />
      <circle r={r} className="matsya-ripple" />
      <circle r={r} className="matsya-ripple matsya-ripple-2" />
      <g>
        <Fish size={0.9} />
        <animateMotion dur="5s" repeatCount="indefinite" rotate="auto" path={orbit} />
      </g>
      {!compact && (
        <g transform={`translate(0 ${-r - 40})`}>
          <rect x={-170} y={-34} width={340} height={64} rx={32} className="matsya-pill" />
          <text y={-8} className="matsya-title">{guidance.title}</text>
          <text y={18} className="matsya-hint">{guidance.hint}</text>
        </g>
      )}
    </g>
  );
}

const LANTERNS: Record<string, [number, number]> = { life: [-22, -30], family: [0, -44], knowledge: [22, -30] };

/** The Boat of Hope: three lanterns (life, family, knowledge) that brighten with real outcomes. */
export function BoatOfHopeMark({ boat, scale = 1 }: { boat: BoatOfHope; scale?: number }) {
  return (
    <g className="boat-of-hope" transform={`scale(${scale})`} aria-label="Boat of Hope">
      <ellipse cx={0} cy={-12} rx={70} ry={52} fill={PALETTE.goldPale} opacity={0.15 + boat.glow * 0.7} className="boat-halo" />
      <path d="M-52 22 Q-34 30 0 30 Q34 30 52 22" fill="none" stroke={PALETTE.water} strokeWidth={2} opacity={0.6} className="boat-ripple" />
      <path d="M-60 32 Q-30 40 0 40 Q30 40 60 32" fill="none" stroke={PALETTE.water} strokeWidth={1.4} opacity={0.4} className="boat-ripple boat-ripple-2" />
      <path d="M-44 4 L44 4 L32 20 L-32 20 Z" fill={PALETTE.paper} stroke={PALETTE.ink} strokeWidth={2.4} strokeLinejoin="round" />
      <path d="M0 4 V-52" stroke={PALETTE.ink} strokeWidth={2} />
      <path d="M2 -50 L30 -6 L2 -6 Z" fill={PALETTE.paper} stroke={PALETTE.ink} strokeWidth={1.8} strokeLinejoin="round" />
      <path d="M-34 -14 Q-22 -20 -10 -14 M10 -14 Q22 -20 34 -14" fill="none" stroke={PALETTE.inkFaint} strokeWidth={1.2} />
      {boat.lanterns.map((l) => {
        const [x, y] = LANTERNS[l.id];
        return (
          <g key={l.id} transform={`translate(${x} ${y})`}>
            <circle r={13} fill={PALETTE.goldPale} opacity={l.light * 0.9} className={l.light > 0 ? "lantern-glow" : undefined} />
            <circle r={6} fill={l.light > 0 ? PALETTE.gold : PALETTE.paper} fillOpacity={0.25 + l.light * 0.75} stroke={PALETTE.gold} strokeWidth={1.6} />
          </g>
        );
      })}
    </g>
  );
}
