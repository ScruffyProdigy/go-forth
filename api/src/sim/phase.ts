/** What a per-tick phase is. Its own module so the phases and the list of them do not import each other. */
import type { TickContext } from './context.js';
import type { World } from './world.js';

export interface TickPhase {
  readonly name: string;
  /** Advances the world in place. Called once per tick, in the declared order. */
  run(world: World, ctx: TickContext): void;
}
