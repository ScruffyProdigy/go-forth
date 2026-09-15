"""Landing the player spells scheduled for this tick.

The injections were sorted when the world was built, so this phase only has to
take what is due off the front — two spells on one tick always resolve in the
same order, whatever order the match layer handed them over in.

A spell has no caster on the field, so effects that need one (a dash) do
nothing, and the damage it deals charges nobody's gauge. JQ-288 is explicit
that player spells do not gain school-resonance strength scaling: the
multiplier record is never read here, only in `phases/energy.py`.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.events import spell_cast
from app.sim.resolution import Cast, apply_effects, swing_of
from app.sim.world import World


class SpellsPhase:
    name = "spells"

    def run(self, world: World, ctx: TickContext) -> None:
        due = 0
        while due < len(world.pending_spells) and world.pending_spells[due].tick <= world.tick:
            due += 1
        if due == 0:
            return

        landing = world.pending_spells[:due]
        world.pending_spells = world.pending_spells[due:]

        for injection in landing:
            spell = ctx.spells.get(injection.spell_id)
            if spell is None:
                raise ValueError(f"spell {injection.spell_id} was injected but is not in the catalog")

            cast = Cast(world=world, ctx=ctx, side=injection.side, origin=injection.location)
            outcome = apply_effects(spell.effects, cast)

            ctx.emitter.emit(
                **spell_cast(
                    tick=world.tick,
                    position=injection.location,
                    spell_id=injection.spell_id,
                    swing=swing_of(outcome),
                )
            )


spells_phase = SpellsPhase()
