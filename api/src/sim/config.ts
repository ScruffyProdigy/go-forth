/**
 * Tick settings.
 *
 * The battle runs at a fixed tick rate read from here rather than from a
 * constant buried in the loop: the rate is the unit every duration in the game
 * is expressed in, and a headless sim with no wall clock has nothing else to
 * measure time with.
 */

export interface SimConfig {
  /** Ticks per second. A whole number, so a second is a whole number of ticks. */
  tickRate: number;
  /** Backstop length. The design doc's battle phase is 60–90 s (§3.2). */
  maxBattleSeconds: number;
}

export const DEFAULT_SIM_CONFIG: SimConfig = { tickRate: 20, maxBattleSeconds: 90 };

export function validateSimConfig(config: SimConfig): void {
  if (!Number.isInteger(config.tickRate) || config.tickRate <= 0) {
    throw new Error(`tick rate must be a positive whole number, got ${config.tickRate}`);
  }
  if (!(config.maxBattleSeconds > 0)) {
    throw new Error(`battle length must be positive, got ${config.maxBattleSeconds}`);
  }
}

export function secondsPerTick(config: SimConfig): number {
  return 1 / config.tickRate;
}

/** The tick the loop stops at, so a battle always terminates. */
export function maxTicks(config: SimConfig): number {
  return Math.ceil(config.maxBattleSeconds * config.tickRate);
}

/**
 * Converts a duration in seconds into whole ticks.
 *
 * Durations are counted in ticks rather than decremented in seconds on purpose:
 * subtracting 0.05 twenty times does not reliably land on zero, and a cooldown
 * that sometimes takes an extra tick is a determinism bug waiting to happen.
 */
export function toTicks(seconds: number, config: SimConfig): number {
  return Math.max(1, Math.round(seconds * config.tickRate));
}
