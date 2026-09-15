"""Firing the abilities whose gauges came up full.

A cast is entirely data-driven: the phase looks the ability up, decides where
it lands, and hands its effects to `resolution.py`. There is no branch on which
ability it is, and that is the property JQ-288 exists to establish — JQ-185's
roster has to fit through here without widening it.

A cast that needs a target and has none is **held**, not wasted: the gauge
stays full and the unit casts on the first tick something is in reach. The
alternative — burning a full gauge on empty air — makes a card's output depend
on when its last enemy died, which is not a thing a designer can tune.
"""

from __future__ import annotations

from app.sim.abilities import Ability
from app.sim.context import TickContext
from app.sim.effects import ORIGIN_SELF
from app.sim.events import ability_cast
from app.sim.phases.targeting import acquire_target, is_alive
from app.sim.resolution import Cast, apply_effects, swing_of
from app.sim.world import Unit, World, unit_ref


def _cast_for(world: World, ctx: TickContext, unit: Unit, ability: Ability) -> Cast | None:
    if ability.origin == ORIGIN_SELF:
        return Cast(
            world=world, ctx=ctx, side=unit.side, origin=unit.position, caster=unit, follows_caster=True
        )

    target = acquire_target(world, unit, reach=ability.range)
    if target is None:
        return None

    return Cast(world=world, ctx=ctx, side=unit.side, origin=target.position, caster=unit, target=target)


class AbilitiesPhase:
    name = "abilities"

    def run(self, world: World, ctx: TickContext) -> None:
        # A snapshot of the list: an ability that refills an ally's gauge can
        # let that ally cast on this same tick, which is deliberate, but the
        # list of who *gets a turn* is fixed before any of it runs.
        for unit in list(world.units):
            if not is_alive(unit) or unit.ability_id is None:
                continue

            ability = ctx.abilities.get(unit.ability_id)
            if ability is None or unit.energy < ability.energy_cost:
                continue

            cast = _cast_for(world, ctx, unit, ability)
            if cast is None:
                continue

            unit.energy = 0.0
            outcome = apply_effects(ability.effects, cast)

            ctx.emitter.emit(
                **ability_cast(
                    tick=world.tick,
                    position=cast.origin,
                    ability_id=ability.id,
                    caster=unit_ref(unit),
                    targets=(unit_ref(cast.target),) if cast.target is not None else (),
                    swing=swing_of(outcome),
                )
            )


abilities_phase = AbilitiesPhase()
