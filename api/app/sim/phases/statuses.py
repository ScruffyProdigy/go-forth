"""Ticking down what effects left behind: burns and burning ground.

After combat and before removal, for the same reason combat sits where it does
— a unit a burn finishes this tick must not swing back, and slice D's dissolve
still has to see the body.

Damage from a status charges nobody's gauge. The unit that lit it may be dead,
and paying a corpse's energy meter is worse than paying nothing; the source is
kept for the event stream rather than for the ledger.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.geometry import distance
from app.sim.phases.targeting import is_alive
from app.sim.resolution import Cast, damage_unit
from app.sim.world import World


class StatusesPhase:
    name = "statuses"

    def run(self, world: World, ctx: TickContext) -> None:
        self._burn_the_ground(world, ctx)
        self._burn_the_burning(world, ctx)

    def _burn_the_ground(self, world: World, ctx: TickContext) -> None:
        if not world.hazards:
            return

        for hazard in world.hazards:
            cast = Cast(world=world, ctx=ctx, side=hazard.side, origin=hazard.center)
            for victim in list(world.units):
                if victim.side == hazard.side or not is_alive(victim):
                    continue
                if distance(hazard.center, victim.position) > hazard.radius:
                    continue

                amount = hazard.damage_per_tick * (hazard.bonus_vs_mage if victim.kind == "mage" else 1.0)
                damage_unit(cast, victim, amount, hazard.source)

            hazard.ticks_remaining -= 1

        world.hazards = [hazard for hazard in world.hazards if hazard.ticks_remaining > 0]

    def _burn_the_burning(self, world: World, ctx: TickContext) -> None:
        for unit in list(world.units):
            burn = unit.burn
            if burn is None:
                continue
            if not is_alive(unit):
                unit.burn = None
                continue

            cast = Cast(world=world, ctx=ctx, side=unit.side, origin=unit.position)
            amount = burn.damage_per_tick * (burn.bonus_vs_mage if unit.kind == "mage" else 1.0)
            # The burn belongs to the other side: `Cast.side` is the victim's,
            # so the damage helper is handed the victim directly rather than
            # asked to find enemies.
            damage_unit(cast, unit, amount, burn.source)

            burn.ticks_remaining -= 1
            if burn.ticks_remaining <= 0 or not is_alive(unit):
                unit.burn = None


statuses_phase = StatusesPhase()
