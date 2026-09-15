"""Orders: turning each troop's one verb into a place for each of its units.

Runs first in the tick, before anything moves. It rewrites every unit's
destination from its troop's order and its derived formation slot — every tick,
unconditionally — which is what makes "return to your assigned destination after
a bounded diversion" (JQ-296) free: a behaviour layer that stops overriding a
unit's destination gets the assigned station back on the next tick without any
bookkeeping of its own.

Nothing here reads a position from a plan. The order is the input; the station is
derived.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.formation import station
from app.sim.world import World, orders_by_troop


class OrdersPhase:
    name = "orders"

    def run(self, world: World, ctx: TickContext) -> None:
        orders = orders_by_troop(world)

        for unit in world.units:
            unit.destination = station(
                orders[unit.troop_id],
                unit.side,
                unit.formation_offset,
                ctx.map_config,
            )


orders_phase = OrdersPhase()
