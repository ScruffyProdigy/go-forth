"""Charging the energy gauges.

Runs before abilities, and before combat, which puts a one-tick lag between
doing something and being paid for it: the damage a unit deals on tick N is
converted to energy at the top of tick N+1. That is a consequence of the phase
order JQ-286 declared rather than an accident, and it is the same lag for
every unit in every battle, so it costs nothing in determinism or fairness.

Only a unit with an ability charges. A gauge on a card that has nothing to
spend it on is state that appears in every snapshot and means nothing.

Reaching full does not cast. It makes the ability *available*, and the gauge
then sits there until something decides to spend it — see `casting.py`. So
this phase caps the gauge at its ability's cost rather than letting a held
ability bank energy toward the next one.

The multiplier is read per side (`ctx.multipliers[unit.side]`), because
resonance is a property of a player's roster rather than of the field (JQ-289):
a three-a-side Fire mirror is Fire 3 for each player, not Fire 6 on the map.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.energy import (
    ELAPSED_SECONDS,
    ENERGY_METERS,
    energy_gain,
    energy_multiplier_for,
    energy_rule_for,
)
from app.sim.phases.targeting import is_alive
from app.sim.world import World


class EnergyPhase:
    name = "energy"

    def run(self, world: World, ctx: TickContext) -> None:
        for unit in world.units:
            if not is_alive(unit) or unit.ability_id is None:
                continue

            unit.energy_meters[ELAPSED_SECONDS] += ctx.seconds_per_tick

            rule = energy_rule_for(unit.schools, ctx.energy_rules)
            multiplier = energy_multiplier_for(unit.schools, ctx.multipliers[unit.side])
            unit.energy += energy_gain(unit.energy_meters, rule, multiplier)

            # A full gauge holds at full rather than banking past it. The
            # ability is available from this moment and the unit may sit on it
            # for a while (see `casting.py`); letting the overflow accumulate
            # would quietly reward holding with a faster *second* cast, which
            # is not a thing anyone asked the mechanic to do.
            ability = ctx.abilities.get(unit.ability_id)
            if ability is not None:
                unit.energy = min(unit.energy, ability.energy_cost)

            # Drained rather than rebuilt, so the dict keeps the insertion
            # order `new_energy_meters` gave it.
            for meter in ENERGY_METERS:
                unit.energy_meters[meter] = 0.0


energy_phase = EnergyPhase()
