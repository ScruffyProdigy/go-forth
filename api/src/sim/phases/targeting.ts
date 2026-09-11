/**
 * Target acquisition, shared by the phases that need it.
 *
 * Ties break on unit id rather than on array position: two enemies exactly the
 * same distance away must resolve the same way in every replay, and array order
 * shifts as units are removed.
 */
import { distance } from '../geometry.js';
import type { Unit, World } from '../world.js';

export function isAlive(unit: Unit): boolean {
  return unit.hp > 0;
}

/** The nearest living enemy within the unit's weapon range, or null. */
export function acquireTarget(world: World, unit: Unit): Unit | null {
  let best: Unit | null = null;
  let bestGap = Infinity;

  for (const candidate of world.units) {
    if (candidate.side === unit.side || !isAlive(candidate)) continue;

    const gap = distance(unit.position, candidate.position);
    if (gap > unit.range) continue;

    if (gap < bestGap || (gap === bestGap && best !== null && candidate.id < best.id)) {
      best = candidate;
      bestGap = gap;
    }
  }

  return best;
}
