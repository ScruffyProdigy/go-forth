import { describe, expect, it } from 'vitest';

import { DEFAULT_SIM_CONFIG } from './config.js';
import { createTickContext } from './context.js';
import { TICK_PHASES } from './phases.js';
import { THREE_ZONE_MAP } from './map.js';
import { createRng } from './rng.js';
import { resolveSchoolMultipliers } from './schools.js';
import type { UnitType } from './units.js';
import { createWorld, type BattleSetup, type Unit, type World } from './world.js';

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

const hound: UnitType = {
  id: 'cinder-hound',
  kind: 'summon',
  schools: ['fire'],
  maxHp: 40,
  damage: 20,
  range: 20,
  speed: 60,
  attackCooldownSeconds: 1,
};

const DUEL: BattleSetup = {
  unitTypes: [adept, hound],
  armies: [
    { side: 'north', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [{ typeId: 'cinder-hound' }] }] },
    { side: 'south', troops: [{ mages: [{ typeId: 'ember-adept' }], summons: [{ typeId: 'cinder-hound' }] }] },
  ],
};

function context() {
  return createTickContext({
    config: DEFAULT_SIM_CONFIG,
    map: THREE_ZONE_MAP,
    multipliers: resolveSchoolMultipliers([]),
    rng: createRng(5),
  });
}

function duel(): World {
  return createWorld(THREE_ZONE_MAP, DUEL, createRng(5));
}

function unitOf(world: World, side: 'north' | 'south', typeId: string): Unit {
  const unit = world.units.find((candidate) => candidate.side === side && candidate.typeId === typeId);
  if (!unit) throw new Error(`no ${side} ${typeId}`);
  return unit;
}

function phase(name: string) {
  const found = TICK_PHASES.find((candidate) => candidate.name === name);
  if (!found) throw new Error(`no phase called ${name}`);
  return found;
}

describe('the phase order', () => {
  it('is declared in one place, so a later slice adds a phase instead of editing the loop', () => {
    expect(TICK_PHASES.map((tickPhase) => tickPhase.name)).toEqual(['movement', 'combat', 'removal']);
  });

  it('runs combat after movement, so a unit that closed this tick can swing this tick', () => {
    const names = TICK_PHASES.map((tickPhase) => tickPhase.name);

    expect(names.indexOf('combat')).toBeGreaterThan(names.indexOf('movement'));
  });

  it('sweeps the dead last, so a defeated unit cannot act after it fell', () => {
    const names = TICK_PHASES.map((tickPhase) => tickPhase.name);

    expect(names.indexOf('removal')).toBe(names.length - 1);
  });
});

describe('movement', () => {
  it('advances a unit toward the enemy base', () => {
    const world = duel();
    const ctx = context();
    const hunter = unitOf(world, 'north', 'cinder-hound');
    const before = hunter.position.y;

    phase('movement').run(world, ctx);

    expect(hunter.position.y).toBeGreaterThan(before);
  });

  it('advances by speed times the tick length, not by a whole second', () => {
    const world = duel();
    const ctx = context();
    const hunter = unitOf(world, 'north', 'cinder-hound');
    const before = hunter.position;

    phase('movement').run(world, ctx);

    const travelled = Math.hypot(hunter.position.x - before.x, hunter.position.y - before.y);
    expect(travelled).toBeCloseTo(hunter.speed / DEFAULT_SIM_CONFIG.tickRate, 6);
  });

  it('stops at weapon range rather than overlapping the enemy (JQ-243)', () => {
    const world = duel();
    const ctx = context();
    const north = unitOf(world, 'north', 'cinder-hound');
    const south = unitOf(world, 'south', 'cinder-hound');
    north.position = { x: 100, y: 300 };
    south.position = { x: 100, y: 300 + north.range };

    phase('movement').run(world, ctx);

    expect(north.position).toEqual({ x: 100, y: 300 });
  });
});

describe('combat', () => {
  function engaged(): { world: World; attacker: Unit; defender: Unit } {
    const world = duel();
    const attacker = unitOf(world, 'north', 'cinder-hound');
    const defender = unitOf(world, 'south', 'cinder-hound');
    for (const unit of world.units) {
      unit.position = { x: -1000, y: -1000 };
    }
    attacker.position = { x: 100, y: 300 };
    defender.position = { x: 100, y: 310 };
    return { world, attacker, defender };
  }

  it('damages an enemy inside range', () => {
    const { world, defender } = engaged();

    phase('combat').run(world, context());

    expect(defender.hp).toBe(defender.maxHp - 20);
  });

  it('leaves an enemy outside range alone', () => {
    const { world, attacker, defender } = engaged();
    defender.position = { x: 100, y: 300 + attacker.range + 1 };

    phase('combat').run(world, context());

    expect(defender.hp).toBe(defender.maxHp);
  });

  it('waits out the cooldown before swinging again', () => {
    const { world, defender } = engaged();
    const ctx = context();

    phase('combat').run(world, ctx);
    phase('combat').run(world, ctx);

    expect(defender.hp).toBe(defender.maxHp - 20);
  });

  it('swings again once the cooldown has run down', () => {
    const { world, defender } = engaged();
    const ctx = context();
    const ticksPerCooldown = DEFAULT_SIM_CONFIG.tickRate;

    for (let tick = 0; tick <= ticksPerCooldown; tick += 1) {
      phase('combat').run(world, ctx);
    }

    expect(defender.hp).toBe(defender.maxHp - 40);
  });

  it('emits unitDefeated when a unit is brought to zero', () => {
    const { world, defender } = engaged();
    const ctx = context();
    defender.hp = 5;

    phase('combat').run(world, ctx);

    const events = ctx.emitter.events.filter((event) => event.type === 'unitDefeated');
    expect(events).toHaveLength(1);
    expect(events[0].swing.unitsRemoved[0].unitId).toBe(defender.id);
  });

  it('names the killer on the defeat it caused', () => {
    const { world, attacker, defender } = engaged();
    const ctx = context();
    defender.hp = 5;

    phase('combat').run(world, ctx);

    expect(ctx.emitter.events[0].actors.source?.unitId).toBe(attacker.id);
  });

  it('does not let a unit already at zero swing back', () => {
    const { world, attacker, defender } = engaged();
    const ctx = context();
    attacker.hp = 0;

    phase('combat').run(world, ctx);

    expect(defender.hp).toBe(defender.maxHp);
  });
});

describe('removal', () => {
  it('takes a unit at zero HP off the field', () => {
    const world = duel();
    const fallen = unitOf(world, 'south', 'cinder-hound');
    fallen.hp = 0;

    phase('removal').run(world, context());

    expect(world.units.map((unit) => unit.id)).not.toContain(fallen.id);
  });

  it('takes it out of its troop, so the troop no longer counts it', () => {
    const world = duel();
    const fallen = unitOf(world, 'south', 'cinder-hound');
    fallen.hp = 0;

    phase('removal').run(world, context());

    const troop = world.troops.find((candidate) => candidate.id === fallen.troopId);
    expect(troop?.summonIds).not.toContain(fallen.id);
  });

  it('leaves the living alone', () => {
    const world = duel();
    const before = world.units.length;

    phase('removal').run(world, context());

    expect(world.units).toHaveLength(before);
  });
});
