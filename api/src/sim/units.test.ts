import { describe, expect, it } from 'vitest';

import { buildUnitTypeCatalog, type UnitType } from './units.js';

const adept: UnitType = {
  id: 'ember-adept',
  kind: 'mage',
  schools: ['fire'],
  maxHp: 60,
  damage: 8,
  range: 90,
  speed: 30,
  attackCooldownSeconds: 1.5,
  supportCapacity: 2,
  resummonPaceSeconds: 12,
};

const hound: UnitType = {
  id: 'cinder-hound',
  kind: 'summon',
  schools: ['fire'],
  maxHp: 90,
  damage: 12,
  range: 18,
  speed: 60,
  attackCooldownSeconds: 1,
};

describe('buildUnitTypeCatalog', () => {
  it('keys the catalog by unit type id', () => {
    const catalog = buildUnitTypeCatalog([adept, hound]);

    expect(catalog['cinder-hound'].damage).toBe(12);
  });

  it('accepts a dual-school card, which carries two schools', () => {
    const golem: UnitType = { ...hound, id: 'furnace-golem', schools: ['fire', 'artifice'] };

    expect(buildUnitTypeCatalog([golem])['furnace-golem'].schools).toEqual(['fire', 'artifice']);
  });

  it('rejects two types sharing an id', () => {
    expect(() => buildUnitTypeCatalog([hound, { ...hound, maxHp: 1 }])).toThrow(/twice/i);
  });

  it('rejects a unit belonging to no school', () => {
    expect(() => buildUnitTypeCatalog([{ ...hound, schools: [] }])).toThrow(/school/i);
  });

  it('rejects a unit with no HP', () => {
    expect(() => buildUnitTypeCatalog([{ ...hound, maxHp: 0 }])).toThrow(/maxHp/i);
  });

  it('rejects a negative attack range', () => {
    expect(() => buildUnitTypeCatalog([{ ...hound, range: -1 }])).toThrow(/range/i);
  });

  it('rejects an attack cooldown of zero, which would fire every tick', () => {
    expect(() => buildUnitTypeCatalog([{ ...hound, attackCooldownSeconds: 0 }])).toThrow(
      /cooldown/i,
    );
  });

  it('rejects a mage with no support capacity, which could hold no summons', () => {
    expect(() => buildUnitTypeCatalog([{ ...adept, supportCapacity: undefined }])).toThrow(
      /support capacity/i,
    );
  });
});
