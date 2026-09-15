"""The decision phase: every unit picks what it is doing this tick.

Sits between `orders` and `movement`. That is the one point in the tick where
every unit's assigned station is fresh — JQ-287's orders phase has just written
it — and nothing has moved yet, so every unit decides against the same field.

It **commits, it does not act.** The chosen action becomes `unit.ai.intent`, and
`movement` walks it and `combat` swings it. Deciding and executing in one phase
would mean the field shifted underneath units later in the list, which is both
unfair and unreproducible in any way a reader could follow.

Each troop coordinates **before** any of its units decides. That ordering is the
whole of what makes an assignment worth having: every member of the troop then
reads the same assignments against the same field, so exactly one of them sees
itself asked to answer a given threat and the rest see it already answered.
Coordinating inside the per-unit loop would mean a unit deciding against an
allocation that was still being made, which is neither fair nor followable.

A unit with no behavior data attached is left completely alone, intent and all.
A battle that ships no behavior library therefore runs exactly as it did before
this phase existed — which is what keeps three parallel slices honest while none
of them has merged.
"""

from __future__ import annotations

from app.sim.ai.attach import resolve_missing
from app.sim.ai.coordination import assignment_for, coordinate
from app.sim.ai.decide import decide, intent_of
from app.sim.ai.intent import Assignment
from app.sim.ai.observe import observe
from app.sim.context import TickContext
from app.sim.phases.targeting import is_alive
from app.sim.types import UnitId
from app.sim.world import Troop, World


class DecisionPhase:
    """Observe, generate, score, select — for each living unit, in world order."""

    name = "decision"

    def run(self, world: World, ctx: TickContext) -> None:
        # A resummoned summon (JQ-289) is built after `create_world`, so it
        # arrives with no behaviour — and a unit with no behaviour is skipped
        # below, which would leave it walking at its station while its whole
        # troop decided. Cheap: it returns immediately once everyone has one.
        resolve_missing(world.units, world.troops, world.behavior, ctx.unit_types)

        # `world.troops` is a list, so this runs in a fixed order — and it runs
        # to completion before anything decides.
        for troop in world.troops:
            coordinate(world, troop, world.tick, ctx.seconds_per_tick)

        troops = {troop.id: troop for troop in world.troops}

        for unit in world.units:
            if not is_alive(unit) or unit.ai is None:
                continue

            decision = decide(
                observe(
                    world,
                    unit,
                    ctx.map_config,
                    ctx.seconds_per_tick,
                    ctx.abilities,
                    assignment=_assignment(troops.get(unit.troop_id), unit.id),
                ),
                unit.ai.behavior,
                ctx.rng,
            )
            intent = intent_of(decision)
            unit.ai.intent = intent

            # Movement reads `unit.destination`, which the orders phase rewrites
            # next tick — so a diversion undoes itself and "return to your
            # station" needs no code at all.
            if intent.destination is not None:
                unit.destination = intent.destination


def _assignment(troop: Troop | None, unit_id: UnitId) -> Assignment | None:
    return assignment_for(troop, unit_id) if troop is not None else None


decision_phase = DecisionPhase()
