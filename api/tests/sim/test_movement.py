"""Movement: walking to the station the order derived, and what stops it."""

from __future__ import annotations

from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import TickContext, create_tick_context
from app.sim.geometry import distance
from app.sim.map import THREE_ZONE_MAP
from app.sim.orders import DEFEND_BASE, PUSH_ENEMY_BASE
from app.sim.phases.movement import engagement_standoff, movement_phase
from app.sim.phases.targeting import acquire_target
from app.sim.rng import create_rng
from app.sim.schools import resolve_side_multipliers
from app.sim.types import SIDES, Vec2
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, Unit, World, create_world
from tests.sim.fixtures_units import ADEPT, HOUND

OFF_THE_BOARD = Vec2(-1000, -1000)
STEP = HOUND.speed / DEFAULT_SIM_CONFIG.tick_rate

CHARGE = BattleSetup(
    unit_types=[ADEPT, HOUND],
    armies=[
        ArmySetup(
            side=side,
            troops=[
                TroopSetup(
                    order=PUSH_ENEMY_BASE if side == "north" else DEFEND_BASE,
                    mages=[RosterEntry("ember-adept")],
                    summons=[RosterEntry("cinder-hound")],
                )
            ],
        )
        for side in SIDES
    ],
)


def context() -> TickContext:
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=THREE_ZONE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(5),
    )


def field() -> tuple[World, Unit, Unit]:
    """A north hunter mid-map with a station at the far base, and one enemy."""
    world = create_world(THREE_ZONE_MAP, CHARGE, create_rng(5))
    for unit in world.units:
        unit.position = OFF_THE_BOARD

    hunter = next(unit for unit in world.units if unit.side == "north" and unit.kind == "summon")
    enemy = next(unit for unit in world.units if unit.side == "south" and unit.kind == "summon")
    hunter.position = Vec2(187.5, 200)
    hunter.destination = THREE_ZONE_MAP.bases["south"].position
    return world, hunter, enemy


def test_a_unit_walks_toward_the_station_its_order_gave_it() -> None:
    world, hunter, _ = field()

    movement_phase.run(world, context())

    assert hunter.position.y > 200


def test_it_covers_speed_times_the_tick_length() -> None:
    world, hunter, _ = field()
    before = hunter.position

    movement_phase.run(world, context())

    assert abs(distance(before, hunter.position) - STEP) < 1e-9


def test_it_stops_for_an_enemy_it_meets_on_the_way() -> None:
    world, hunter, enemy = field()
    enemy.position = Vec2(187.5, 200 + hunter.range)
    before = hunter.position

    movement_phase.run(world, context())

    assert hunter.position == before


def test_it_resumes_once_the_way_is_clear_again() -> None:
    world, hunter, enemy = field()
    enemy.position = Vec2(187.5, 200 + hunter.range)
    movement_phase.run(world, context())

    enemy.hp = 0
    movement_phase.run(world, context())

    assert hunter.position.y > 200


def test_it_never_closes_nearer_than_its_engagement_standoff() -> None:
    world, hunter, enemy = field()
    enemy.position = Vec2(187.5, 200 + hunter.range + 1)

    movement_phase.run(world, context())

    assert distance(hunter.position, enemy.position) >= engagement_standoff(hunter)


def test_a_unit_that_passes_an_enemy_off_axis_ends_up_able_to_shoot_it() -> None:
    """The other half of the standoff, and the half that was missing.

    "Never close nearer than the standoff" is satisfied perfectly by a unit that
    never gets near anything, so on its own it is not evidence of anything. This
    is the complementary property: a unit whose path takes it inside weapon range
    of an enemy ends up in a position to fire.

    Off-axis on purpose. Walking straight at something is the case that works
    under any rule — a step along the line of approach closes the distance by its
    own length, so an exact boundary is reachable. Walking *past* something
    closes it by less, which is where a standoff pinned to the boundary itself
    leaves a unit converging on its own weapon range for ever: unable to shoot
    because it is a hair outside, unable to walk on because its slack is spent.
    Measured before the fix, a hound sat frozen at 20.000000000000018 against a
    range of 20, alive and out of the battle permanently."""
    world, hunter, enemy = field()
    for unit in world.units:
        unit.speed = 0
    hunter.speed = HOUND.speed
    hunter.position = Vec2(100, 100)
    hunter.destination = Vec2(100, 500)
    # Its path passes 10 to the side of the enemy — comfortably within reach.
    enemy.position = Vec2(110, 400)

    for _ in range(3000):
        before = hunter.position
        movement_phase.run(world, context())
        if hunter.position == before:
            break

    assert acquire_target(world, hunter) is not None
    assert distance(hunter.position, enemy.position) <= hunter.range


def test_that_gap_is_what_keeps_two_ranks_readable() -> None:
    """JQ-243: ranks that end up in contact read as one scrum rather than as two
    armies. The separation is a placement rule, not a rendering trick."""
    world, hunter, enemy = field()
    enemy.position = Vec2(187.5, 200 + hunter.range + STEP / 2)

    movement_phase.run(world, context())

    assert distance(hunter.position, enemy.position) >= 16


def test_it_stops_at_the_edge_of_the_base_plate_rather_than_on_it() -> None:
    world, hunter, _ = field()
    plate = THREE_ZONE_MAP.bases["south"]
    hunter.position = Vec2(plate.position.x, plate.position.y - plate.footprint_radius - STEP / 2)

    movement_phase.run(world, context())

    assert distance(hunter.position, plate.position) == plate.footprint_radius


def test_a_unit_that_cannot_walk_stays_put() -> None:
    world, hunter, _ = field()
    hunter.speed = 0
    before = hunter.position

    movement_phase.run(world, context())

    assert hunter.position == before
