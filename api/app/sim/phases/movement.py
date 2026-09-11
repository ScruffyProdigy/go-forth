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
    return ctx.map_config.bases[opposing(unit.side)].position


class MovementPhase:
    name = "movement"

    def run(self, world: World, ctx: TickContext) -> None:
        for unit in world.units:
            if not is_alive(unit) or unit.speed == 0:
                continue
            # Already in reach of something: hold the gap and let combat work.
            if acquire_target(world, unit) is not None:
                continue

            unit.position = move_toward(
                unit.position,
                _destination_for(unit, ctx),
                unit.speed * ctx.seconds_per_tick,
            )


movement_phase = MovementPhase()
