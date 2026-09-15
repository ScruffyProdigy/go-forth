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
    station,
)
from app.sim.map import THREE_ZONE_MAP, chip_box, zone_by_id, zone_centre
from app.sim.orders import DEFEND_BASE, PUSH_ENEMY_BASE, Order, hold
from app.sim.rng import create_rng
from app.sim.types import Side, Vec2
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, World, create_world
from tests.sim.fixtures_units import ADEPT, HOUND

FULL_WIDTH = THREE_ZONE_MAP.size_width


def formation(order: Order, side: Side = "north", mages: int = 1, summons: int = 2) -> Formation:
    return derive_formation(order, side, mages, summons, FULL_WIDTH)


def mage_offsets(shape: Formation, mages: int) -> list[Vec2]:
    return list(shape.offsets[:mages])


def summon_offsets(shape: Formation, mages: int) -> list[Vec2]:
    return list(shape.offsets[mages:])


@pytest.mark.parametrize("order", [hold("A"), DEFEND_BASE, PUSH_ENEMY_BASE])
def test_every_order_puts_the_summons_in_front_of_the_mages(order: Order) -> None:
    shape = formation(order)

    assert all(summon.y > mage.y for summon in summon_offsets(shape, 1) for mage in mage_offsets(shape, 1))


@pytest.mark.parametrize("order", [hold("A"), DEFEND_BASE, PUSH_ENEMY_BASE])
def test_the_summon_line_is_the_front_rank_whichever_way_the_side_faces(order: Order) -> None:
    shape = formation(order, side="south")

    assert all(summon.y < mage.y for summon in summon_offsets(shape, 1) for mage in mage_offsets(shape, 1))


def test_push_brings_the_mages_close_behind_the_line() -> None:
    assert formation(PUSH_ENEMY_BASE).depth == MAGE_SETBACK_PUSH


@pytest.mark.parametrize("order", [hold("A"), DEFEND_BASE])
def test_hold_and_defend_set_the_mages_further_back(order: Order) -> None:
    assert formation(order).depth == MAGE_SETBACK_GUARDED
    assert formation(order).depth > formation(PUSH_ENEMY_BASE).depth


def test_a_troop_of_mages_alone_is_the_line_itself() -> None:
    assert formation(PUSH_ENEMY_BASE, mages=3, summons=0).depth == 0


def test_the_summon_line_fills_columns_before_it_adds_a_rank() -> None:
    shape = formation(hold("A"), summons=MAX_RANK_COLUMNS)
    line = summon_offsets(shape, 1)

    assert len({slot.y for slot in line}) == 1
    assert len({slot.x for slot in line}) == MAX_RANK_COLUMNS


def test_it_only_deepens_once_the_rank_is_full() -> None:
    shape = formation(hold("A"), summons=MAX_RANK_COLUMNS + 1)

    assert len({slot.y for slot in summon_offsets(shape, 1)}) == 2


def test_a_narrow_band_runs_out_of_columns_sooner() -> None:
    narrow = derive_formation(hold("A"), "north", 1, 10, FORMATION_SPACING * 3)

    assert narrow.columns == 3


def test_neighbours_in_a_rank_stand_a_spacing_apart() -> None:
    line = sorted(slot.x for slot in summon_offsets(formation(hold("A"), summons=4), 1))

    gaps = [round(b - a, 9) for a, b in itertools.pairwise(line)]
    assert gaps == [FORMATION_SPACING] * 3


def anchor(order: Order, side: Side = "north") -> Vec2:
    band = deployment_band(THREE_ZONE_MAP, side, 0, 1)
    return deployment_anchor(THREE_ZONE_MAP, side, order, band, formation(order, side))


@pytest.mark.parametrize("side", ["north", "south"])
def test_hold_starts_pressed_against_the_zone_facing_side_of_the_strip(side: Side) -> None:
    strip = THREE_ZONE_MAP.deployment[side]
    far_edge = strip.lane.end if side == "north" else strip.lane.start

    assert abs(anchor(hold("B"), side).y - far_edge) == FORMATION_SPACING / 2


@pytest.mark.parametrize("side", ["north", "south"])
def test_defend_starts_back_on_its_own_base_side_of_the_strip(side: Side) -> None:
    toward_enemy = 1 if side == "north" else -1

    assert (anchor(DEFEND_BASE, side).y - anchor(hold("B"), side).y) * toward_enemy < 0


@pytest.mark.parametrize("side", ["north", "south"])
def test_push_starts_as_far_forward_as_hold_does(side: Side) -> None:
    assert anchor(PUSH_ENEMY_BASE, side).y == anchor(hold("B"), side).y


def test_troops_share_the_strip_side_by_side_rather_than_stacking() -> None:
    bands = [deployment_band(THREE_ZONE_MAP, "north", index, 3) for index in range(3)]

    assert [band.start for band in bands] == [0, 125, 250]
    assert bands[-1].end == THREE_ZONE_MAP.size_width


def build(orders: dict[Side, Order], summons: int = 2, seed: int = 1) -> World:
    return create_world(
        THREE_ZONE_MAP,
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
    world = build({"north": hold("A"), "south": DEFEND_BASE})
    north = [unit for unit in world.units if unit.side == "north"]
    mage = next(unit for unit in north if unit.kind == "mage")

    assert all(
        summon.position.y - mage.position.y == MAGE_SETBACK_GUARDED
        for summon in north
        if summon.kind == "summon"
    )


def test_a_pushing_troop_starts_tighter_than_a_holding_one() -> None:
    pushing = build({"north": PUSH_ENEMY_BASE, "south": DEFEND_BASE})
    holding = build({"north": hold("A"), "south": DEFEND_BASE})

    def depth(world: World) -> float:
        north = [unit.position.y for unit in world.units if unit.side == "north"]
        return max(north) - min(north)

    assert depth(pushing) < depth(holding)


def test_a_defending_troop_starts_nearer_its_own_base_than_a_holding_one() -> None:
    defending = build({"north": DEFEND_BASE, "south": DEFEND_BASE})
    holding = build({"north": hold("A"), "south": DEFEND_BASE})

    def rearmost(world: World) -> float:
        return min(unit.position.y for unit in world.units if unit.side == "north")

    assert rearmost(defending) < rearmost(holding)


def test_a_big_troop_still_starts_inside_its_own_strip() -> None:
    world = build({"north": PUSH_ENEMY_BASE, "south": hold("C")}, summons=19)

    for unit in world.units:
        strip = THREE_ZONE_MAP.deployment[unit.side]
        assert strip.lane.start <= unit.position.y <= strip.lane.end
        assert strip.extent.start <= unit.position.x <= strip.extent.end


def test_a_holding_troop_walks_to_a_station_inside_its_own_zone() -> None:
    zone = zone_by_id(THREE_ZONE_MAP, "C")
    world = build({"north": hold("C"), "south": DEFEND_BASE}, summons=19)

    for unit in (unit for unit in world.units if unit.side == "north"):
        assert zone.lane.start <= unit.destination.y <= zone.lane.end
        assert zone.extent.start <= unit.destination.x <= zone.extent.end


def test_a_station_outside_the_zone_is_pulled_back_into_it() -> None:
    zone = zone_by_id(THREE_ZONE_MAP, "A")
    far_out = station(hold("A"), "north", Vec2(0, -400), THREE_ZONE_MAP)

    assert zone.lane.start <= far_out.y <= zone.lane.end


def test_no_station_lands_in_the_corner_the_zone_chip_needs() -> None:
    zone = zone_by_id(THREE_ZONE_MAP, "A")
    across, down = chip_box(THREE_ZONE_MAP, zone)
    centre = zone_centre(zone)
    into_the_corner = Vec2(across.start - centre.x + 10, down.start - centre.y + 10)

    spot = station(hold("A"), "north", into_the_corner, THREE_ZONE_MAP)

    assert not (across.start <= spot.x < across.end and down.start <= spot.y < down.end)


def test_a_pushing_troop_walks_at_the_enemy_base() -> None:
    world = build({"north": PUSH_ENEMY_BASE, "south": DEFEND_BASE})
    base = THREE_ZONE_MAP.bases["south"].position

    for unit in (unit for unit in world.units if unit.side == "north"):
        assert abs(unit.destination.y - base.y) <= MAGE_SETBACK_GUARDED
