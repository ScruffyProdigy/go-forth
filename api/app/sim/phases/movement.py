"""Movement.

Units advance on a position and stop at weapon range rather than walking into the
enemy — two ranks in contact sit ~20 px apart and read as one blob, and the
engagement gap is what hands the front line back (JQ-243).

The position they advance on is the enemy base, because slice A has no orders.
Orders, derived formations, and engage-en-route are JQ-287, which replaces
`_destination_for` with the troop's assigned objective.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.geometry import move_toward
from app.sim.phases.targeting import acquire_target, is_alive
from app.sim.types import Vec2, opposing
from app.sim.world import Unit, World


def _destination_for(unit: Unit, ctx: TickContext) -> Vec2:
    """Where this unit walks. Its assigned station if anything has set one.

    JQ-287's orders phase writes `unit.destination` from the troop's order and
    JQ-328's decision phase may divert it for a tick. With neither in play it is
    None and slice A's behavior stands: everyone marches on the enemy base.
    """
    if unit.destination is not None:
        return unit.destination
    return ctx.map_config.bases[opposing(unit.side)].position


class MovementPhase:
    name = "movement"

    def run(self, world: World, ctx: TickContext) -> None:
        for unit in world.units:
            if not is_alive(unit) or unit.speed == 0:
                continue

            intent = unit.ai.intent if unit.ai is not None else None
            if intent is not None:
                # The decision phase already weighed standing still against
                # moving, danger included. Attacking and holding mean stay put;
                # advancing means go, even with an enemy in reach — pressing an
                # objective past a weak enemy is a decision, not an oversight.
                if intent.kind != "advance":
                    continue
            elif acquire_target(world, unit) is not None:
                # No decision loop: hold the gap and let combat work.
                continue

            unit.position = move_toward(
                unit.position,
                _destination_for(unit, ctx),
                unit.speed * ctx.seconds_per_tick,
            )


movement_phase = MovementPhase()
