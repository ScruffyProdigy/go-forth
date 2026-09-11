/**
 * The sim's only source of randomness.
 *
 * `Math.random` is banned everywhere under `sim/` (see `.eslintrc.cjs`): a
 * battle must replay identically from its seed, in this process and in a fresh
 * one, or the server cannot be the authority on what happened.
 *
 * The generator is mulberry32 — one 32-bit word of state, integer arithmetic
 * only, so the state serialises into a snapshot as a plain number and the
 * sequence resumes exactly where it left off.
 */

/** The generator's whole state: one signed 32-bit integer. */
export type RngState = number;

export interface Rng {
  /** The next draw, as an unsigned 32-bit integer. */
  nextUint32(): number;
  /** The next draw, scaled into `[0, 1)`. */
  nextFloat(): number;
  /** The next draw, as an integer in `[0, maxExclusive)`. */
  nextInt(maxExclusive: number): number;
  /** The state *after* every draw so far — resume it with `rngFromState`. */
  readonly state: RngState;
}

const TWO_POW_32 = 0x1_0000_0000;

/** Resumes a generator from a state captured off another one. */
export function rngFromState(state: RngState): Rng {
  let current = state | 0;

  const nextUint32 = (): number => {
    current = (current + 0x6d2b79f5) | 0;
    let t = Math.imul(current ^ (current >>> 15), 1 | current);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return (t ^ (t >>> 14)) >>> 0;
  };

  return {
    nextUint32,
    nextFloat: () => nextUint32() / TWO_POW_32,
    nextInt: (maxExclusive: number) => {
      if (!Number.isInteger(maxExclusive) || maxExclusive < 1) {
        throw new Error(`nextInt bound must be a positive integer, got ${maxExclusive}`);
      }
      return Math.floor((nextUint32() / TWO_POW_32) * maxExclusive);
    },
    get state() {
      return current;
    },
  };
}

/** Starts a generator from a battle seed. */
export function createRng(seed: number): Rng {
  if (!Number.isInteger(seed)) {
    throw new Error(`seed must be an integer, got ${seed}`);
  }
  return rngFromState(seed);
}
