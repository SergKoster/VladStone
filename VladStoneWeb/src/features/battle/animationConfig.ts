export type AnimationSpeed = "slow" | "normal" | "fast" | "off";

export const SPEED_OPTIONS: { id: AnimationSpeed; label: string }[] = [
  { id: "slow", label: "Медленно" },
  { id: "normal", label: "Норм" },
  { id: "fast", label: "Быстро" },
  { id: "off", label: "Без анимаций" },
];

const SPEED_FACTOR: Record<AnimationSpeed, number> = {
  slow: 1.8,
  normal: 1,
  fast: 0.55,
  off: 0,
};

// Base durations at "normal" speed, in ms, keyed by combat event type.
// Tuned a touch slower so micro-steps read clearly.
const BASE_DURATION: Record<string, number> = {
  spawn: 360,
  move: 500,
  push: 500,
  death: 520,
  move_blocked: 220,
  spawn_blocked: 220,
  match_finished: 0,
  default: 340,
};

// One melee strike: a fast, sharp jump onto the target, a brief impact, then an
// eased return — all driven by a single CSS keyframe (see unit-strike).
const STRIKE_BASE = 640;
// Fraction of the strike at which the attacker is on the target (impact moment).
export const STRIKE_IMPACT = 0.42;

// Extra pause inserted after each animated micro-step so turns are easy to follow.
const INTER_STEP_PAUSE = 280;

// Hard cap on "no animation progress": if no event advances for this long, the
// battle watchdog force-finishes the turn. Generously above the longest single
// event (slow strike ~1.2s + pause) so it only catches genuine hangs.
export const ANIMATION_WATCHDOG_MS = 10_000;

const STORAGE_KEY = "vladstone:animation-speed";

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Total on-screen duration for one event, scaled by the chosen speed. */
export function durationFor(eventType: string, speed: AnimationSpeed): number {
  const factor = SPEED_FACTOR[speed];
  if (factor === 0) {
    return 0;
  }
  const base = BASE_DURATION[eventType] ?? BASE_DURATION.default;
  return Math.round(base * factor);
}

function scale(base: number, speed: AnimationSpeed): number {
  const factor = SPEED_FACTOR[speed];
  return factor === 0 ? 0 : Math.round(base * factor);
}

/** Total duration of a single melee strike (jump in, impact, return). */
export function strikeFor(speed: AnimationSpeed): number {
  return scale(STRIKE_BASE, speed);
}

/** Pause inserted between animated micro-steps. */
export function pauseFor(speed: AnimationSpeed): number {
  return scale(INTER_STEP_PAUSE, speed);
}

/** CSS timing lengths handed to the unit layer for the glide and the strike. */
export function layerTimings(speed: AnimationSpeed): { moveMs: number; strikeMs: number } {
  return {
    moveMs: durationFor("move", speed),
    strikeMs: strikeFor(speed),
  };
}

export function loadSpeed(): AnimationSpeed {
  if (typeof window === "undefined") {
    return "normal";
  }
  const stored = window.localStorage?.getItem(STORAGE_KEY) as AnimationSpeed | null;
  if (stored && stored in SPEED_FACTOR) {
    return stored;
  }
  return prefersReducedMotion() ? "off" : "normal";
}

export function saveSpeed(speed: AnimationSpeed): void {
  try {
    window.localStorage?.setItem(STORAGE_KEY, speed);
  } catch {
    // Ignore storage failures (private mode, disabled storage).
  }
}
