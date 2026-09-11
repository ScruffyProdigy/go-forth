/**
 * Combat: acquire, swing on a cooldown, and report the defeats.
 *
 * Damage resolves in array order rather than simultaneously. That is a real
 * design choice — it means a unit killed this tick does not swing back — and it
 * is deterministic because unit order is deterministic. Abilities and energy are
 * slice C (JQ-288); this is the plain auto-attack underneath them.
 */
import type { TickContext } from '../context.js';
import { toTicks } from '../config.js';
import { unitDefeated } from '../events.js';
import type { TickPhase } from '../phase.js';
import type { World } from '../world.js';
import { unitRef } from '../world.js';
import { acquireTarget, isAlive } from './targeting.js';

export const combatPhase: TickPhase = {
  name: 'combat',
  run(world: World, ctx: TickContext): void {
    for (const unit of world.units) {
      if (!isAlive(unit)) continue;

      if (unit.cooldownRemaining > 0) {
        unit.cooldownRemaining -= 1;
        if (unit.cooldownRemaining > 0) continue;
      }

      const target = acquireTarget(world, unit);
      if (!target) continue;

      target.hp -= unit.damage;
      unit.cooldownRemaining = toTicks(unit.attackCooldownSeconds, ctx.config);

      if (target.hp <= 0) {
        target.hp = 0;
        ctx.emitter.emit(
          unitDefeated({
            tick: world.tick,
            position: target.position,
            unit: unitRef(target),
            killer: unitRef(unit),
          }),
        );
      }
    }
  },
};
