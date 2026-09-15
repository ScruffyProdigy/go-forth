"""Zone control: who holds what, what it pays, and when it flips."""

from __future__ import annotations

from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import TickContext, create_tick_context
from app.sim.events import BattleEvent
from app.sim.map import THREE_ZONE_MAP, zone_by_id, zone_centre
from app.sim.orders import DEFEND_BASE, hold
from app.sim.phases.scoring import scoring_phase
from app.sim.rng import create_rng
from app.sim.schools import resolve_side_multipliers
from app.sim.types import SIDES, Side, Vec2
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, Unit, World, create_world
from app.sim.zones import zone_occupancy
from tests.sim.fixtures_units import ADEPT, HOUND

#: Far outside every zone, so a unit parked here holds nothing.
OFF_THE_BOARD = Vec2(-1000, -1000)
B = zone_by_id(THREE_ZONE_MAP, "B")
MIDDLE_OF_B = zone_centre(B)

TWO_EACH = BattleSetup(
    unit_types=[ADEPT, HOUND],
    armies=[
        ArmySetup(
            side=side,
            troops=[
                TroopSetup(
                    order=hold("B") if side == "north" else DEFEND_BASE,
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


def cleared() -> World:
    """A battle with everyone parked off the board, ready to be placed by hand."""
    world = create_world(THREE_ZONE_MAP, TWO_EACH, create_rng(5))
    for unit in world.units:
        unit.position = OFF_THE_BOARD
    return world


def summon(world: World, side: Side) -> Unit:
    return next(unit for unit in world.units if unit.side == side and unit.kind == "summon")


def flips(events: tuple[BattleEvent, ...]) -> list[BattleEvent]:
    return [event for event in events if event.type == "zoneFlip"]


def test_a_zone_with_one_side_in_it_is_held_by_that_side() -> None:
    world = cleared()
    summon(world, "north").position = MIDDLE_OF_B

    scoring_phase.run(world, context())

    assert world.zone_holders["B"] == "north"


def test_the_holder_is_paid_the_zones_rate_every_tick() -> None:
    world, ctx = cleared(), context()
    summon(world, "north").position = MIDDLE_OF_B

    for _ in range(3):
        scoring_phase.run(world, ctx)

    assert world.zone_score["north"] == 3 * B.points_per_tick
    assert world.zone_score["south"] == 0


def test_a_contested_zone_scores_for_nobody() -> None:
    world = cleared()
    summon(world, "north").position = MIDDLE_OF_B
    summon(world, "south").position = MIDDLE_OF_B

    scoring_phase.run(world, context())

    assert world.zone_holders["B"] is None
    assert world.zone_score == {"north": 0, "south": 0}


def test_an_empty_zone_scores_for_nobody() -> None:
    world = cleared()

    scoring_phase.run(world, context())

    assert world.zone_holders == {"A": None, "B": None, "C": None}
    assert world.zone_score == {"north": 0, "south": 0}


def test_being_outnumbered_does_not_matter_only_being_alone_does() -> None:
    world = cleared()
    for unit in (unit for unit in world.units if unit.side == "north"):
        unit.position = MIDDLE_OF_B
    summon(world, "south").position = MIDDLE_OF_B

    scoring_phase.run(world, context())

    assert world.zone_holders["B"] is None


def test_a_unit_brought_to_zero_this_tick_has_already_stopped_holding() -> None:
    world = cleared()
    holder = summon(world, "north")
    holder.position = MIDDLE_OF_B
    holder.hp = 0

    scoring_phase.run(world, context())

    assert world.zone_holders["B"] is None


def test_a_zone_flip_is_emitted_when_the_holder_changes() -> None:
    world, ctx = cleared(), context()
    summon(world, "north").position = MIDDLE_OF_B

    scoring_phase.run(world, ctx)

    assert [event.zone_id for event in flips(ctx.emitter.events)] == ["B"]


def test_a_flip_carries_the_swing_in_income_it_caused() -> None:
    world, ctx = cleared(), context()
    summon(world, "north").position = MIDDLE_OF_B

    scoring_phase.run(world, ctx)

    assert flips(ctx.emitter.events)[0].swing.zone_score == {
        "north": B.points_per_tick,
        "south": 0,
    }


def test_taking_a_zone_off_the_other_side_swings_both_ways() -> None:
    world, ctx = cleared(), context()
    south = summon(world, "south")
    south.position = MIDDLE_OF_B
    scoring_phase.run(world, ctx)
    ctx.emitter.drain()

    south.position = OFF_THE_BOARD
    summon(world, "north").position = MIDDLE_OF_B
    scoring_phase.run(world, ctx)

    assert flips(ctx.emitter.events)[0].swing.zone_score == {
        "north": B.points_per_tick,
        "south": -B.points_per_tick,
    }


def test_losing_a_zone_to_nobody_carries_the_loss_alone() -> None:
    world, ctx = cleared(), context()
    north = summon(world, "north")
    north.position = MIDDLE_OF_B
    scoring_phase.run(world, ctx)
    ctx.emitter.drain()

    north.position = OFF_THE_BOARD
    scoring_phase.run(world, ctx)

    assert flips(ctx.emitter.events)[0].swing.zone_score == {"north": -B.points_per_tick, "south": 0}


def test_holding_a_zone_quietly_emits_nothing_after_the_flip() -> None:
    world, ctx = cleared(), context()
    summon(world, "north").position = MIDDLE_OF_B

    for _ in range(5):
        scoring_phase.run(world, ctx)

    assert len(flips(ctx.emitter.events)) == 1


def test_ownership_is_not_sticky_a_zone_stops_paying_when_it_empties() -> None:
    world, ctx = cleared(), context()
    north = summon(world, "north")
    north.position = MIDDLE_OF_B
    scoring_phase.run(world, ctx)
    north.position = OFF_THE_BOARD

    for _ in range(4):
        scoring_phase.run(world, ctx)

    assert world.zone_score["north"] == B.points_per_tick


def test_occupancy_reports_every_zone_in_map_order() -> None:
    world = cleared()
    summon(world, "north").position = MIDDLE_OF_B

    occupancy = zone_occupancy(world, THREE_ZONE_MAP)

    assert [entry.zone.id for entry in occupancy] == ["A", "B", "C"]
    assert occupancy[1].counts == {"north": 1, "south": 0}
    assert occupancy[1].holder == "north"
