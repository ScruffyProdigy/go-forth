/**
 * What a phase is handed each tick.
 *
 * Everything a system needs and nothing it can use to reach outside the sim:
 * no clock, no filesystem, no logger. New slices add fields here rather than
 * importing modules of their own into the phases.
 */
import type { SimConfig } from './config.js';
import { secondsPerTick, validateSimConfig } from './config.js';
import type { EventEmitter } from './events.js';
import { createEventEmitter } from './events.js';
import type { MapConfig } from './map.js';
import type { Rng } from './rng.js';
import type { SchoolMultiplierTable } from './schools.js';

export interface TickContext {
  readonly config: SimConfig;
  readonly map: MapConfig;
  /** Resolved once at battle start; read by every system, written by none. */
  readonly multipliers: SchoolMultiplierTable;
  /** The one emitter every system writes events through. */
  readonly emitter: EventEmitter;
  readonly rng: Rng;
  /** Cached, because every phase that moves anything needs it. */
  readonly secondsPerTick: number;
}

export function createTickContext(input: {
  config: SimConfig;
  map: MapConfig;
  multipliers: SchoolMultiplierTable;
  rng: Rng;
  emitter?: EventEmitter;
}): TickContext {
  validateSimConfig(input.config);

  return {
    config: input.config,
    map: input.map,
    multipliers: input.multipliers,
    emitter: input.emitter ?? createEventEmitter(),
    rng: input.rng,
    secondsPerTick: secondsPerTick(input.config),
  };
}
