"""Spending the abilities whose gauges are full.

A full gauge makes an ability **available**; it does not fire it. What this
phase does each tick is ask the cast policy, for every unit holding a ready
ability, whether now is the moment — and carry out the ones that say yes.

That split is the point. "Auto-cast the instant the bar fills" makes a dash
fire at whatever happens to be nearest, which is usually the cheap melee summon
already walking into contact, and the gauge is gone by the time the ranged unit
behind it is worth closing on. Holding is a real decision, so it belongs to
whatever is making decisions — the behaviour layer (JQ-296/328) — and this
phase only owns *executing* one. `casting.py` is the seam, with a deliberately
unclever default so a battle carrying no behaviour data still acts.

The cast itself is entirely data-driven once the decision is made: the phase
looks the ability up and hands its effects to `resolution.py`. There is no
branch on which ability it is, and that is the property JQ-288 exists to
establish — JQ-185's roster has to fit through here without widening it.
"""

from __future__ import annotations

from app.sim.casting import ability_ready
from app.sim.context import TickContext
from app.sim.events import ability_cast
from app.sim.phases.targeting import acquire_target, is_alive
from app.sim.resolution import Cast, apply_effects, swing_of
from app.sim.world import World, unit_ref


class AbilitiesPhase:
    name = "abilities"

    def run(self, world: World, ctx: TickContext) -> None:
        # A snapshot of the list: an ability that refills an ally's gauge can
        # make that ally's ability available on this same tick, which is
        # deliberate, but the list of who gets asked is fixed before any of it
        # runs.
        for unit in list(world.units):
            if not is_alive(unit) or unit.ability_id is None:
                continue

            ability = ctx.abilities.get(unit.ability_id)
            if ability is None or not ability_ready(unit, ability):
                continue

            # The phase does the search and the policy does the judging.
            # A behaviour layer that wants a *different* target overrides the
            # policy and ignores this one; the default is glad of it.
            nearest = acquire_target(world, unit, reach=ability.range)
            aimed = ctx.cast_policy.aim(world, unit, ability, nearest)
            if aimed is None:
                # Held, not wasted: the gauge stays full and the unit is asked
                # again next tick.
                continue

            cast = Cast(
                world=world,
                ctx=ctx,
                side=unit.side,
                origin=aimed.origin,
                caster=unit,
                target=aimed.target,
                follows_caster=aimed.follows_caster,
            )

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
