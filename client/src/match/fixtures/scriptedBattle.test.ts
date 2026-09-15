import { describe, expect, it } from 'vitest';

import { starterMirrorRound1 } from '../../plan/fixtures/starterMirror.ts';
import type { PlanState } from '../../plan/types.ts';
import { THREE_ZONE_MAP, distance } from '../geometry.ts';
import type { LoadoutSpell } from '../types.ts';
import { MAX_TICKS, advance, applyCast, deploy, openingState, toSnapshot } from './scriptedBattle.ts';

const LOADOUT: LoadoutSpell[] = [
  { spellId: 'fireball', name: 'Fireball', cost: 3, effect: 'A burst.' },
  { spellId: 'expensive', name: 'Conflagration', cost: 99, effect: 'Too dear.' },
];

function allIn(plan: PlanState): PlanState {
  return { ...plan, troops: plan.troops.map((troop) => ({ ...troop, order: { kind: 'pushEnemyBase' } })) };
}

function runToEnd(state: ReturnType<typeof openingState>) {
  let current = state;
  // A hard bound rather than `while (ending === null)`: a fixture that never
  // ends should fail the test, not hang the suite.
  for (let step = 0; step < MAX_TICKS + 5 && current.ending === null; step += 1) {
    current = advance(current);
  }
  return current;
}

describe('deployment', () => {
  it('puts both armies in their own strip, summons ahead of their mage', () => {
    const units = deploy({ side: 'south', plan: starterMirrorRound1() });
    const strip = THREE_ZONE_MAP.deployment.south;

    expect(units.length).toBeGreaterThan(0);
    for (const unit of units) {
      expect(unit.position.y).toBeGreaterThanOrEqual(strip.start - 30);
      expect(unit.position.y).toBeLessThanOrEqual(strip.end);
    }

    const mage = units.find((unit) => unit.id === 'south-emberwright');
    const summon = units.find((unit) => unit.id.startsWith('south-emberwright-emberHound'));
    // South advances north, which is up the screen: ahead means a smaller y.
    expect(summon!.position.y).toBeLessThan(mage!.position.y);
  });

  it('is reproducible — the same plan lays out identically', () => {
    expect(deploy({ side: 'north', plan: starterMirrorRound1() })).toEqual(
      deploy({ side: 'north', plan: starterMirrorRound1() }),
    );
  });
});

describe('a battle', () => {
  it('runs the same way twice from the same opening', () => {
    const armies = [
      { side: 'south' as const, plan: starterMirrorRound1() },
      { side: 'north' as const, plan: starterMirrorRound1() },
    ];
    expect(runToEnd(openingState(armies))).toEqual(runToEnd(openingState(armies)));
  });

  it('ends on zone control when nobody breaks through', () => {
    const result = runToEnd(
      openingState([
        { side: 'south', plan: starterMirrorRound1() },
        { side: 'north', plan: starterMirrorRound1() },
      ]),
    );

    expect(result.ending).not.toBeNull();
    expect(result.ending!.kind).toBe('roundComplete');
    expect(result.baseHp.north.hp).toBe(THREE_ZONE_MAP.baseMaxHp);
    expect(result.baseHp.south.hp).toBe(THREE_ZONE_MAP.baseMaxHp);
  });

  it('ends the moment a base falls, and names the side that destroyed it', () => {
    const result = runToEnd(
      openingState([
        // The defender holds zones and keeps one troop home; the attacker sends
        // everything at the base. Both sides still have units when it lands, so
        // this is base destruction and not annihilation wearing its name.
        { side: 'south', plan: starterMirrorRound1() },
        { side: 'north', plan: allIn(starterMirrorRound1()) },
      ]),
    );

    expect(result.ending).toEqual({ kind: 'baseDestroyed', winner: 'north' });
    expect(result.baseHp.south.hp).toBe(0);
    expect(result.baseHp.north.hp).toBe(THREE_ZONE_MAP.baseMaxHp);
    expect(result.tick).toBeLessThan(MAX_TICKS);
    expect(result.units.some((unit) => unit.side === 'south')).toBe(true);
  });
});

describe('a cast', () => {
  const opening = openingState([
    { side: 'south', plan: starterMirrorRound1() },
    { side: 'north', plan: starterMirrorRound1() },
  ]);

  it('charges its resolved cost and records itself', () => {
    const { state, rejection } = applyCast(
      opening,
      'south',
      { commandId: 'c1', spellId: 'fireball', at: { x: 187, y: 300 }, tick: 0 },
      LOADOUT,
    );

    expect(rejection).toBeNull();
    expect(state.energy.south).toBe(opening.energy.south - 3);
    expect(state.casts).toHaveLength(1);
    expect(state.casts[0].commandId).toBe('c1');
  });

  it('only damages the other side', () => {
    const at = opening.units.find((unit) => unit.side === 'north')!.position;
    const { state } = applyCast(
      opening,
      'south',
      { commandId: 'c1', spellId: 'fireball', at, tick: 0 },
      LOADOUT,
    );

    const hurtSouth = state.units.filter(
      (unit) =>
        unit.side === 'south' &&
        unit.hp < opening.units.find((before) => before.id === unit.id)!.hp,
    );
    expect(hurtSouth).toEqual([]);

    const northNearby = opening.units.filter(
      (unit) => unit.side === 'north' && distance(unit.position, at) <= 60,
    );
    expect(northNearby.length).toBeGreaterThan(0);
    for (const near of northNearby) {
      expect(state.units.find((unit) => unit.id === near.id)!.hp).toBeLessThan(near.hp);
    }
  });

  it('is refused, and charges nothing, when the energy is not there', () => {
    const { state, rejection } = applyCast(
      opening,
      'south',
      { commandId: 'c1', spellId: 'expensive', at: { x: 187, y: 300 }, tick: 0 },
      LOADOUT,
    );

    expect(rejection).toBe('notEnoughEnergy');
    expect(state).toBe(opening);
  });

  it('is refused for a spell that is not in the loadout', () => {
    const { rejection } = applyCast(
      opening,
      'south',
      { commandId: 'c1', spellId: 'notTaken', at: { x: 187, y: 300 }, tick: 0 },
      LOADOUT,
    );
    expect(rejection).toBe('notEquipped');
  });

  it('is refused off the map', () => {
    const { rejection } = applyCast(
      opening,
      'south',
      { commandId: 'c1', spellId: 'fireball', at: { x: -5, y: 300 }, tick: 0 },
      LOADOUT,
    );
    expect(rejection).toBe('outOfBounds');
  });

  it('charges once for a command id already accepted', () => {
    const command = { commandId: 'c1', spellId: 'fireball', at: { x: 187, y: 300 }, tick: 0 };
    const once = applyCast(opening, 'south', command, LOADOUT).state;
    const twice = applyCast(once, 'south', command, LOADOUT).state;

    expect(twice.energy.south).toBe(once.energy.south);
    expect(twice.casts).toHaveLength(1);
  });
});

describe('the snapshot a client is given', () => {
  const state = openingState([
    { side: 'south', plan: starterMirrorRound1() },
    { side: 'north', plan: starterMirrorRound1() },
  ]);

  it('carries your energy and never the opponent’s', () => {
    const snapshot = toSnapshot(state, 'south', LOADOUT);
    expect(snapshot.energy).toBe(state.energy.south);
    expect(JSON.stringify(snapshot)).not.toContain('"north":{"hp"');
  });

  it('can be filtered to your own units, for the wait after lock-in', () => {
    const snapshot = toSnapshot(state, 'south', LOADOUT, THREE_ZONE_MAP, { onlyYourUnits: true });
    expect(snapshot.units.length).toBeGreaterThan(0);
    expect(snapshot.units.every((unit) => unit.side === 'south')).toBe(true);
  });
});
