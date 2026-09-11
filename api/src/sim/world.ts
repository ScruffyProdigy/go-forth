/**
 * The world model, and how a battle's opening state is built from roster data.
 *
 * The roster is a **multiset** (design doc §4.1): "3× Ember Adept, 4× Cinder
 * Hound" is the normal shape, and nothing in the sim assumes an army size. Round
 * 1 fields three mages and round 4 fields most of the roster, so any code here
 * that hard-coded a count would be wrong by round 2.
 *
 * A troop is one or more mages plus the summons they support (§4.2). Support is
 * mandatory and local — a mage in another troop is too far away to help — so a
 * summon whose school no mage in *its own* troop supports is rejected at build
 * time rather than quietly standing on the field.
 *
 * Placement here is the flat "everyone into the strip" version. Formations
 * derived from orders are slice B (JQ-287); this is what it replaces.
 */
import type { MapConfig } from './map.js';
import { validateMapConfig } from './map.js';
import type { Rng, RngState } from './rng.js';
import type { School } from './schools.js';
import type { Side, TroopId, UnitId, UnitRef, Vec2 } from './types.js';
import { SIDES } from './types.js';
import { buildUnitTypeCatalog, type UnitKind, type UnitType, type UnitTypeCatalog } from './units.js';

/** One line of a roster: a card and how many copies of it. Omitting `count` means one. */
export interface RosterEntry {
  typeId: string;
  count?: number;
}

export interface TroopSetup {
  id?: string;
  mages: RosterEntry[];
  summons: RosterEntry[];
}

export interface ArmySetup {
  side: Side;
  troops: TroopSetup[];
}

/** Everything a battle needs to exist, as data. */
export interface BattleSetup {
  unitTypes: UnitType[];
  armies: ArmySetup[];
}

export interface Unit {
  readonly id: UnitId;
  readonly typeId: string;
  readonly kind: UnitKind;
  readonly schools: readonly School[];
  readonly side: Side;
  readonly troopId: TroopId;
  readonly maxHp: number;
  readonly damage: number;
  readonly range: number;
  /** Map units per second; the loop converts to per-tick. */
  readonly speed: number;
  readonly attackCooldownSeconds: number;
  hp: number;
  position: Vec2;
  /** Ticks still to wait before this unit can attack again. Counted in ticks, not seconds — see `toTicks`. */
  cooldownRemaining: number;
}

export interface Troop {
  readonly id: TroopId;
  readonly side: Side;
  /** Living mages. A troop whose last mage dies dissolves — slice D (§4.6). */
  mageIds: UnitId[];
  summonIds: UnitId[];
}

export interface BaseState {
  readonly maxHp: number;
  readonly position: Vec2;
  hp: number;
}

export interface World {
  tick: number;
  /** Serialisable: a snapshot fully determines every draw that follows it. */
  rngState: RngState;
  units: Unit[];
  troops: Troop[];
  bases: Record<Side, BaseState>;
  zoneScore: Record<Side, number>;
}

/** How a unit appears in the event stream. */
export function unitRef(unit: Unit): UnitRef {
  return { unitId: unit.id, troopId: unit.troopId, side: unit.side, typeId: unit.typeId };
}

/** Spacing between deployed units, in map units. Sprites are 18–28 px (JQ-243). */
const DEPLOY_SPACING = 24;
/** A unit of jitter, so placement reads as an army rather than a spreadsheet. */
const DEPLOY_JITTER = 1;

function expand(entries: readonly RosterEntry[], catalog: UnitTypeCatalog, kind: UnitKind): UnitType[] {
  const expanded: UnitType[] = [];

  for (const entry of entries) {
    const type = catalog[entry.typeId];
    if (!type) {
      throw new Error(`roster names ${entry.typeId}, which is not in the unit type catalog`);
    }
    if (type.kind !== kind) {
      throw new Error(`${entry.typeId} is a ${type.kind}, but the roster lists it as a ${kind}`);
    }
    const count = entry.count ?? 1;
    if (!Number.isInteger(count) || count < 1) {
      throw new Error(`roster entry ${entry.typeId} has a count of ${count}`);
    }
    for (let copy = 0; copy < count; copy += 1) {
      expanded.push(type);
    }
  }

  return expanded;
}

function assertOneArmyPerSide(armies: readonly ArmySetup[]): void {
  const seen = new Set<Side>();
  for (const army of armies) {
    if (seen.has(army.side)) {
      throw new Error(`two armies were given for ${army.side}`);
    }
    seen.add(army.side);
  }
  for (const side of SIDES) {
    if (!seen.has(side)) {
      throw new Error(`no army was given for ${side}`);
    }
  }
}

function assertSupported(mages: readonly UnitType[], summons: readonly UnitType[], troopId: TroopId): void {
  if (mages.length === 0) {
    throw new Error(`troop ${troopId} has no mage, so it could hold nothing on the field`);
  }

  const supported = new Set<School>(mages.flatMap((mage) => mage.schools));
  for (const summon of summons) {
    if (!summon.schools.some((school) => supported.has(school))) {
      throw new Error(
        `troop ${troopId} has no mage able to support ${summon.id} ` +
          `(${summon.schools.join('/')}); support is mandatory and local`,
      );
    }
  }
}

function instantiate(
  type: UnitType,
  id: UnitId,
  side: Side,
  troopId: TroopId,
  position: Vec2,
): Unit {
  return {
    id,
    typeId: type.id,
    kind: type.kind,
    schools: type.schools,
    side,
    troopId,
    maxHp: type.maxHp,
    damage: type.damage,
    range: type.range,
    speed: type.speed,
    attackCooldownSeconds: type.attackCooldownSeconds,
    hp: type.maxHp,
    position,
    cooldownRemaining: 0,
  };
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/**
 * Lays a side's units out in its deployment strip, filling columns before adding
 * a row — a row costs 21 px of the scarce portrait axis, a column 22 px of width
 * the map was not using (JQ-243).
 */
function deploymentSpot(map: MapConfig, side: Side, index: number, rng: Rng): Vec2 {
  const strip = map.deployment[side];
  const width = strip.extent.to - strip.extent.from;
  const columns = Math.max(1, Math.floor(width / DEPLOY_SPACING));
  const column = index % columns;
  const row = Math.floor(index / columns);

  const x = strip.extent.from + DEPLOY_SPACING / 2 + column * DEPLOY_SPACING;
  const jitter = (rng.nextFloat() * 2 - 1) * DEPLOY_JITTER;

  // Front rank nearest the zones; further ranks fall back toward the base.
  const depth = DEPLOY_SPACING / 2 + row * DEPLOY_SPACING;
  const y = side === 'north' ? strip.lane.to - depth : strip.lane.from + depth;

  return {
    x: clamp(x + jitter, strip.extent.from, strip.extent.to),
    y: clamp(y, strip.lane.from, strip.lane.to),
  };
}

/** Builds the opening state of a battle. Pure: the same inputs give the same world. */
export function createWorld(map: MapConfig, battleState: BattleSetup, rng: Rng): World {
  validateMapConfig(map);
  assertOneArmyPerSide(battleState.armies);

  const catalog = buildUnitTypeCatalog(battleState.unitTypes);
  const units: Unit[] = [];
  const troops: Troop[] = [];

  for (const army of battleState.armies) {
    let placed = 0;

    army.troops.forEach((troopSetup, troopIndex) => {
      const troopId = troopSetup.id ?? `${army.side}-t${troopIndex}`;
      const mageTypes = expand(troopSetup.mages, catalog, 'mage');
      const summonTypes = expand(troopSetup.summons, catalog, 'summon');
      assertSupported(mageTypes, summonTypes, troopId);

      const troop: Troop = { id: troopId, side: army.side, mageIds: [], summonIds: [] };

      [...mageTypes, ...summonTypes].forEach((type, memberIndex) => {
        const unitId = `${troopId}-u${memberIndex}`;
        const unit = instantiate(
          type,
          unitId,
          army.side,
          troopId,
          deploymentSpot(map, army.side, placed, rng),
        );
        placed += 1;

        units.push(unit);
        if (type.kind === 'mage') {
          troop.mageIds.push(unitId);
        } else {
          troop.summonIds.push(unitId);
        }
      });

      troops.push(troop);
    });
  }

  const duplicate = units.find((unit, index) => units.findIndex((other) => other.id === unit.id) !== index);
  if (duplicate) {
    throw new Error(`two units share the id ${duplicate.id}; troop ids must be unique`);
  }

  return {
    tick: 0,
    rngState: rng.state,
    units,
    troops,
    bases: {
      north: { maxHp: map.bases.north.maxHp, position: map.bases.north.position, hp: map.bases.north.maxHp },
      south: { maxHp: map.bases.south.maxHp, position: map.bases.south.position, hp: map.bases.south.maxHp },
    },
    zoneScore: { north: 0, south: 0 },
  };
}
