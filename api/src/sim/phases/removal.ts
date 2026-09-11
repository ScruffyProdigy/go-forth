/**
 * Sweeping the dead off the field.
 *
 * Separate from combat so that everything resolving this tick sees the same
 * field: a unit brought to zero stops acting immediately, but only leaves the
 * arrays once the tick is over.
 *
 * Slice D (JQ-289) hangs the dispelled slot and the troop-bond dissolve off this
 * phase — it is where a troop first learns it has lost its last mage.
 */
import type { TickContext } from '../context.js';
import type { TickPhase } from '../phase.js';
import type { World } from '../world.js';
import { isAlive } from './targeting.js';

export const removalPhase: TickPhase = {
  name: 'removal',
  run(world: World, _ctx: TickContext): void {
    const fallen = world.units.filter((unit) => !isAlive(unit));
    if (fallen.length === 0) return;

    const fallenIds = new Set(fallen.map((unit) => unit.id));
    world.units = world.units.filter((unit) => !fallenIds.has(unit.id));

    for (const troop of world.troops) {
      troop.mageIds = troop.mageIds.filter((id) => !fallenIds.has(id));
      troop.summonIds = troop.summonIds.filter((id) => !fallenIds.has(id));
    }
  },
};
