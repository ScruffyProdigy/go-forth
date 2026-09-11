import { describe, expect, it } from 'vitest';

import { placeholderBattle, PLACEHOLDER_UNIT_TYPES } from './fixtures.js';
import { THREE_ZONE_MAP } from './map.js';
import { runBattle } from './runBattle.js';
import { digestBattle, serializeBattle } from './serialize.js';

function run(seed: number) {
  return runBattle(THREE_ZONE_MAP, [], placeholderBattle(), seed);
}

describe('serializeBattle', () => {
  it('is stable — the same battle serialises to the same text', () => {
    expect(serializeBattle(run(7))).toBe(serializeBattle(run(7)));
  });

  it('opens with a header naming the seed and the outcome', () => {
    const header = JSON.parse(serializeBattle(run(7)).split('\n')[0]);

    expect(header).toMatchObject({ seed: 7, map: THREE_ZONE_MAP.id });
    expect(header.outcome).toBeDefined();
  });

  it('writes one line per event', () => {
    const result = run(7);
    const eventLines = serializeBattle(result)
      .split('\n')
      .filter((line) => line.includes('"event"'));

    expect(eventLines).toHaveLength(result.events.length);
  });

  it('closes with the surviving units, so state is compared as well as events', () => {
    const result = run(7);
    const last = JSON.parse(serializeBattle(result).split('\n').at(-1) ?? '{}');

    expect(last.finalUnits).toHaveLength(result.finalState.units.length);
  });

  it('lists the survivors in a stable order whatever order they died in', () => {
    const last = JSON.parse(serializeBattle(run(7)).split('\n').at(-1) ?? '{}');
    const ids = last.finalUnits.map((unit: { id: string }) => unit.id);

    expect(ids).toEqual([...ids].sort());
  });
});

describe('digestBattle', () => {
  it('matches for two runs on the same seed', () => {
    expect(digestBattle(run(7))).toBe(digestBattle(run(7)));
  });

  it('differs for a different seed', () => {
    expect(digestBattle(run(7))).not.toBe(digestBattle(run(8)));
  });
});

describe('the placeholder armies', () => {
  it('field the Fire mirror the design doc calls for in v1', () => {
    const battle = placeholderBattle();

    expect(battle.armies).toHaveLength(2);
    for (const army of battle.armies) {
      expect(army.troops.length).toBeGreaterThan(0);
    }
  });

  it('open the round at the starting mage cap of three (§4.3)', () => {
    for (const army of placeholderBattle().armies) {
      const mages = army.troops.flatMap((troop) => troop.mages);
      const total = mages.reduce((sum, entry) => sum + (entry.count ?? 1), 0);
      expect(total).toBe(3);
    }
  });

  it('are built from cards that pass catalog validation', () => {
    expect(PLACEHOLDER_UNIT_TYPES.length).toBeGreaterThan(0);
    expect(() => runBattle(THREE_ZONE_MAP, [], placeholderBattle(), 1)).not.toThrow();
  });
});
