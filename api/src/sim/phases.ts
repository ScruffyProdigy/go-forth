/**
 * The per-tick phase order — declared here and nowhere else.
 *
 * The loop walks this list. A later slice adds its phase to the list rather than
 * threading logic through `stepBattle`, which is what keeps three parallel
 * slices out of the same function.
 *
 * Where the remaining slices slot in:
 *
 * | Phase       | Slice | Sits            |
 * | ----------- | ----- | --------------- |
 * | `orders`    | B     | before movement |
 * | `movement`  | A     |                 |
 * | `energy`    | C     | before combat   |
 * | `abilities` | C     | before combat   |
 * | `combat`    | A     |                 |
 * | `scoring`   | B     | after combat    |
 * | `resummon`  | D     | before removal  |
 * | `removal`   | A     | last            |
 *
 * `removal` stays last: a unit brought to zero must not act again, and every
 * phase that wants to see the dead — the troop-bond dissolve above all — has to
 * run before they are swept.
 */
import { combatPhase } from './phases/combat.js';
import { movementPhase } from './phases/movement.js';
import { removalPhase } from './phases/removal.js';
import type { TickPhase } from './phase.js';

export const TICK_PHASES: readonly TickPhase[] = Object.freeze([
  movementPhase,
  combatPhase,
  removalPhase,
]);

export type { TickPhase };
