"""Lane control: who holds a hotspot, what it pays, and when it flips."""

from __future__ import annotations

from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import TickContext, create_tick_context
from app.sim.events import BattleEvent
from app.sim.map import TWO_LANE_MAP, hotspot_centre, zone_by_id
from app.sim.orders import DEFEND_BASE, hold
from app.sim.phases.scoring import scoring_phase
from app.sim.rng import create_rng
from app.sim.schools import resolve_side_multipliers
from app.sim.types import SIDES, Side, Vec2
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, Unit, World, create_world
from app.sim.zones import zone_occupancy
from tests.sim.fixtures_units import ADEPT, HOUND

#: Far outside every lane, so a unit parked here holds nothing.
OFF_THE_BOARD = Vec2(-1000, -1000)
WEST = zone_by_id(TWO_LANE_MAP, "W")
ON_THE_POINT = hotspot_centre(TWO_LANE_MAP, WEST)
#: Inside the west lane, but nowhere near its hotspot.
LURKING = Vec2(WEST.extent.start + 10, WEST.lane.start + 10)

TWO_EACH = BattleSetup(
    unit_types=[ADEPT, HOUND],
    armies=[
        ArmySetup(
            side=side,
            troops=[
                TroopSetup(
                    order=hold("W") if side == "north" else DEFEND_BASE,
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
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(5),
    )


def cleared() -> World:
    """A battle with everyone parked off the board, ready to be placed by hand."""
    world = create_world(TWO_LANE_MAP, TWO_EACH, create_rng(5))
    for unit in world.units:
        unit.position = OFF_THE_BOARD
    return world


def mage(world: World, side: Side) -> Unit:
    return next(unit for unit in world.units if unit.side == side and unit.kind == "mage")


def summon(world: World, side: Side) -> Unit:
    return next(unit for unit in world.units if unit.side == side and unit.kind == "summon")


def flips(events: tuple[BattleEvent, ...]) -> list[BattleEvent]:
    return [event for event in events if event.type == "zoneFlip"]


def test_a_mage_alone_on_the_hotspot_holds_the_lane() -> None:
    world = cleared()
    mage(world, "north").position = ON_THE_POINT

    scoring_phase.run(world, context())

    assert world.zone_holders["W"] == "north"


def test_a_summon_on_the_hotspot_holds_nothing() -> None:
    """Otherwise the lane goes to whoever owns the fastest disposable body, and
    committing the mage — the whole cost of scoring — stops being a decision."""
    world = cleared()
    summon(world, "north").position = ON_THE_POINT

    scoring_phase.run(world, context())

    assert world.zone_holders["W"] is None


def test_a_mage_in_the_lane_but_off_the_point_holds_nothing() -> None:
    """A lane is 369 deep. If standing anywhere in it counted, one straggler in a
    corner would deny it, and denial would stop being a combat outcome."""
    world = cleared()
    mage(world, "north").position = LURKING

    scoring_phase.run(world, context())

    assert world.zone_holders["W"] is None


def test_the_holder_is_paid_the_lanes_rate_every_tick() -> None:
    world, ctx = cleared(), context()
    mage(world, "north").position = ON_THE_POINT

    for _ in range(3):
        scoring_phase.run(world, ctx)

    assert world.zone_score["north"] == 3 * WEST.points_per_tick
    assert world.zone_score["south"] == 0


def test_two_mages_on_the_same_point_contest_it() -> None:
    world = cleared()
    mage(world, "north").position = ON_THE_POINT
    mage(world, "south").position = ON_THE_POINT

    scoring_phase.run(world, context())

    assert world.zone_holders["W"] is None
    assert world.zone_score == {"north": 0, "south": 0}


def test_an_empty_point_scores_for_nobody() -> None:
    world = cleared()

    scoring_phase.run(world, context())

    assert world.zone_holders == {"W": None, "E": None}
    assert world.zone_score == {"north": 0, "south": 0}


def test_an_escort_standing_over_the_point_does_not_contest_it() -> None:
    """The screen forms up past the hotspot; only the mage on it counts. A holder
    keeps scoring while enemy summons are all over it — under fire is the normal
    way to hold a lane."""
    world = cleared()
    mage(world, "north").position = ON_THE_POINT
    summon(world, "south").position = ON_THE_POINT

    scoring_phase.run(world, context())

    assert world.zone_holders["W"] == "north"


def test_a_mage_brought_to_zero_this_tick_has_already_stopped_holding() -> None:
    world = cleared()
    holder = mage(world, "north")
    holder.position = ON_THE_POINT
    holder.hp = 0

    scoring_phase.run(world, context())

    assert world.zone_holders["W"] is None


def test_a_zone_flip_is_emitted_when_the_holder_changes() -> None:
    world, ctx = cleared(), context()
    mage(world, "north").position = ON_THE_POINT

    scoring_phase.run(world, ctx)

    assert [event.zone_id for event in flips(ctx.emitter.events)] == ["W"]


def test_a_flip_carries_the_swing_in_income_it_caused() -> None:
    world, ctx = cleared(), context()
    mage(world, "north").position = ON_THE_POINT

    scoring_phase.run(world, ctx)

    assert flips(ctx.emitter.events)[0].swing.zone_score == {
        "north": WEST.points_per_tick,
        "south": 0,
    }


def test_taking_a_lane_off_the_other_side_swings_both_ways() -> None:
    world, ctx = cleared(), context()
    south = mage(world, "south")
    south.position = ON_THE_POINT
    scoring_phase.run(world, ctx)
    ctx.emitter.drain()

    south.position = OFF_THE_BOARD
    mage(world, "north").position = ON_THE_POINT
    scoring_phase.run(world, ctx)

    assert flips(ctx.emitter.events)[0].swing.zone_score == {
        "north": WEST.points_per_tick,
        "south": -WEST.points_per_tick,
    }


def test_stepping_off_the_point_carries_the_loss_alone() -> None:
    world, ctx = cleared(), context()
    north = mage(world, "north")
    north.position = ON_THE_POINT
    scoring_phase.run(world, ctx)
    ctx.emitter.drain()

    north.position = LURKING
    scoring_phase.run(world, ctx)

    assert flips(ctx.emitter.events)[0].swing.zone_score == {
        "north": -WEST.points_per_tick,
        "south": 0,
    }


def test_holding_a_lane_quietly_emits_nothing_after_the_flip() -> None:
    world, ctx = cleared(), context()
    mage(world, "north").position = ON_THE_POINT

    for _ in range(5):
        scoring_phase.run(world, ctx)

    assert len(flips(ctx.emitter.events)) == 1


def test_ownership_is_not_sticky_a_lane_stops_paying_when_it_is_abandoned() -> None:
    world, ctx = cleared(), context()
    north = mage(world, "north")
    north.position = ON_THE_POINT
    scoring_phase.run(world, ctx)
    north.position = OFF_THE_BOARD

    for _ in range(4):
        scoring_phase.run(world, ctx)

    assert world.zone_score["north"] == WEST.points_per_tick


def test_occupancy_reports_every_lane_in_map_order() -> None:
    world = cleared()
    mage(world, "north").position = ON_THE_POINT

    occupancy = zone_occupancy(world, TWO_LANE_MAP)

    assert [entry.zone.id for entry in occupancy] == ["W", "E"]
    assert occupancy[0].counts == {"north": 1, "south": 0}
    assert occupancy[0].holder == "north"


def test_occupancy_also_reports_everyone_in_the_lane_for_the_renderer() -> None:
    world = cleared()
    mage(world, "north").position = ON_THE_POINT
    summon(world, "north").position = LURKING
    summon(world, "south").position = LURKING

    west = zone_occupancy(world, TWO_LANE_MAP)[0]

    assert west.lane_counts == {"north": 2, "south": 1}
    assert west.counts == {"north": 1, "south": 0}
