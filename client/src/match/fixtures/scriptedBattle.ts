/**
 * A battle that behaves plausibly, so the client can be built before the server
 * can run one (JQ-311).
 *
 * This is emphatically **not** a sim. The sim is Python, server-authoritative and
 * deterministic (`api/app/sim/`), and it is the only thing allowed to decide what
 * happens in a battle. This is a fixture: it produces a stream of authoritative
 * *looking* snapshots so the screens, the cast round-trip, the recovery path and
 * the result states can be built and tested now. When JQ-309 lands a real
 * session, this file is deleted — not the screens that render its output.
 *
 * It is still pure and deterministic, for the same reason the sim is: a fixture
 * whose battle differs between two runs makes a failing screen test unfalsifiable.
 * No `Math.random`, no wall clock, no iteration over unordered collections.
 *
 * All numbers below are provisional demo tuning, recorded here rather than sent
 * for balance approval (JQ-311's 2026-09-12 scheduling note). They are chosen to
 * make a round *legible in about thirty seconds*, not to be fair.
 */

import type { Order, PlanState, ZoneId } from '../../plan/types.ts';
import {
  THREE_ZONE_MAP,
  type MapGeometry,
  distance,
  laneCentre,
  zoneAt,
} from '../geometry.ts';
import {
  type BaseHp,
  type BattleSnapshot,
  type BattleUnit,
  type CastCommand,
  type CastRejection,
  type LoadoutSpell,
  type MapPoint,
  type ResolvedCast,
  type RoundEnding,
  type Side,
  type ZoneState,
  opposing,
} from '../types.ts';

/* ------------------------------------------------------------- provisional -- */

/** The sim's rate (`SimConfig.tick_rate`), so a tick means the same thing here. */
export const TICK_RATE = 20;
const SECONDS_PER_TICK = 1 / TICK_RATE;

/**
 * 30 seconds. The design doc's battle is 60-90 s; the demo round is half of the
 * short end so a reviewer can watch a whole round without losing interest.
 */
export const MAX_TICKS = 30 * TICK_RATE;

const MAGE = { hp: 120, dps: 14, range: 42, speed: 26 };
const SUMMON = { hp: 60, dps: 10, range: 20, speed: 34 };
/**
 * Siege multiplier against a base, and how close a unit has to be to swing at
 * one. Both are tuned to a single observable: an all-in charge that gets through
 * should break a full-health base at around 18 seconds, with a few attackers
 * left. At 3x and a 38-unit reach it got the base to two thirds and died there,
 * which reads as "the charge failed" and never exercises the defeat screen.
 */
const BASE_DAMAGE_MULTIPLIER = 8;
const BASE_REACH = 70;

const ENERGY_START = 3;
const ENERGY_PER_SECOND = 0.35;
const ENERGY_CAP = 10;

/** A cast's blast. Generous, so its effect on the board is visible at a glance. */
const CAST_RADIUS = 60;
const CAST_DAMAGE = 45;

/* ------------------------------------------------------------------ state -- */

export interface ScriptedUnit {
  readonly id: string;
  readonly kind: 'mage' | 'summon';
  readonly side: Side;
  readonly typeName: string;
  readonly position: MapPoint;
  readonly hp: number;
  readonly maxHp: number;
  readonly dps: number;
  readonly range: number;
  /** Map units per second. */
  readonly speed: number;
  /** Where this unit's order sends it. */
  readonly destination: MapPoint;
  /**
   * True for a troop ordered at the enemy base.
   *
   * A pusher fights what it passes but never stops to; anything else closes on
   * the nearest enemy. That difference is the whole reason "push enemy base" is
   * a distinct order rather than a hold on the far zone — and without it an
   * all-in charge stalls in the midfield and the round ends in annihilation
   * instead of at the base, which is exactly what it must not do.
   */
  readonly pushing: boolean;
}

export interface ScriptedState {
  readonly tick: number;
  readonly units: readonly ScriptedUnit[];
  readonly zoneScore: Readonly<Record<Side, number>>;
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  readonly energy: Readonly<Record<Side, number>>;
  readonly casts: readonly ResolvedCast[];
  /** Set on the tick the round ends. Null while it is still running. */
  readonly ending: RoundEnding | null;
}

export interface ArmyPlan {
  readonly side: Side;
  readonly plan: PlanState;
}

/* --------------------------------------------------------------- opening -- */

function destinationFor(order: Order, side: Side, map: MapGeometry): MapPoint {
  const x = map.width / 2;
  if (order.kind === 'hold') {
    return { x, y: laneCentre(zoneLane(map, order.zone)) };
  }
  if (order.kind === 'defendBase') {
    const base = map.bases[side];
    return { x, y: base.y + (side === 'south' ? -50 : 50) };
  }
  return map.bases[opposing(side)];
}

function zoneLane(map: MapGeometry, zone: ZoneId) {
  const found = map.zones.find((candidate) => candidate.id === zone);
  if (!found) throw new Error(`no zone ${zone} on map`);
  return found.lane;
}

/**
 * Lays a plan out in its side's deployment strip.
 *
 * Placement is columns-first, one column per troop, summons ahead of the mage —
 * the same shape the plan screen draws, so the board a player locked in is the
 * board they then watch. JQ-287 owns derived formations for real; this only has
 * to not contradict it.
 */
export function deploy(army: ArmyPlan, map: MapGeometry = THREE_ZONE_MAP): ScriptedUnit[] {
  const strip = map.deployment[army.side];
  const forward = army.side === 'south' ? -1 : 1;
  const units: ScriptedUnit[] = [];

  army.plan.troops.forEach((troop, troopIndex) => {
    const mage = army.plan.roster.mages.find((candidate) => candidate.id === troop.mageId);
    if (!mage) return;

    const column = ((troopIndex + 0.5) / Math.max(1, army.plan.troops.length)) * map.width;
    const destination = destinationFor(troop.order, army.side, map);
    const pushing = troop.order.kind === 'pushEnemyBase';
    const mageY = army.side === 'south' ? strip.end - 16 : strip.start + 16;

    troop.summonIds.forEach((summonId, summonIndex) => {
      const summon = army.plan.roster.summons[summonId];
      const spread = (summonIndex - (troop.summonIds.length - 1) / 2) * 20;
      units.push({
        id: `${army.side}-${troop.mageId}-${summonId}-${summonIndex}`,
        kind: 'summon',
        side: army.side,
        typeName: summon?.name ?? summonId,
        position: { x: column + spread, y: mageY + forward * 26 },
        hp: SUMMON.hp,
        maxHp: SUMMON.hp,
        dps: SUMMON.dps,
        range: SUMMON.range,
        speed: SUMMON.speed,
        destination,
        pushing,
      });
    });

    units.push({
      id: `${army.side}-${troop.mageId}`,
      kind: 'mage',
      side: army.side,
      typeName: mage.name,
      position: { x: column, y: mageY },
      hp: MAGE.hp,
      maxHp: MAGE.hp,
      dps: MAGE.dps,
      range: MAGE.range,
      speed: MAGE.speed,
      destination,
      pushing,
    });
  });

  return units;
}

export function openingState(
  armies: readonly ArmyPlan[],
  map: MapGeometry = THREE_ZONE_MAP,
): ScriptedState {
  return {
    tick: 0,
    units: armies.flatMap((army) => deploy(army, map)),
    zoneScore: { north: 0, south: 0 },
    baseHp: {
      north: { hp: map.baseMaxHp, maxHp: map.baseMaxHp },
      south: { hp: map.baseMaxHp, maxHp: map.baseMaxHp },
    },
    energy: { north: ENERGY_START, south: ENERGY_START },
    casts: [],
    ending: null,
  };
}

/* ----------------------------------------------------------------- a tick -- */

function nearestEnemy(unit: ScriptedUnit, units: readonly ScriptedUnit[]): ScriptedUnit | null {
  let best: ScriptedUnit | null = null;
  let bestDistance = Infinity;
  // Index order, with a strict `<`, so ties resolve by position in the array and
  // never by iteration order. The Python sim lives by the same rule.
  for (const candidate of units) {
    if (candidate.side === unit.side || candidate.hp <= 0) continue;
    const gap = distance(unit.position, candidate.position);
    if (gap < bestDistance) {
      best = candidate;
      bestDistance = gap;
    }
  }
  return best;
}

function step(from: MapPoint, towards: MapPoint, speed: number): MapPoint {
  const gap = distance(from, towards);
  const stride = speed * SECONDS_PER_TICK;
  if (gap <= stride || gap === 0) return towards;
  return {
    x: from.x + ((towards.x - from.x) / gap) * stride,
    y: from.y + ((towards.y - from.y) / gap) * stride,
  };
}

export function advance(
  state: ScriptedState,
  map: MapGeometry = THREE_ZONE_MAP,
): ScriptedState {
  if (state.ending !== null) return state;

  const tick = state.tick + 1;
  const damageTaken = new Map<string, number>();
  const baseDamage: Record<Side, number> = { north: 0, south: 0 };

  // Everyone acts on the state as it was at the start of the tick, so the order
  // units appear in the array cannot decide who lands a blow first.
  const moved = state.units.map((unit) => {
    if (unit.hp <= 0) return unit;

    const enemyBase = map.bases[opposing(unit.side)];
    if (distance(unit.position, enemyBase) <= BASE_REACH) {
      baseDamage[opposing(unit.side)] +=
        unit.dps * BASE_DAMAGE_MULTIPLIER * SECONDS_PER_TICK;
      return unit;
    }

    const target = nearestEnemy(unit, state.units);
    const gap = target ? distance(unit.position, target.position) : Infinity;
    if (target && gap <= unit.range) {
      damageTaken.set(
        target.id,
        (damageTaken.get(target.id) ?? 0) + unit.dps * SECONDS_PER_TICK,
      );
      // A pusher keeps going while it swings; anyone else holds the engagement.
      if (!unit.pushing) return unit;
    }

    const towards =
      !unit.pushing && target && gap < unit.range * 4 ? target.position : unit.destination;
    return { ...unit, position: step(unit.position, towards, unit.speed) };
  });

  const units = moved
    .map((unit) => ({ ...unit, hp: unit.hp - (damageTaken.get(unit.id) ?? 0) }))
    .filter((unit) => unit.hp > 0);

  const zones = scoreZones(units, map);
  const zoneScore = {
    north: state.zoneScore.north + zones.north,
    south: state.zoneScore.south + zones.south,
  };

  const baseHp = {
    north: { ...state.baseHp.north, hp: Math.max(0, state.baseHp.north.hp - baseDamage.north) },
    south: { ...state.baseHp.south, hp: Math.max(0, state.baseHp.south.hp - baseDamage.south) },
  };

  const energy = {
    north: Math.min(ENERGY_CAP, state.energy.north + ENERGY_PER_SECOND * SECONDS_PER_TICK),
    south: Math.min(ENERGY_CAP, state.energy.south + ENERGY_PER_SECOND * SECONDS_PER_TICK),
  };

  return {
    tick,
    units,
    zoneScore,
    baseHp,
    energy,
    casts: state.casts,
    ending: endingFor(tick, units, baseHp, zoneScore),
  };
}

function scoreZones(
  units: readonly ScriptedUnit[],
  map: MapGeometry,
): Record<Side, number> {
  const gained: Record<Side, number> = { north: 0, south: 0 };

  for (const zone of map.zones) {
    let north = 0;
    let south = 0;
    for (const unit of units) {
      if (zoneAt(map, unit.position.y) !== zone.id) continue;
      if (unit.side === 'north') north += 1;
      else south += 1;
    }
    // Contested is nobody's: an outnumbered zone is held, an even one is not.
    if (north > south) gained.north += zone.pointsPerTick;
    else if (south > north) gained.south += zone.pointsPerTick;
  }

  return gained;
}

function endingFor(
  tick: number,
  units: readonly ScriptedUnit[],
  baseHp: Record<Side, BaseHp>,
  zoneScore: Record<Side, number>,
): RoundEnding | null {
  // Base destruction is checked first and ends the match, not just the round.
  if (baseHp.north.hp <= 0) return { kind: 'baseDestroyed', winner: 'south' };
  if (baseHp.south.hp <= 0) return { kind: 'baseDestroyed', winner: 'north' };

  const northAlive = units.some((unit) => unit.side === 'north');
  const southAlive = units.some((unit) => unit.side === 'south');
  if (!northAlive || !southAlive) {
    return {
      kind: 'roundComplete',
      winner: northAlive ? 'north' : southAlive ? 'south' : null,
      reason: 'annihilation',
    };
  }

  if (tick >= MAX_TICKS) {
    return {
      kind: 'roundComplete',
      winner: winnerOnScore(zoneScore),
      reason: 'zoneControl',
    };
  }

  return null;
}

function winnerOnScore(zoneScore: Record<Side, number>): Side | null {
  if (zoneScore.north > zoneScore.south) return 'north';
  if (zoneScore.south > zoneScore.north) return 'south';
  return null;
}

/* ----------------------------------------------------------------- casts -- */

export interface CastAttempt {
  readonly state: ScriptedState;
  readonly rejection: CastRejection | null;
}

/**
 * The server's half of a cast: charge the energy, apply the effect, record it.
 *
 * Rejection is the interesting half. The client never decides a cast is legal —
 * it asks, and renders what comes back — so every reason a cast can fail has to
 * be expressible here, and the screen has to have something to say for each.
 */
export function applyCast(
  state: ScriptedState,
  side: Side,
  command: CastCommand,
  loadout: readonly LoadoutSpell[],
  map: MapGeometry = THREE_ZONE_MAP,
): CastAttempt {
  if (state.ending !== null) return { state, rejection: 'roundOver' };

  const spell = loadout.find((entry) => entry.spellId === command.spellId);
  if (!spell) return { state, rejection: 'notEquipped' };

  const { x, y } = command.at;
  if (x < 0 || x > map.width || y < 0 || y > map.height) {
    return { state, rejection: 'outOfBounds' };
  }

  if (state.energy[side] < spell.cost) return { state, rejection: 'notEnoughEnergy' };

  // A repeat of a command already accepted is the same cast, not a second one.
  // Deduplicating properly is JQ-310; this is the fixture holding the seam open.
  if (state.casts.some((cast) => cast.commandId === command.commandId)) {
    return { state, rejection: null };
  }

  const units = state.units
    .map((unit) =>
      unit.side === side || distance(unit.position, command.at) > CAST_RADIUS
        ? unit
        : { ...unit, hp: unit.hp - CAST_DAMAGE },
    )
    .filter((unit) => unit.hp > 0);

  const cast: ResolvedCast = {
    commandId: command.commandId,
    spellId: spell.spellId,
    spellName: spell.name,
    castBy: side,
    at: command.at,
    tick: state.tick,
  };

  return {
    state: {
      ...state,
      units,
      energy: { ...state.energy, [side]: state.energy[side] - spell.cost },
      casts: [...state.casts, cast],
    },
    rejection: null,
  };
}

/* ------------------------------------------------------------- to a view -- */

/**
 * Turns the fixture's state into the snapshot the screens render.
 *
 * `you` decides what is in it, not just how it is drawn: the opponent's energy
 * and loadout never cross this line. Filtering at the edge nearest the wire is
 * what makes "visibility filtering is required from the first demo" (JQ-311)
 * something the client cannot accidentally undo.
 */
export function toSnapshot(
  state: ScriptedState,
  you: Side,
  loadout: readonly LoadoutSpell[],
  map: MapGeometry = THREE_ZONE_MAP,
  options: { readonly onlyYourUnits?: boolean } = {},
): BattleSnapshot {
  const visible = options.onlyYourUnits
    ? state.units.filter((unit) => unit.side === you)
    : state.units;

  return {
    tick: state.tick,
    units: visible.map(toBattleUnit),
    zones: zoneStates(state, map),
    zoneScore: { north: round2(state.zoneScore.north), south: round2(state.zoneScore.south) },
    energy: round2(state.energy[you]),
    loadout,
    casts: state.casts,
  };
}

function toBattleUnit(unit: ScriptedUnit): BattleUnit {
  return {
    id: unit.id,
    kind: unit.kind,
    side: unit.side,
    typeName: unit.typeName,
    position: { x: round2(unit.position.x), y: round2(unit.position.y) },
    hp: round2(unit.hp),
    maxHp: unit.maxHp,
  };
}

export function zoneStates(state: ScriptedState, map: MapGeometry): ZoneState[] {
  return map.zones.map((zone) => {
    let north = 0;
    let south = 0;
    for (const unit of state.units) {
      if (zoneAt(map, unit.position.y) !== zone.id) continue;
      if (unit.side === 'north') north += 1;
      else south += 1;
    }
    return { id: zone.id, heldBy: north > south ? 'north' : south > north ? 'south' : null };
  });
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
