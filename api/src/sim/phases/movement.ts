/**
 * Movement.
 *
 * Units advance on a position and stop at weapon range rather than walking into
 * the enemy — two ranks in contact sit ~20 px apart and read as one blob, and
 * the engagement gap is what hands the front line back (JQ-243).
 *
 * The position they advance on is the enemy base, because slice A has no orders.
 * Orders, derived formations, and engage-en-route are JQ-287, which replaces
 * `destinationFor` with the troop's assigned objective.
 */
import { moveToward } from '../geometry.js';
import type { TickContext } from '../context.js';
import type { TickPhase } from '../phase.js';
import { opposing } from '../types.js';
import type { Vec2 } from '../types.js';
import type { Unit, World } from '../world.js';
import { acquireTarget, isAlive } from './targeting.js';

function destinationFor(unit: Unit, ctx: TickContext): Vec2 {
  return ctx.map.bases[opposing(unit.side)].position;
}

export const movementPhase: TickPhase = {
  name: 'movement',
  run(world: World, ctx: TickContext): void {
    const step = ctx.secondsPerTick;

    for (const unit of world.units) {
      if (!isAlive(unit) || unit.speed === 0) continue;
      // Already in reach of something: hold the gap and let combat work.
      if (acquireTarget(world, unit)) continue;

      unit.position = moveToward(unit.position, destinationFor(unit, ctx), unit.speed * step);
    }
  },
};
