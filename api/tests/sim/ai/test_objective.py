"""Reading JQ-287's order contract, now that it is real.

An earlier version of these ran against a `Troop` with an `order` attached by
hand, because slice B had not landed and this module read the order structurally
rather than importing it. That scaffolding is gone — these call the same
functions the orders phase does.
"""

from __future__ import annotations

from app.sim.ai.objective import objective_for
from app.sim.orders import DEFEND_BASE, PUSH_ENEMY_BASE, Order, hold
from app.sim.types import Vec2
from app.sim.world import Unit, World
from tests.sim.ai.helpers import make_unit, make_world
from tests.sim.fixtures_units import HOUND

MIDFIELD = Vec2(180, 300)


def hound_under(order: Order) -> tuple[World, Unit]:
    unit = make_unit("north-t0-u0", HOUND, "north", MIDFIELD)
    return make_world([unit], orders={"north-t0": order}), unit


def test_the_station_is_whatever_the_orders_phase_last_wrote() -> None:
    """Not recomputed here. The orders phase owns deriving it; this reads it."""
    world, unit = hound_under(PUSH_ENEMY_BASE)
    unit.destination = Vec2(120, 260)

    assert objective_for(world, unit).station == Vec2(120, 260)


def test_only_a_troop_pushing_the_enemy_base_may_take_it() -> None:
    for order, allowed in ((hold("B"), False), (DEFEND_BASE, False), (PUSH_ENEMY_BASE, True)):
        world, unit = hound_under(order)

        assert objective_for(world, unit).may_attack_base is allowed


def test_the_permission_follows_the_troop_rather_than_the_unit() -> None:
    """Two units, two troops, one field — each reads its own troop's order."""
    pusher = make_unit("north-t0-u0", HOUND, "north", MIDFIELD, troop_id="north-t0")
    holder = make_unit("north-t1-u0", HOUND, "north", MIDFIELD, troop_id="north-t1")
    world = make_world([pusher, holder], orders={"north-t0": PUSH_ENEMY_BASE, "north-t1": hold("B")})

    assert objective_for(world, pusher).may_attack_base
    assert not objective_for(world, holder).may_attack_base
