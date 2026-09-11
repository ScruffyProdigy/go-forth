/**
 * The battle sim.
 *
 * Everything a caller needs is here; nothing here touches the outside world. The
 * server hands `runBattle` a map, the school configs, a battle's roster data, and
 * a seed, and gets back the whole battle — tick by tick, with its event stream.
 *
 * Slice A (JQ-286) of the sim. Orders and zones are JQ-287, energy and abilities
 * JQ-288, resummoning and resonance JQ-289. See `phases.ts` for where each of
 * them attaches.
 */
export { runBattle, stepBattle } from './runBattle.js';
export type { BattleOutcome, BattleResult, BattleTick } from './runBattle.js';

export { DEFAULT_SIM_CONFIG, maxTicks, secondsPerTick, toTicks, validateSimConfig } from './config.js';
export type { SimConfig } from './config.js';

export { THREE_ZONE_MAP, validateMapConfig, zoneContaining } from './map.js';
export type { BaseConfig, DeploymentStrip, MapConfig, ZoneConfig } from './map.js';

export { createEventEmitter, unitDefeated } from './events.js';
export type { BattleEvent, BattleEventType, EventActors, EventEmitter, EventSwing } from './events.js';

export { IDENTITY_MULTIPLIERS, SCHOOLS, resolveSchoolMultipliers } from './schools.js';
export type { School, SchoolConfig, SchoolMultipliers, SchoolMultiplierTable } from './schools.js';

export { buildUnitTypeCatalog } from './units.js';
export type { UnitKind, UnitType, UnitTypeCatalog } from './units.js';

export { createWorld, unitRef } from './world.js';
export type {
  ArmySetup,
  BaseState,
  BattleSetup,
  RosterEntry,
  Troop,
  TroopSetup,
  Unit,
  World,
} from './world.js';

export { TICK_PHASES } from './phases.js';
export type { TickPhase } from './phase.js';
export { createTickContext } from './context.js';
export type { TickContext } from './context.js';

export { createRng, rngFromState } from './rng.js';
export type { Rng, RngState } from './rng.js';

export { digestBattle, serializeBattle } from './serialize.js';
export { PLACEHOLDER_UNIT_TYPES, placeholderBattle } from './fixtures.js';

export { SIDES, opposing } from './types.js';
export type { Side, Span, TroopId, UnitId, UnitRef, Vec2 } from './types.js';
