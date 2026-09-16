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

import type { Order, PlanState } from '../../plan/types.ts';
import {
  TWO_LANE_MAP,
  type MapGeometry,
  type ZoneGeometry,
  distance,
  hotspotContains,
  spanCentre,
  zoneCentre,
  zoneGeometry,
} from '../geometry.ts';
import {
  type BaseHp,
  type BattleEvent,
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

/** How far apart two troops sent to the same lane form up. */
const COLUMN_PITCH = 52;

/**
 * How long an event is kept on the state. Comfortably longer than the board
 * shows one, so a client that misses a frame still sees it, and short enough
 * that the list cannot grow for the whole round.
 */
const EVENT_HISTORY_TICKS = 60;

/**
 * Provisional protection, so outcome previews have something real to read.
 *
 * Stated per unit rather than assumed by the preview: JQ-312 AC 4 turns on a
 * preview being able to tell "protection 0" from "the server did not say", and
 * the only way to test that distinction is for the fixture to be able to say
 * both. Summons carry none; a mage shrugs off a little.
 */
const MAGE_PROTECTION = 6;
const SUMMON_PROTECTION = 0;

/**
 * The provisional ability gauge. Real charging is school data (JQ-288's energy
 * sources); this fills on a clock so that rings, "about to fire" and the
 * `abilityCast` event are all reachable in a thirty-second demo round.
 */
const ABILITY_COST = 35;
const ABILITY_GAIN_PER_SECOND = 4;

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
  /** Damage shrugged off per hit. What outcome previews read. */
  readonly protection: number;
  /** The ability a full gauge fires, and the gauge. Null never charges. */
  readonly abilityName: string | null;
  readonly abilityEnergy: number;
  /** The mage this summon belongs to — a dissolve needs to know. */
  readonly mageId: string | null;
}

export interface ScriptedState {
  readonly tick: number;
  readonly units: readonly ScriptedUnit[];
  readonly zoneScore: Readonly<Record<Side, number>>;
  readonly baseHp: Readonly<Record<Side, BaseHp>>;
  readonly energy: Readonly<Record<Side, number>>;
  readonly casts: readonly ResolvedCast[];
  /**
   * What has happened, newest last, in the sim's own event vocabulary. Kept on
   * the state rather than derived by diffing snapshots: a diff cannot tell a
   * summon that died from one that walked out of the visible set.
   */
  readonly events: readonly BattleEvent[];
  /** Set on the tick the round ends. Null while it is still running. */
  readonly ending: RoundEnding | null;
}

export interface ArmyPlan {
  readonly side: Side;
  readonly plan: PlanState;
}

/* --------------------------------------------------------------- opening -- */

/**
 * Where an order sends a troop.
 *
 * A Hold aims at the lane's **hotspot**, not at the lane. Under JQ-376 holding
 * is a mage standing in that square, so a fixture that walked troops to the
 * middle of the lane's area would produce a board where nobody ever scores and
 * the screens would be built against a battle the sim cannot produce.
 */
function destinationFor(order: Order, side: Side, map: MapGeometry): MapPoint {
  if (order.kind === 'hold') {
    return zoneCentre(zoneGeometry(map, order.zone));
  }
  if (order.kind === 'defendBase') {
    const base = map.bases[side];
    return { x: map.width / 2, y: base.y + (side === 'south' ? -50 : 50) };
  }
  return map.bases[opposing(side)];
}

/**
 * Which part of the deployment strip a troop forms up in.
 *
 * Its order's lane, so the board a player locked in is the board they watch: a
 * troop sent west starts west. Troops without a lane (the two base orders) form
 * up in the corridor between them, which is the way they are going anyway.
 */
function columnFor(order: Order, map: MapGeometry): number {
  if (order.kind === 'hold') return zoneCentre(zoneGeometry(map, order.zone)).x;
  return corridorCentre(map);
}

/**
 * The middle of the push corridor: the widest gap between two lanes.
 *
 * Derived rather than written down as "the middle of the map", because the map
 * decides where its lanes are and a map whose corridor is off-centre would
 * otherwise deploy its pushers into a lane.
 */
function corridorCentre(map: MapGeometry): number {
  const ordered = [...map.zones].sort((a, b) => a.extent.start - b.extent.start);

  let widest = { start: map.width / 2, end: map.width / 2 };
  for (let index = 1; index < ordered.length; index += 1) {
    const gap = { start: ordered[index - 1].extent.end, end: ordered[index].extent.start };
    if (gap.end - gap.start > widest.end - widest.start) widest = gap;
  }

  return spanCentre(widest);
}

/**
 * Lays a plan out in its side's deployment strip.
 *
 * Placement is columns-first, one column per troop, summons ahead of the mage —
 * the same shape the plan screen draws, so the board a player locked in is the
 * board they then watch. JQ-287 owns derived formations for real; this only has
 * to not contradict it.
 */
export function deploy(army: ArmyPlan, map: MapGeometry = TWO_LANE_MAP): ScriptedUnit[] {
  const strip = map.deployment[army.side];
  const forward = army.side === 'south' ? -1 : 1;
  const units: ScriptedUnit[] = [];

  army.plan.troops.forEach((troop) => {
    const mage = army.plan.roster.mages.find((candidate) => candidate.id === troop.mageId);
    if (!mage) return;

    // Columns-first within the troop's own lane (JQ-287). Troops sharing a lane
    // are nudged apart so two Hold West troops do not stack into one mark.
    const sharing = army.plan.troops.filter(
      (candidate) => columnFor(candidate.order, map) === columnFor(troop.order, map),
    );
    const rank = sharing.indexOf(troop);
    const column =
      columnFor(troop.order, map) + (rank - (sharing.length - 1) / 2) * COLUMN_PITCH;
    const destination = destinationFor(troop.order, army.side, map);
    const pushing = troop.order.kind === 'pushEnemyBase';
    const mageY = army.side === 'south' ? strip.lane.end - 16 : strip.lane.start + 16;

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
        protection: SUMMON_PROTECTION,
        abilityName: null,
        abilityEnergy: 0,
        mageId: troop.mageId,
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
      protection: MAGE_PROTECTION,
      abilityName: `${mage.name}'s ability`,
      abilityEnergy: 0,
      mageId: troop.mageId,
    });
  });

  return units;
}

export function openingState(
  armies: readonly ArmyPlan[],
  map: MapGeometry = TWO_LANE_MAP,
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
    events: [],
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
  map: MapGeometry = TWO_LANE_MAP,
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

  const events: BattleEvent[] = [];

  // The gauge fills, and a full one fires and resets. Charged before deaths are
  // resolved so a unit that dies this tick does not also fire this tick.
  const charged = moved.map((unit) => {
    if (unit.abilityName === null) return unit;

    const gauge = unit.abilityEnergy + ABILITY_GAIN_PER_SECOND * SECONDS_PER_TICK;
    if (gauge < ABILITY_COST) return { ...unit, abilityEnergy: gauge };

    events.push({
      id: `ability-${unit.id}-${tick}`,
      type: 'abilityCast',
      tick,
      at: unit.position,
      side: unit.side,
      subject: unit.abilityName,
    });
    return { ...unit, abilityEnergy: 0 };
  });

  const survivors = charged.map((unit) => ({
    ...unit,
    hp: unit.hp - (damageTaken.get(unit.id) ?? 0),
  }));

  for (const unit of survivors) {
    if (unit.hp > 0) continue;
    events.push({
      id: `defeated-${unit.id}-${tick}`,
      type: 'unitDefeated',
      tick,
      at: unit.position,
      side: unit.side,
      subject: unit.typeName,
    });
  }

  // A mage's death takes its summons with it (JQ-289's troop bond). Emitted as
  // one `troopDissolve` rather than a handful of defeats, because that is what
  // it is: the board has to show a troop coming apart, not four coincidences.
  const fallenMages = survivors.filter((unit) => unit.kind === 'mage' && unit.hp <= 0);
  const dissolved = new Set<string>();
  for (const mage of fallenMages) {
    const bonded = survivors.filter(
      (unit) => unit.kind === 'summon' && unit.hp > 0 && unit.mageId === mage.mageId
        && unit.side === mage.side,
    );
    if (bonded.length === 0) continue;

    for (const summon of bonded) dissolved.add(summon.id);
    events.push({
      id: `dissolve-${mage.id}-${tick}`,
      type: 'troopDissolve',
      tick,
      at: mage.position,
      side: mage.side,
      subject: mage.typeName,
      count: bonded.length,
    });
  }

  const units = survivors.filter((unit) => unit.hp > 0 && !dissolved.has(unit.id));

  const zones = scoreZones(units, map);
  const zoneScore = {
    north: state.zoneScore.north + zones.north,
    south: state.zoneScore.south + zones.south,
  };

  // A flip is emitted when the holder changes, carrying the income it swung.
  const before = holdersOf(state.units, map);
  const after = holdersOf(units, map);
  for (const zone of map.zones) {
    if (before[zone.id] === after[zone.id]) continue;
    events.push({
      id: `flip-${zone.id}-${tick}`,
      type: 'zoneFlip',
      tick,
      at: zoneCentre(zone),
      side: after[zone.id],
      zone: zone.id,
    });
  }

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
    // Trimmed to what the board can still be showing. An unbounded list would
    // grow for the whole round and be re-scanned every frame.
    events: [...state.events, ...events].filter((event) => tick - event.tick <= EVENT_HISTORY_TICKS),
    ending: endingFor(tick, units, baseHp, zoneScore),
  };
}

/** Who holds each lane right now, by the hotspot rule. */
function holdersOf(
  units: readonly ScriptedUnit[],
  map: MapGeometry,
): Record<string, Side | null> {
  const holders: Record<string, Side | null> = {};
  for (const zone of map.zones) holders[zone.id] = holderOf(units, map, zone);
  return holders;
}

/**
 * A lane is held when **exactly one side has a living mage in its hotspot**
 * (JQ-376). Both present, or neither, holds nothing, and a summon standing on
 * the spot holds nothing at all — scoring costs you the exposure of the troop's
 * slowest, most fragile unit, which is the point of the rule.
 */
function holderOf(
  units: readonly ScriptedUnit[],
  map: MapGeometry,
  zone: ZoneGeometry,
): Side | null {
  let north = false;
  let south = false;
  for (const unit of units) {
    if (unit.kind !== 'mage' || unit.hp <= 0) continue;
    if (!hotspotContains(map, zone, unit.position)) continue;
    if (unit.side === 'north') north = true;
    else south = true;
  }

  if (north === south) return null;
  return north ? 'north' : 'south';
}

function scoreZones(
  units: readonly ScriptedUnit[],
  map: MapGeometry,
): Record<Side, number> {
  const gained: Record<Side, number> = { north: 0, south: 0 };

  for (const zone of map.zones) {
    const holder = holderOf(units, map, zone);
    if (holder !== null) gained[holder] += zone.pointsPerTick;
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
  map: MapGeometry = TWO_LANE_MAP,
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

  const event: BattleEvent = {
    id: `spell-${command.commandId}`,
    type: 'spell',
    tick: state.tick,
    at: command.at,
    side,
    subject: spell.name,
    count: state.units.length - units.length,
  };

  return {
    state: {
      ...state,
      units,
      energy: { ...state.energy, [side]: state.energy[side] - spell.cost },
      casts: [...state.casts, cast],
      events: [...state.events, event],
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
  map: MapGeometry = TWO_LANE_MAP,
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
    events: state.events,
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
    protection: unit.protection,
    ability:
      unit.abilityName === null
        ? undefined
        : {
            id: `${unit.id}-ability`,
            name: unit.abilityName,
            // A fraction, not the two numbers: the board decides what "close"
            // looks like, and a client given a cost would decide it too.
            charge: round2(Math.min(1, unit.abilityEnergy / ABILITY_COST)),
          },
  };
}

export function zoneStates(state: ScriptedState, map: MapGeometry): ZoneState[] {
  return map.zones.map((zone) => ({ id: zone.id, heldBy: holderOf(state.units, map, zone) }));
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
