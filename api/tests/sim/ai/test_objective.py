"""The read-only seam onto JQ-287's orders, and the fixtures standing in for it.

JQ-287 is in flight, so half of these run against a `Troop` with an `order`
attached by hand — the shape their contract publishes, not their code. When slice
B lands these become tests of the real thing without changing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.objective import PUSH_ENEMY_BASE, ObjectiveFixtures, objective_for
from app.sim.map import THREE_ZONE_MAP
from app.sim.types import Vec2
from app.sim.world import Unit, World
from tests.sim.ai.helpers import make_unit, make_world
from tests.sim.fixtures_units import HOUND

MIDFIELD = Vec2(180, 300)
SOUTH_BASE = THREE_ZONE_MAP.bases["south"].position


@dataclass(frozen=True)
class FakeOrder:
    """JQ-287's `Order`, as far as this module is concerned: a `kind`."""

    kind: str


def lone_hound() -> tuple[World, Unit]:
    world = make_world([make_unit("north-t0-u0", HOUND, "north", MIDFIELD)])
    return world, world.units[0]


def test_without_orders_a_unit_falls_back_to_marching_on_the_enemy_base() -> None:
    """Slice A's behavior, which is what has to hold until slice B merges."""
    world, unit = lone_hound()

    objective = objective_for(world, unit, THREE_ZONE_MAP)

    assert objective.station == SOUTH_BASE
    assert objective.may_attack_base


def test_fixtures_can_supply_a_station_while_jq_287_is_in_flight() -> None:
    world, unit = lone_hound()
    fixtures = ObjectiveFixtures(stations={"north-t0": Vec2(120, 260)})

    objective = objective_for(world, unit, THREE_ZONE_MAP, fixtures)

    assert objective.station == Vec2(120, 260)


def test_fixtures_can_withhold_base_permission_from_a_troop() -> None:
    world, unit = lone_hound()
    fixtures = ObjectiveFixtures(push_troops=frozenset({"north-t1"}))

    objective = objective_for(world, unit, THREE_ZONE_MAP, fixtures)

    assert not objective.may_attack_base


def test_an_order_supersedes_the_fixtures_entirely() -> None:
    """The moment JQ-287's field is present, nothing reads the stand-in."""
    world, unit = lone_hound()
    setattr(world.troops[0], "order", FakeOrder(kind="holdZone"))  # noqa: B010
    unit.destination = Vec2(200, 280)

    objective = objective_for(
        world, unit, THREE_ZONE_MAP, ObjectiveFixtures(stations={"north-t0": Vec2(1, 1)})
    )

    assert objective.station == Vec2(200, 280)
    assert not objective.may_attack_base


def test_only_a_troop_pushing_the_enemy_base_may_take_it() -> None:
    world, unit = lone_hound()

    for kind, allowed in (("holdZone", False), ("defendBase", False), (PUSH_ENEMY_BASE, True)):
        setattr(world.troops[0], "order", FakeOrder(kind=kind))  # noqa: B010

        assert objective_for(world, unit, THREE_ZONE_MAP).may_attack_base is allowed


def test_a_unit_under_orders_with_no_station_yet_still_has_somewhere_to_be() -> None:
    """The orders phase writes `destination`; this covers the tick before it has."""
    world, unit = lone_hound()
    setattr(world.troops[0], "order", FakeOrder(kind=PUSH_ENEMY_BASE))  # noqa: B010

    assert objective_for(world, unit, THREE_ZONE_MAP).station == SOUTH_BASE
