// Four restrained local cues (spec §9 "Sound"): bell, accepted chime, surge swell,
// ending chord. Synthesised with WebAudio, so there is no external audio and nothing
// autoplays: the context is created on the operator's first click (START GAME).
// Any failure is silent. Operator laptop only; the projector never plays sound.

export type SoundCue = "bell" | "chime" | "swell" | "chord";

const MUTE_KEY = "floodshift.game.muted";
let ctx: AudioContext | null = null;

export function isMuted(): boolean {
  try {
    return sessionStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setMuted(muted: boolean) {
  try {
    sessionStorage.setItem(MUTE_KEY, muted ? "1" : "0");
  } catch {
    /* private window: mute lasts for this page only */
  }
}

/** Call from a user gesture so later cues are allowed to sound. */
export function unlockAudio() {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
  } catch {
    ctx = null;
  }
}

function tone(freq: number, start: number, dur: number, gain: number, type: OscillatorType = "sine") {
  if (!ctx) return;
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  amp.gain.setValueAtTime(0, start);
  amp.gain.linearRampToValueAtTime(gain, start + 0.02);
  amp.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(amp).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + dur + 0.05);
}

export function play(cue: SoundCue) {
  if (isMuted() || !ctx || ctx.state !== "running") return;
  try {
    const t = ctx.currentTime;
    switch (cue) {
      case "bell":
        tone(196, t, 2.4, 0.18);
        tone(392, t, 1.6, 0.06);
        break;
      case "chime":
        tone(660, t, 0.6, 0.09);
        tone(990, t + 0.08, 0.5, 0.05);
        break;
      case "swell": {
        if (!ctx) return;
        const osc = ctx.createOscillator();
        const amp = ctx.createGain();
        osc.type = "triangle";
        osc.frequency.setValueAtTime(70, t);
        osc.frequency.linearRampToValueAtTime(110, t + 1.6);
        amp.gain.setValueAtTime(0, t);
        amp.gain.linearRampToValueAtTime(0.16, t + 0.9);
        amp.gain.exponentialRampToValueAtTime(0.0001, t + 2.2);
        osc.connect(amp).connect(ctx.destination);
        osc.start(t);
        osc.stop(t + 2.3);
        break;
      }
      case "chord":
        for (const [f, d] of [
          [220, 0],
          [277.18, 0.06],
          [329.63, 0.12],
        ] as const)
          tone(f, t + d, 2.8, 0.07);
        break;
    }
  } catch {
    /* silent by design */
  }
}
