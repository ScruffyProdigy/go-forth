import { describe, expect, it } from 'vitest';

import { DEFAULT_SIM_CONFIG, maxTicks, secondsPerTick, validateSimConfig } from './config.js';

describe('DEFAULT_SIM_CONFIG', () => {
  it('is valid', () => {
    expect(() => validateSimConfig(DEFAULT_SIM_CONFIG)).not.toThrow();
  });

  it('fixes a whole number of ticks per second', () => {
    expect(Number.isInteger(DEFAULT_SIM_CONFIG.tickRate)).toBe(true);
  });

  it('backstops a battle at the design doc length, 60-90 s', () => {
    expect(DEFAULT_SIM_CONFIG.maxBattleSeconds).toBeGreaterThanOrEqual(60);
  });
});

describe('secondsPerTick', () => {
  it('is the inverse of the configured tick rate', () => {
    expect(secondsPerTick({ tickRate: 20, maxBattleSeconds: 90 })).toBeCloseTo(0.05, 10);
  });
});

describe('maxTicks', () => {
  it('is the battle length in ticks, so the loop always terminates', () => {
    expect(maxTicks({ tickRate: 20, maxBattleSeconds: 90 })).toBe(1800);
  });
});

describe('validateSimConfig', () => {
  it('rejects a tick rate that is not a positive integer', () => {
    expect(() => validateSimConfig({ tickRate: 0, maxBattleSeconds: 90 })).toThrow(/tick rate/i);
    expect(() => validateSimConfig({ tickRate: 1.5, maxBattleSeconds: 90 })).toThrow(/tick rate/i);
  });

  it('rejects a battle with no length', () => {
    expect(() => validateSimConfig({ tickRate: 20, maxBattleSeconds: 0 })).toThrow(/length/i);
  });
});
