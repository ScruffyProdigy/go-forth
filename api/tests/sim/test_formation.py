"""Formations and start positions, both derived from the order and nothing else."""

from __future__ import annotations

import itertools

import pytest

from app.sim.formation import (
    FORMATION_SPACING,
    MAGE_SETBACK_GUARDED,
    MAGE_SETBACK_PUSH,
    MAX_RANK_COLUMNS,
    Formation,
    deployment_anchor,
    deployment_band,
    derive_formation,
    forward,
    station,
)
from app.sim.map import TWO_LANE_MAP, chip_box, hotspot_centre, hotspot_contains, zone_by_id
from app.sim.orders import DEFEND_BASE, PUSH_ENEMY_BASE, Order, hold
from app.sim.rng import create_rng
from app.sim.types import Side, Span, Vec2
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, Unit, World, create_world
from tests.sim.fixtures_units import ADEPT, HOUND

FULL_WIDTH = TWO_LANE_MAP.size_width


def formation(order: Order, side: Side = "north", mages: int = 1, summons: int = 2) -> Formation:
    return derive_formation(order, side, mages, summons, FULL_WIDTH)


def mage_offsets(shape: Formation, mages: int) -> list[Vec2]:
    return list(shape.offsets[:mages])


def summon_offsets(shape: Formation, mages: int) -> list[Vec2]:
    return list(shape.offsets[mages:])


@pytest.mark.parametrize("order", [hold("W"), DEFEND_BASE, PUSH_ENEMY_BASE])
def test_every_order_puts_the_summons_in_front_of_the_mages(order: Order) -> None:
    shape = formation(order)

    assert all(summon.y > mage.y for summon in summon_offsets(shape, 1) for mage in mage_offsets(shape, 1))


@pytest.mark.parametrize("order", [hold("W"), DEFEND_BASE, PUSH_ENEMY_BASE])
def test_the_summon_line_is_the_front_rank_whichever_way_the_side_faces(order: Order) -> None:
    shape = formation(order, side="south")

    assert all(summon.y < mage.y for summon in summon_offsets(shape, 1) for mage in mage_offsets(shape, 1))


def test_push_brings_the_mages_close_behind_the_line() -> None:
    assert formation(PUSH_ENEMY_BASE).depth == MAGE_SETBACK_PUSH


@pytest.mark.parametrize("order", [hold("W"), DEFEND_BASE])
def test_hold_and_defend_set_the_mages_further_back(order: Order) -> None:
    assert formation(order).depth == MAGE_SETBACK_GUARDED
    assert formation(order).depth > formation(PUSH_ENEMY_BASE).depth


def test_a_troop_of_mages_alone_is_the_line_itself() -> None:
    assert formation(PUSH_ENEMY_BASE, mages=3, summons=0).depth == 0


def test_the_summon_line_fills_columns_before_it_adds_a_rank() -> None:
    shape = formation(hold("W"), summons=MAX_RANK_COLUMNS)
    line = summon_offsets(shape, 1)

    assert len({slot.y for slot in line}) == 1
    assert len({slot.x for slot in line}) == MAX_RANK_COLUMNS


def test_it_only_deepens_once_the_rank_is_full() -> None:
    shape = formation(hold("W"), summons=MAX_RANK_COLUMNS + 1)

    assert len({slot.y for slot in summon_offsets(shape, 1)}) == 2


def test_a_narrow_band_runs_out_of_columns_sooner() -> None:
    narrow = derive_formation(hold("W"), "north", 1, 10, FORMATION_SPACING * 3)

    assert narrow.columns == 3


def test_neighbours_in_a_rank_stand_a_spacing_apart() -> None:
    line = sorted(slot.x for slot in summon_offsets(formation(hold("W"), summons=4), 1))

    gaps = [round(b - a, 9) for a, b in itertools.pairwise(line)]
    assert gaps == [FORMATION_SPACING] * 3


def band(order: Order, side: Side = "north", share_index: int = 0, share_count: int = 1) -> Span:
    return deployment_band(TWO_LANE_MAP, side, order, share_index, share_count)


def anchor(order: Order, side: Side = "north") -> Vec2:
    """Where the troop's origin rank stands at the whistle."""
    return deployment_anchor(TWO_LANE_MAP, side, order, band(order, side), formation(order, side))


def front_rank(order: Order, side: Side = "north") -> float:
    """Where the rank facing the enemy stands, whichever rank the order anchored on."""
    return anchor(order, side).y + formation(order, side).lead * forward(side)


@pytest.mark.parametrize("side", ["north", "south"])
def test_hold_starts_pressed_against_the_lane_facing_side_of_the_strip(side: Side) -> None:
    strip = TWO_LANE_MAP.deployment[side]
    far_edge = strip.lane.end if side == "north" else strip.lane.start

    assert abs(front_rank(hold("E"), side) - far_edge) == FORMATION_SPACING / 2


@pytest.mark.parametrize("side", ["north", "south"])
def test_defend_starts_back_on_its_own_base_side_of_the_strip(side: Side) -> None:
    toward_enemy = 1 if side == "north" else -1

    assert (front_rank(DEFEND_BASE, side) - front_rank(hold("E"), side)) * toward_enemy < 0


@pytest.mark.parametrize("side", ["north", "south"])
def test_push_starts_as_far_forward_as_hold_does(side: Side) -> None:
    assert front_rank(PUSH_ENEMY_BASE, side) == front_rank(hold("E"), side)


@pytest.mark.parametrize("side", ["north", "south"])
def test_a_holding_troop_starts_in_front_of_the_lane_it_was_sent_to(side: Side) -> None:
    """Derived from the order, so a troop walks straight up its own lane instead
    of setting off diagonally across the map."""
    for zone in TWO_LANE_MAP.zones:
        lateral = anchor(hold(zone.id), side).x
        assert zone.extent.start <= lateral <= zone.extent.end


def test_troops_sharing_a_lane_share_its_band_side_by_side() -> None:
    west = zone_by_id(TWO_LANE_MAP, "W")
    bands = [band(hold("W"), "north", index, 3) for index in range(3)]

    assert bands[0].start == west.extent.start
    assert bands[-1].end == west.extent.end
    assert bands[0].end == bands[1].start and bands[1].end == bands[2].start


def test_troops_under_different_lane_orders_do_not_share_a_band() -> None:
    west, east = band(hold("W")), band(hold("E"))

    assert west.end <= east.start


def test_defend_and_push_are_not_about_a_lane_so_they_take_the_whole_strip() -> None:
    strip = TWO_LANE_MAP.deployment["north"]

    for order in (DEFEND_BASE, PUSH_ENEMY_BASE):
        assert band(order) == Span(strip.extent.start, strip.extent.end)


def build(orders: dict[Side, Order], summons: int = 2, seed: int = 1) -> World:
    return create_world(
        TWO_LANE_MAP,
        BattleSetup(
            unit_types=[ADEPT, HOUND],
            armies=[
                ArmySetup(
                    side=side,
                    troops=[
                        TroopSetup(
                            order=orders[side],
                            mages=[RosterEntry("ember-adept")],
                            summons=[RosterEntry("cinder-hound", summons)],
                        )
                    ],
                )
                for side in ("north", "south")
            ],
        ),
        create_rng(seed),
    )


def test_a_troop_starts_in_the_shape_its_order_derived() -> None:
    world = build({"north": hold("W"), "south": DEFEND_BASE})
    north = [unit for unit in world.units if unit.side == "north"]
    mage = next(unit for unit in north if unit.kind == "mage")

    assert all(
        summon.position.y - mage.position.y == MAGE_SETBACK_GUARDED
        for summon in north
        if summon.kind == "summon"
    )


def test_a_pushing_troop_starts_tighter_than_a_holding_one() -> None:
    pushing = build({"north": PUSH_ENEMY_BASE, "south": DEFEND_BASE})
    holding = build({"north": hold("W"), "south": DEFEND_BASE})

    def depth(world: World) -> float:
        north = [unit.position.y for unit in world.units if unit.side == "north"]
        return max(north) - min(north)

    assert depth(pushing) < depth(holding)


def test_a_defending_troop_starts_nearer_its_own_base_than_a_holding_one() -> None:
    defending = build({"north": DEFEND_BASE, "south": DEFEND_BASE})
    holding = build({"north": hold("W"), "south": DEFEND_BASE})

    def rearmost(world: World) -> float:
        return min(unit.position.y for unit in world.units if unit.side == "north")

    assert rearmost(defending) < rearmost(holding)


def test_a_big_troop_still_starts_inside_its_own_strip() -> None:
    world = build({"north": PUSH_ENEMY_BASE, "south": hold("E")}, summons=19)

    for unit in world.units:
        strip = TWO_LANE_MAP.deployment[unit.side]
        assert strip.lane.start <= unit.position.y <= strip.lane.end
        assert strip.extent.start <= unit.position.x <= strip.extent.end


def test_a_holding_troop_walks_to_a_station_inside_its_own_zone() -> None:
    zone = zone_by_id(TWO_LANE_MAP, "E")
    world = build({"north": hold("E"), "south": DEFEND_BASE}, summons=19)

    for unit in (unit for unit in world.units if unit.side == "north"):
        assert zone.lane.start <= unit.destination.y <= zone.lane.end
        assert zone.extent.start <= unit.destination.x <= zone.extent.end


def test_a_station_outside_the_zone_is_pulled_back_into_it() -> None:
    zone = zone_by_id(TWO_LANE_MAP, "W")
    far_out = station(hold("W"), "north", Vec2(0, -400), TWO_LANE_MAP)

    assert zone.lane.start <= far_out.y <= zone.lane.end


def test_no_station_lands_in_the_corner_the_zone_chip_needs() -> None:
    zone = zone_by_id(TWO_LANE_MAP, "W")
    across, down = chip_box(TWO_LANE_MAP, zone)
    centre = hotspot_centre(TWO_LANE_MAP, zone)
    into_the_corner = Vec2(across.start - centre.x + 10, down.start - centre.y + 10)

    spot = station(hold("W"), "north", into_the_corner, TWO_LANE_MAP)

    assert not (across.start <= spot.x < across.end and down.start <= spot.y < down.end)


def test_a_pushing_troop_walks_at_the_enemy_base() -> None:
    world = build({"north": PUSH_ENEMY_BASE, "south": DEFEND_BASE})
    base = TWO_LANE_MAP.bases["south"].position

    for unit in (unit for unit in world.units if unit.side == "north"):
        assert abs(unit.destination.y - base.y) <= MAGE_SETBACK_GUARDED


def north_units(world: World, kind: str) -> list[Unit]:
    return [unit for unit in world.units if unit.side == "north" and unit.kind == kind]


def test_a_holding_troop_sends_its_mage_to_stand_on_the_hotspot() -> None:
    """Hold anchors on the mage rank, because a lane is held by a mage standing
    in its hotspot and nothing else."""
    world = build({"north": hold("W"), "south": DEFEND_BASE})
    point = hotspot_centre(TWO_LANE_MAP, zone_by_id(TWO_LANE_MAP, "W"))

    assert [mage.destination for mage in north_units(world, "mage")] == [point]


def test_and_its_summons_screen_the_ground_past_the_point() -> None:
    """So getting into scoring position and winning the ground in front of it
    are the same act."""
    world = build({"north": hold("W"), "south": DEFEND_BASE})
    point = hotspot_centre(TWO_LANE_MAP, zone_by_id(TWO_LANE_MAP, "W"))

    # North fights southward, so "in front" is further down the map.
    assert all(summon.destination.y > point.y for summon in north_units(world, "summon"))


def test_push_still_anchors_on_the_line_so_the_mage_trails_it() -> None:
    world = build({"north": PUSH_ENEMY_BASE, "south": DEFEND_BASE})
    mage = north_units(world, "mage")[0]

    assert all(summon.destination.y > mage.destination.y for summon in north_units(world, "summon"))
    assert mage.destination != TWO_LANE_MAP.bases["south"].position


def test_only_hold_builds_its_formation_around_the_mage() -> None:
    assert formation(hold("W")).lead == MAGE_SETBACK_GUARDED
    assert formation(DEFEND_BASE).lead == 0
    assert formation(PUSH_ENEMY_BASE).lead == 0


@pytest.mark.parametrize("side", ["north", "south"])
def test_a_defending_station_never_leaves_its_own_deployment_strip(side: Side) -> None:
    """Half of why keeping your mages at home cannot score. The other half is
    that a deployment strip may not overlap a zone, which the map validator
    enforces — together they make "turtling earns nothing" a consequence of the
    geometry rather than something the battle happens to produce."""
    strip = TWO_LANE_MAP.deployment[side]
    reach = max(TWO_LANE_MAP.size_width, TWO_LANE_MAP.size_height)

    for dx in (-reach, -40, 0, 40, reach):
        for dy in (-reach, -40, 0, 40, reach):
            spot = station(DEFEND_BASE, side, Vec2(dx, dy), TWO_LANE_MAP)

            assert strip.extent.start <= spot.x <= strip.extent.end
            assert strip.lane.start <= spot.y <= strip.lane.end


@pytest.mark.parametrize("side", ["north", "south"])
def test_so_no_defending_station_can_reach_a_scoring_point(side: Side) -> None:
    reach = max(TWO_LANE_MAP.size_width, TWO_LANE_MAP.size_height)

    for dy in (-reach, -40, 0, 40, reach):
        spot = station(DEFEND_BASE, side, Vec2(0, dy), TWO_LANE_MAP)

        assert not any(hotspot_contains(TWO_LANE_MAP, zone, spot) for zone in TWO_LANE_MAP.zones)
