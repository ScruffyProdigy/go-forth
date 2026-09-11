/**
 * The tick loop — the sim's entry point.
 *
 * Pure by construction: no I/O, no wall clock, no rendering imports. Everything
 * it needs arrives as an argument and everything it produces is returned, so the
 * same four inputs always give byte-identical state and events. `purity.test.ts`
 * asserts that by walking this module's import graph.
 *
 * The loop itself does nothing but walk `TICK_PHASES` — see `phases.ts` for the
 * order and for where the remaining slices attach.
 */
import type { SimConfig } from './config.js';
import { DEFAULT_SIM_CONFIG, maxTicks, validateSimConfig } from './config.js';
import { createTickContext, type TickContext } from './context.js';
import type { BattleEvent } from './events.js';
import type { MapConfig } from './map.js';
import { TICK_PHASES } from './phases.js';
import { createRng } from './rng.js';
import type { SchoolConfig, SchoolMultiplierTable } from './schools.js';
import { resolveSchoolMultipliers } from './schools.js';
import { SIDES } from './types.js';
import type { BattleSetup, World } from './world.js';
import { createWorld } from './world.js';

/** Why the battle stopped. Zone-score and base-destruction endings arrive with slice B. */
export type BattleOutcome = 'annihilation' | 'timeUp';

export interface BattleTick {
  readonly tick: number;
  /** A snapshot: detached from the live world, so later ticks cannot rewrite it. */
  readonly state: World;
  readonly events: readonly BattleEvent[];
}

export interface BattleResult {
  /** The seed the battle ran on. Replaying it reproduces this result exactly. */
  readonly seed: number;
  /** Tick by tick, starting with the opening state at tick 0. */
  readonly ticks: readonly BattleTick[];
  /** Every event of the battle, in order. */
  readonly events: readonly BattleEvent[];
  readonly finalState: World;
  readonly outcome: BattleOutcome;
  /** The map the battle was fought on, so a consumer need not be handed it twice. */
  readonly map: MapConfig;
  readonly config: SimConfig;
  readonly multipliers: SchoolMultiplierTable;
}

/** Advances the world exactly one tick and returns the events that tick produced. */
export function stepBattle(world: World, ctx: TickContext): BattleEvent[] {
  world.tick += 1;

  for (const phase of TICK_PHASES) {
    phase.run(world, ctx);
  }

  world.rngState = ctx.rng.state;
  return ctx.emitter.drain();
}

function sideIsWipedOut(world: World): boolean {
  return SIDES.some((side) => !world.units.some((unit) => unit.side === side));
}

function snapshot(world: World): World {
  return structuredClone(world);
}

/**
 * Runs a battle to its end.
 *
 * @param seed - the whole of the battle's randomness. Same seed, same battle.
 */
export function runBattle(
  mapConfig: MapConfig,
  schoolConfigs: readonly SchoolConfig[],
  battleState: BattleSetup,
  seed: number,
  config: SimConfig = DEFAULT_SIM_CONFIG,
): BattleResult {
  validateSimConfig(config);

  const rng = createRng(seed);
  const multipliers = resolveSchoolMultipliers(schoolConfigs);
  const world = createWorld(mapConfig, battleState, rng);
  const ctx = createTickContext({ config, map: mapConfig, multipliers, rng });

  const ticks: BattleTick[] = [{ tick: 0, state: snapshot(world), events: [] }];
  const events: BattleEvent[] = [];
  const limit = maxTicks(config);

  let outcome: BattleOutcome = 'timeUp';

  while (world.tick < limit) {
    const tickEvents = stepBattle(world, ctx);
    events.push(...tickEvents);
    ticks.push({ tick: world.tick, state: snapshot(world), events: tickEvents });

    if (sideIsWipedOut(world)) {
      outcome = 'annihilation';
      break;
    }
  }

  return { seed, ticks, events, finalState: world, outcome, map: mapConfig, config, multipliers };
}
