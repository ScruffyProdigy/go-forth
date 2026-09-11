import { describe, expect, it } from 'vitest';

import { createRng, rngFromState } from './rng.js';

describe('createRng', () => {
  it('produces the same sequence for the same seed', () => {
    const a = createRng(12345);
    const b = createRng(12345);

    const fromA = [a.nextUint32(), a.nextUint32(), a.nextUint32()];
    const fromB = [b.nextUint32(), b.nextUint32(), b.nextUint32()];

    expect(fromA).toEqual(fromB);
  });

  it('produces a different sequence for a different seed', () => {
    const a = createRng(1);
    const b = createRng(2);

    expect(a.nextUint32()).not.toBe(b.nextUint32());
  });

  it('yields floats in [0, 1)', () => {
    const rng = createRng(99);

    for (let i = 0; i < 200; i += 1) {
      const value = rng.nextFloat();
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
  });

  it('yields integers below the exclusive bound', () => {
    const rng = createRng(7);

    for (let i = 0; i < 200; i += 1) {
      const value = rng.nextInt(6);
      expect(Number.isInteger(value)).toBe(true);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(6);
    }
  });

  it('does not return the same value on every draw', () => {
    const rng = createRng(4);
    const draws = new Set(Array.from({ length: 50 }, () => rng.nextUint32()));

    expect(draws.size).toBeGreaterThan(1);
  });
});

describe('rngFromState', () => {
  it('resumes the sequence a captured state left off at', () => {
    const original = createRng(2024);
    original.nextUint32();
    original.nextUint32();

    const resumed = rngFromState(original.state);

    expect(resumed.nextUint32()).toBe(original.nextUint32());
  });

  it('exposes a state that is a plain serialisable integer', () => {
    const rng = createRng(31);
    rng.nextUint32();

    expect(Number.isInteger(rng.state)).toBe(true);
    expect(JSON.parse(JSON.stringify({ state: rng.state })).state).toBe(rng.state);
  });
});
