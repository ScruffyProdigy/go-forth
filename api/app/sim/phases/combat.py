"""Combat: acquire, swing on a cooldown, and report the defeats.

Damage resolves in list order rather than simultaneously. That is a real design
choice — it means a unit killed this tick does not swing back — and it is
deterministic because unit order is deterministic. This is the plain
auto-attack underneath the abilities; what it adds for slice C (JQ-288) is the
energy meters a swing moves, so that Fire's "charge off damage dealt" rule is
true of a weapon swing and not only of an ability's blast.

Bases are attacked here too, and only by troops under Push enemy base. The filter
is applied here rather than trusted to whoever is choosing targets: a unit under
any other order never gets a base as a target, however it was asked. Units come
first — a pushing troop that walks into defenders fights them rather than walking
past to hammer the wall.
"""

from __future__ import annotations

from app.sim.config import to_ticks
from app.sim.context import TickContext
from app.sim.energy import DAMAGE_DEALT, DAMAGE_TAKEN
from app.sim.events import base_hit, unit_defeated
from app.sim.geometry import distance
from app.sim.orders import may_attack_base
from app.sim.phases.targeting import acquire_target
from app.sim.types import opposing
from app.sim.world import Unit, World, is_alive, orders_by_troop, unit_ref


def _swing_at_the_base(world: World, unit: Unit, ctx: TickContext) -> bool:
    """Lands a blow on the enemy base if the unit is in reach of it."""
    side = opposing(unit.side)
    base = world.bases[side]
    if base.hp <= 0:
        return False

    reach = unit.range + ctx.map_config.bases[side].footprint_radius
    if distance(unit.position, base.position) > reach:
        return False

    dealt = min(unit.damage, base.hp)
    base.hp -= dealt
    unit.energy_meters[DAMAGE_DEALT] += dealt
    ctx.emitter.emit(
        **base_hit(
            tick=world.tick,
            position=base.position,
            owner=side,
            attacker=unit_ref(unit),
            damage=dealt,
        )
    )
    return True


class CombatPhase:
    name = "combat"

    def run(self, world: World, ctx: TickContext) -> None:
        orders = orders_by_troop(world)

        for unit in world.units:
            if not is_alive(unit):
                continue

            if unit.cooldown_remaining > 0:
                unit.cooldown_remaining -= 1
                if unit.cooldown_remaining > 0:
                    continue

            target = acquire_target(world, unit)
            if target is None:
                if may_attack_base(orders[unit.troop_id]) and _swing_at_the_base(world, unit, ctx):
                    unit.cooldown_remaining = to_ticks(unit.attack_cooldown_seconds, ctx.config)
                continue

            target.hp -= unit.damage
            # The meters the energy phase converts next tick.
            unit.energy_meters[DAMAGE_DEALT] += unit.damage
            target.energy_meters[DAMAGE_TAKEN] += unit.damage
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
