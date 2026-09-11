import { describe, expect, it } from 'vitest';

import { THREE_ZONE_MAP } from './map.js';
import { createRng } from './rng.js';
import type { UnitType } from './units.js';
import { createWorld, type BattleSetup } from './world.js';

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

function setup(overrides: Partial<BattleSetup> = {}): BattleSetup {
  return {
    unitTypes: [adept, hound],
    armies: [
      {
        side: 'north',
        troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [{ typeId: 'cinder-hound' }] }],
      },
      {
        side: 'south',
        troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [{ typeId: 'cinder-hound' }] }],
      },
    ],
    ...overrides,
  };
}

function build(battleState: BattleSetup = setup()) {
  return createWorld(THREE_ZONE_MAP, battleState, createRng(1));
}

describe('createWorld', () => {
  it('starts at tick zero', () => {
    expect(build().tick).toBe(0);
  });

  it('opens both bases at full HP', () => {
    const world = build();

    expect(world.bases.north.hp).toBe(THREE_ZONE_MAP.bases.north.maxHp);
    expect(world.bases.south.hp).toBe(THREE_ZONE_MAP.bases.south.maxHp);
  });

  it('opens with no zone score on either side', () => {
    expect(build().zoneScore).toEqual({ north: 0, south: 0 });
  });
});

describe('the roster as a multiset', () => {
  it('instantiates a unit per copy, so duplicates are legal', () => {
    const world = build(
      setup({
        armies: [
          {
            side: 'north',
            troops: [
              {
                mages: [{ typeId: 'ember-adept', count: 3 }],
                summons: [{ typeId: 'cinder-hound', count: 4 }],
              },
            ],
          },
          { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
        ],
      }),
    );

    const north = world.units.filter((unit) => unit.side === 'north');
    expect(north.filter((unit) => unit.typeId === 'ember-adept')).toHaveLength(3);
    expect(north.filter((unit) => unit.typeId === 'cinder-hound')).toHaveLength(4);
  });

  it('assumes no army size — one unit a side is a legal battle', () => {
    const world = build(
      setup({
        armies: [
          { side: 'north', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
          { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
        ],
      }),
    );

    expect(world.units).toHaveLength(2);
  });

  it('assumes no army size — forty units a side is the same code path', () => {
    const many = {
      mages: [{ typeId: 'ember-adept', count: 6 }],
      summons: [{ typeId: 'cinder-hound', count: 14 }],
    };
    const world = build(
      setup({
        armies: [
          { side: 'north', troops: [many, many] },
          { side: 'south', troops: [many, many] },
        ],
      }),
    );

    expect(world.units).toHaveLength(80);
  });

  it('rejects a roster entry naming a card that is not in the catalog', () => {
    expect(() =>
      build(
        setup({
          armies: [
            { side: 'north', troops: [{ mages: [{ typeId: 'frost-adept' }], summons: [] }] },
            { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
          ],
        }),
      ),
    ).toThrow(/frost-adept/);
  });
});

describe('the unit and troop model', () => {
  it('gives every unit the stat block the sim reads', () => {
    const unit = build().units.find((candidate) => candidate.typeId === 'cinder-hound');

    expect(unit).toMatchObject({
      kind: 'summon',
      schools: ['fire'],
      hp: 90,
      maxHp: 90,
      damage: 12,
      range: 18,
      speed: 60,
    });
  });

  it('puts every unit in exactly one troop', () => {
    const world = build();

    for (const unit of world.units) {
      const owning = world.troops.filter(
        (troop) => troop.mageIds.includes(unit.id) || troop.summonIds.includes(unit.id),
      );
      expect(owning).toHaveLength(1);
      expect(owning[0].id).toBe(unit.troopId);
    }
  });

  it('lets a troop reach its mages and its summons separately', () => {
    const troop = build().troops[0];

    expect(troop.mageIds).toHaveLength(1);
    expect(troop.summonIds).toHaveLength(1);
  });

  it('gives every unit a unique id', () => {
    const world = build(
      setup({
        armies: [
          {
            side: 'north',
            troops: [
              { mages: [{ typeId: 'ember-adept', count: 2 }], summons: [] },
              { mages: [{ typeId: 'ember-adept', count: 2 }], summons: [] },
            ],
          },
          { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
        ],
      }),
    );

    expect(new Set(world.units.map((unit) => unit.id)).size).toBe(world.units.length);
  });

  it('rejects a summon no mage in its troop can support (§4.2)', () => {
    const stoneGuard: UnitType = { ...hound, id: 'stone-guard', schools: ['stone'] };

    expect(() =>
      build(
        setup({
          unitTypes: [adept, hound, stoneGuard],
          armies: [
            {
              side: 'north',
              troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [{ typeId: 'stone-guard' }] }],
            },
            { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
          ],
        }),
      ),
    ).toThrow(/support/i);
  });

  it('rejects a troop with no mage, which could hold nothing on the field', () => {
    expect(() =>
      build(
        setup({
          armies: [
            { side: 'north', troops: [{ mages: [], summons: [{ typeId: 'cinder-hound' }] }] },
            { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
          ],
        }),
      ),
    ).toThrow(/mage/i);
  });
});

describe('deployment', () => {
  it('places every unit inside its own side deployment strip', () => {
    const world = build(
      setup({
        armies: [
          {
            side: 'north',
            troops: [
              {
                mages: [{ typeId: 'ember-adept', count: 6 }],
                summons: [{ typeId: 'cinder-hound', count: 14 }],
              },
            ],
          },
          {
            side: 'south',
            troops: [
              {
                mages: [{ typeId: 'ember-adept', count: 6 }],
                summons: [{ typeId: 'cinder-hound', count: 14 }],
              },
            ],
          },
        ],
      }),
    );

    for (const unit of world.units) {
      const strip = THREE_ZONE_MAP.deployment[unit.side];
      expect(unit.position.y).toBeGreaterThanOrEqual(strip.lane.from);
      expect(unit.position.y).toBeLessThanOrEqual(strip.lane.to);
      expect(unit.position.x).toBeGreaterThanOrEqual(strip.extent.from);
      expect(unit.position.x).toBeLessThanOrEqual(strip.extent.to);
    }
  });

  it('does not stack two units on the same spot', () => {
    const world = build(
      setup({
        armies: [
          {
            side: 'north',
            troops: [{ mages: [{ typeId: 'ember-adept', count: 6 }], summons: [] }],
          },
          { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
        ],
      }),
    );

    const spots = world.units.map((unit) => `${unit.position.x},${unit.position.y}`);
    expect(new Set(spots).size).toBe(spots.length);
  });

  it('places the same army the same way for the same seed', () => {
    const a = createWorld(THREE_ZONE_MAP, setup(), createRng(77));
    const b = createWorld(THREE_ZONE_MAP, setup(), createRng(77));

    expect(a.units.map((unit) => unit.position)).toEqual(b.units.map((unit) => unit.position));
  });

  it('places it differently for a different seed', () => {
    const a = createWorld(THREE_ZONE_MAP, setup(), createRng(1));
    const b = createWorld(THREE_ZONE_MAP, setup(), createRng(2));

    expect(a.units.map((unit) => unit.position)).not.toEqual(b.units.map((unit) => unit.position));
  });
});
