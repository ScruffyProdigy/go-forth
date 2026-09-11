import { describe, expect, it } from 'vitest';

import { DEFAULT_SIM_CONFIG } from './config.js';
import { THREE_ZONE_MAP } from './map.js';
import type { MapConfig } from './map.js';
import { runBattle } from './runBattle.js';
import { IDENTITY_MULTIPLIERS } from './schools.js';
import type { UnitType } from './units.js';
import type { BattleSetup } from './world.js';

const adept: UnitType = {
  id: 'ember-adept',
  kind: 'mage',
  schools: ['fire'],
  maxHp: 60,
  damage: 10,
  range: 90,
  speed: 30,
  attackCooldownSeconds: 1,
  supportCapacity: 2,
};

/** A mage that cannot fight back: it makes "one side is wiped out" easy to stage. */
const wisp: UnitType = {
  id: 'dying-wisp',
  kind: 'mage',
  schools: ['fire'],
  maxHp: 1,
  damage: 0,
  range: 0,
  speed: 0,
  attackCooldownSeconds: 1,
  supportCapacity: 1,
};

/**
 * A one-column map: both armies deploy in the same narrow lane, so a unit that
 * advances on the enemy base walks straight into the enemy rather than past it.
 * Engaging something that is not already in weapon range is slice B's job.
 */
const NARROW_MAP: MapConfig = {
  ...THREE_ZONE_MAP,
  id: 'test-lane',
  size: { width: 40, height: THREE_ZONE_MAP.size.height },
  zones: THREE_ZONE_MAP.zones.map((zone) => ({ ...zone, extent: { from: 0, to: 40 } })),
  bases: {
    north: { ...THREE_ZONE_MAP.bases.north, position: { x: 20, y: 20 } },
    south: { ...THREE_ZONE_MAP.bases.south, position: { x: 20, y: 549 } },
  },
  deployment: {
    north: { ...THREE_ZONE_MAP.deployment.north, extent: { from: 0, to: 40 } },
    south: { ...THREE_ZONE_MAP.deployment.south, extent: { from: 0, to: 40 } },
  },
};

const HUNTER_VS_WISP: BattleSetup = {
  unitTypes: [adept, wisp],
  armies: [
    { side: 'north', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [] }] },
    { side: 'south', troops: [{ mages: [{ typeId: 'dying-wisp' }], summons: [] }] },
  ],
};

const STANDOFF: BattleSetup = {
  unitTypes: [wisp],
  armies: [
    { side: 'north', troops: [{ mages: [{ typeId: 'dying-wisp' }], summons: [] }] },
    { side: 'south', troops: [{ mages: [{ typeId: 'dying-wisp' }], summons: [] }] },
  ],
};

describe('runBattle', () => {
  it('reports the opening state as tick zero', () => {
    const result = runBattle(NARROW_MAP, [], HUNTER_VS_WISP, 1);

    expect(result.ticks[0].tick).toBe(0);
    expect(result.ticks[0].events).toEqual([]);
    expect(result.ticks[0].state.units).toHaveLength(2);
  });

  it('reports state tick by tick, numbered in order', () => {
    const result = runBattle(THREE_ZONE_MAP, [], STANDOFF, 1, {
      tickRate: 20,
      maxBattleSeconds: 1,
    });

    expect(result.ticks.map((entry) => entry.tick)).toEqual(
      Array.from({ length: 21 }, (_unused, index) => index),
    );
  });

  it('snapshots each tick, so a later tick cannot rewrite an earlier one', () => {
    const result = runBattle(NARROW_MAP, [], HUNTER_VS_WISP, 1);
    const opening = result.ticks[0].state.units[0].position;

    expect(result.finalState.units[0].position).not.toEqual(opening);
  });

  it('stops once a side has been wiped out', () => {
    const result = runBattle(NARROW_MAP, [], HUNTER_VS_WISP, 1);

    expect(result.outcome).toBe('annihilation');
    expect(result.finalState.units.every((unit) => unit.side === 'north')).toBe(true);
  });

  it('stops at the configured battle length when both sides survive', () => {
    const result = runBattle(THREE_ZONE_MAP, [], STANDOFF, 1, {
      tickRate: 20,
      maxBattleSeconds: 1,
    });

    expect(result.outcome).toBe('timeUp');
    expect(result.finalState.tick).toBe(20);
  });

  it('reads the tick rate from config — half the rate is half the ticks', () => {
    const slow = runBattle(THREE_ZONE_MAP, [], STANDOFF, 1, { tickRate: 10, maxBattleSeconds: 1 });

    expect(slow.finalState.tick).toBe(10);
  });

  it('collects every event, each stamped with the tick it happened on', () => {
    const result = runBattle(NARROW_MAP, [], HUNTER_VS_WISP, 1);

    const defeats = result.events.filter((event) => event.type === 'unitDefeated');
    expect(defeats).toHaveLength(1);
    expect(defeats[0].tick).toBe(result.finalState.tick);
    expect(defeats[0].swing.unitsRemoved[0].typeId).toBe('dying-wisp');
  });

  it('files each event under the tick it was emitted on as well as in the stream', () => {
    const result = runBattle(NARROW_MAP, [], HUNTER_VS_WISP, 1);

    const fromTicks = result.ticks.flatMap((entry) => entry.events);
    expect(fromTicks).toEqual(result.events);
  });

  it('resolves the school multipliers once and hands them back', () => {
    const result = runBattle(NARROW_MAP, [], HUNTER_VS_WISP, 1);

    expect(result.multipliers.fire).toEqual(IDENTITY_MULTIPLIERS);
  });

  it('carries a school config override through to the battle it ran', () => {
    const result = runBattle(
      NARROW_MAP,
      [{ id: 'fire', multipliers: { energyGainMultiplier: 2 } }],
      HUNTER_VS_WISP,
      1,
    );

    expect(result.multipliers.fire.energyGainMultiplier).toBe(2);
  });

  it('defaults to the shipped sim config', () => {
    const result = runBattle(THREE_ZONE_MAP, [], STANDOFF, 1);

    expect(result.config).toEqual(DEFAULT_SIM_CONFIG);
  });

  it('carries the seed it ran on, so a result can be replayed', () => {
    expect(runBattle(NARROW_MAP, [], HUNTER_VS_WISP, 4242).seed).toBe(4242);
  });

  it('rejects a seed that is not an integer', () => {
    expect(() => runBattle(THREE_ZONE_MAP, [], STANDOFF, 1.5)).toThrow(/seed/i);
  });
});
