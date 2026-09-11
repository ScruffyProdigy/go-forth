"""Combat: acquire, swing on a cooldown, and report the defeats.

Damage resolves in list order rather than simultaneously. That is a real design
choice — it means a unit killed this tick does not swing back — and it is
deterministic because unit order is deterministic. Abilities and energy are slice
C (JQ-288); this is the plain auto-attack underneath them.
"""

from __future__ import annotations

from app.sim.config import to_ticks
from app.sim.context import TickContext
from app.sim.events import unit_defeated
from app.sim.phases.targeting import acquire_target, is_alive
from app.sim.world import World, unit_ref


class CombatPhase:
    name = "combat"

    def run(self, world: World, ctx: TickContext) -> None:
        for unit in world.units:
            if not is_alive(unit):
                continue

            if unit.cooldown_remaining > 0:
                unit.cooldown_remaining -= 1
                if unit.cooldown_remaining > 0:
                    continue

            target = acquire_target(world, unit)
            if target is None:
                continue

            target.hp -= unit.damage
            unit.cooldown_remaining = to_ticks(unit.attack_cooldown_seconds, ctx.config)

            if target.hp <= 0:
                target.hp = 0
                ctx.emitter.emit(
                    **unit_defeated(
                        tick=world.tick,
                        position=target.position,
                        unit=unit_ref(target),
                        killer=unit_ref(unit),
                    )
                )


combat_phase = CombatPhase()
