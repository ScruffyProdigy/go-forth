import { describe, expect, it } from 'vitest';

import {
  IDENTITY_MULTIPLIERS,
  SCHOOLS,
  resolveSchoolMultipliers,
  type SchoolConfig,
} from './schools.js';

describe('resolveSchoolMultipliers', () => {
  it('ships identity values for every school when nothing overrides them', () => {
    const table = resolveSchoolMultipliers([]);

    for (const school of SCHOOLS) {
      expect(table[school]).toEqual(IDENTITY_MULTIPLIERS);
    }
  });

  it('carries the three levers slices C and D trade through', () => {
    expect(IDENTITY_MULTIPLIERS).toEqual({
      energyGainMultiplier: 1,
      resummonPaceMultiplier: 1,
      statAxisMultiplier: 1,
    });
  });

  it('honours an override a school config supplies', () => {
    const configs: SchoolConfig[] = [{ id: 'fire', multipliers: { energyGainMultiplier: 1.5 } }];

    const table = resolveSchoolMultipliers(configs);

    expect(table.fire.energyGainMultiplier).toBe(1.5);
  });

  it('leaves the levers an override does not mention at identity', () => {
    const configs: SchoolConfig[] = [{ id: 'fire', multipliers: { energyGainMultiplier: 1.5 } }];

    const table = resolveSchoolMultipliers(configs);

    expect(table.fire.resummonPaceMultiplier).toBe(1);
    expect(table.fire.statAxisMultiplier).toBe(1);
  });

  it('leaves schools the configs never mention at identity', () => {
    const table = resolveSchoolMultipliers([{ id: 'fire', multipliers: { statAxisMultiplier: 2 } }]);

    expect(table.stone).toEqual(IDENTITY_MULTIPLIERS);
  });

  it('rejects a multiplier that is not a positive number', () => {
    const configs: SchoolConfig[] = [{ id: 'stone', multipliers: { statAxisMultiplier: 0 } }];

    expect(() => resolveSchoolMultipliers(configs)).toThrow(/positive/i);
  });

  it('rejects the same school being configured twice', () => {
    expect(() => resolveSchoolMultipliers([{ id: 'fire' }, { id: 'fire' }])).toThrow(/twice/i);
  });

  it('resolves once — the table cannot be rewritten mid-battle', () => {
    const table = resolveSchoolMultipliers([]);

    expect(() => {
      (table as Record<string, unknown>).fire = { energyGainMultiplier: 9 };
    }).toThrow();
    expect(() => {
      (table.fire as { energyGainMultiplier: number }).energyGainMultiplier = 9;
    }).toThrow();
  });
});
