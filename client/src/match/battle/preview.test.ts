import { describe, expect, it } from 'vitest';

import { TWO_LANE_MAP, targetRegions, zoneCentre, zoneGeometry } from '../geometry.ts';
import type { BattleSnapshot, BattleUnit, LoadoutSpell, MapPoint } from '../types.ts';
import { previewFor } from './preview.ts';

/**
 * The rule under test is JQ-312 AC 4, and it is a rule about *refusing* to say
 * things: never infer a clear from enemy count alone, never treat an unstated
 * fact as a convenient one, and label an estimate as an estimate. Most of these
 * therefore assert that a preview declined to claim something.
 */

const WEST = zoneGeometry(TWO_LANE_MAP, 'W');
const WEST_CENTRE = zoneCentre(WEST);

function enemy(id: string, at: MapPoint, hp: number, protection?: number): BattleUnit {
  return {
    id,
    kind: 'summon',
    side: 'north',
    typeName: 'Ember Hound',
    position: at,
    hp,
    maxHp: 60,
    ...(protection === undefined ? {} : { protection }),
  };
}

function snapshotOf(units: BattleUnit[], energy = 10): BattleSnapshot {
  return {
    tick: 100,
    units,
    zones: [
      { id: 'W', heldBy: null },
      { id: 'E', heldBy: null },
    ],
    zoneScore: { north: 0, south: 0 },
    energy,
    loadout: [],
    casts: [],
    events: [],
  };
}

const FIREBALL: LoadoutSpell = {
  spellId: 'fireball',
  name: 'Fireball',
  cost: 3,
  effect: 'A burst.',
  magnitude: 40,
  radius: 60,
};

function preview(units: BattleUnit[], spell = FIREBALL, extra: Partial<{ energy: number; stale: boolean; moving: boolean }> = {}) {
  const region = targetRegions('south', TWO_LANE_MAP).find((entry) => entry.zone === 'W')!;
  return previewFor(
    {
      snapshot: snapshotOf(units, extra.energy ?? 10),
      you: 'south',
      map: TWO_LANE_MAP,
      spell,
      stale: extra.stale ?? false,
      moving: extra.moving ?? false,
    },
    region,
  );
}

describe('an outcome preview', () => {
  it('offers no estimate at all until the spell has been resolved', () => {
    // JQ-297 has not landed, so the server has said nothing about what a
    // Fireball does. Guessing from the card text is the failure mode.
    const unresolved: LoadoutSpell = { spellId: 'f', name: 'Fireball', cost: 3, effect: 'A burst.' };

    const result = preview([enemy('a', WEST_CENTRE, 60, 0)], unresolved);

    expect(result.estimate).toBeNull();
    expect(result.confidence).toBe('unavailable');
    expect(result.summary).toMatch(/not resolved/i);
  });

  it('counts what would actually fall, not what is standing in the blast', () => {
    const result = preview([
      enemy('nearly-dead', WEST_CENTRE, 10, 0),
      enemy('healthy', WEST_CENTRE, 60, 0),
    ]);

    expect(result.estimate).toMatchObject({ inBlast: 2, defeated: 1, survivors: 1, unknown: 0 });
    expect(result.estimate?.clearsZone).toBe(false);
  });

  it('reads protection, so an armoured target is not assumed dead', () => {
    // 40 magnitude against 20 hp looks lethal until the 25 protection is read.
    const armoured = { ...enemy('armoured', WEST_CENTRE, 20), protection: 25 };

    expect(preview([armoured]).estimate).toMatchObject({ defeated: 0, survivors: 1 });
  });

  it('will not claim a clear from enemy count alone', () => {
    // Everything in the blast dies — but one of them has no stated protection,
    // so the sentence "this clears the lane" is not supportable.
    const result = preview([
      enemy('known', WEST_CENTRE, 10, 0),
      enemy('unstated', WEST_CENTRE, 10),
    ]);

    expect(result.estimate).toMatchObject({ defeated: 1, unknown: 1 });
    expect(result.estimate?.clearsZone).toBe(false);
    expect(result.summary).toMatch(/1 unknown/);
  });

  it('will not claim a clear while one of them is standing outside the blast', () => {
    const cornerOfTheLane = { x: WEST.extent.start + 5, y: WEST.lane.start + 5 };

    const result = preview([
      enemy('in-blast', WEST_CENTRE, 10, 0),
      enemy('in-lane-not-in-blast', cornerOfTheLane, 10, 0),
    ]);

    expect(result.estimate?.clearsZone).toBe(false);
  });

  it('claims a clear only when every living enemy in the lane is caught and falls', () => {
    const result = preview([
      enemy('a', WEST_CENTRE, 10, 0),
      enemy('b', { x: WEST_CENTRE.x + 10, y: WEST_CENTRE.y }, 10, 0),
    ]);

    expect(result.estimate?.clearsZone).toBe(true);
    expect(result.summary).toMatch(/Clears the lane/);
  });

  it('does not call an empty lane a clear', () => {
    const result = preview([enemy('elsewhere', { x: 300, y: 300 }, 10, 0)]);

    expect(result.estimate).toMatchObject({ inBlast: 0 });
    expect(result.estimate?.clearsZone).toBe(false);
    expect(result.summary).toMatch(/Nothing in range/);
  });

  it('labels the estimate when the board is moving', () => {
    const result = preview([enemy('a', WEST_CENTRE, 10, 0)], FIREBALL, { moving: true });

    expect(result.confidence).toBe('estimate');
    expect(result.summary).toMatch(/estimate/);
  });

  it('labels the estimate when the picture is known to be stale', () => {
    expect(preview([], FIREBALL, { stale: true }).confidence).toBe('estimate');
  });

  it('says what the energy is short by rather than only refusing', () => {
    const result = preview([enemy('a', WEST_CENTRE, 10, 0)], FIREBALL, { energy: 1.5 });

    expect(result.affordable).toBe(false);
    expect(result.shortfall).toBeCloseTo(1.5, 5);
  });

  it('ignores the dead — a corpse in the blast is not a kill', () => {
    const result = preview([enemy('already-gone', WEST_CENTRE, 0, 0)]);

    expect(result.estimate).toMatchObject({ inBlast: 0 });
  });
});
