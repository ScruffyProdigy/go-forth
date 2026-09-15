"""Orders: the whole of what a plan gives a troop."""

from __future__ import annotations

import copy
import dataclasses

import pytest

from app.sim.map import TWO_LANE_MAP, MapConfig, ZoneConfig, hotspot_centre, strip_centre
from app.sim.orders import (
    DEFEND_BASE,
    PUSH_ENEMY_BASE,
    Order,
    hold,
    legal_orders,
    may_attack_base,
    objective_position,
    validate_order,
)
from app.sim.rng import create_rng
from app.sim.types import Side, Span, Vec2
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, create_world, order_of
from tests.sim.fixtures_units import ADEPT, HOUND


def three_lane_map() -> MapConfig:
    """The same map with a third lane squeezed into the push corridor."""
    config = copy.deepcopy(TWO_LANE_MAP)
    config.zones[0].extent = Span(0, 110)
    config.zones[1].extent = Span(265, 375)
    config.zones.insert(1, ZoneConfig("M", Span(100, 469), Span(150, 225), 1))
    config.hotspot_size = 60
    return config


def test_the_two_lane_map_offers_exactly_four_orders() -> None:
    assert len(legal_orders(TWO_LANE_MAP)) == 4


def test_the_four_are_hold_each_lane_defend_and_push() -> None:
    assert legal_orders(TWO_LANE_MAP) == (
        hold("W"),
        hold("E"),
        DEFEND_BASE,
        PUSH_ENEMY_BASE,
    )


def test_four_is_a_fact_about_the_map_rather_than_a_constant() -> None:
    assert len(legal_orders(three_lane_map())) == 5


def test_a_hold_order_must_name_a_zone_the_map_has() -> None:
    with pytest.raises(ValueError, match="zone"):
        validate_order(hold("Z"), TWO_LANE_MAP)


def test_a_hold_order_must_name_some_zone() -> None:
    with pytest.raises(ValueError, match="name the zone"):
        validate_order(Order("holdZone"), TWO_LANE_MAP)


def test_defend_and_push_name_no_zone() -> None:
    with pytest.raises(ValueError, match="names no zone"):
        validate_order(Order("pushEnemyBase", "A"), TWO_LANE_MAP)


def test_a_verb_that_is_not_an_order_is_rejected() -> None:
    with pytest.raises(ValueError, match="not an order"):
        validate_order(Order("retreat"), TWO_LANE_MAP)  # type: ignore[arg-type]


def test_hold_forms_up_on_its_lanes_hotspot() -> None:
    assert objective_position(hold("E"), "north", TWO_LANE_MAP) == hotspot_centre(
        TWO_LANE_MAP, TWO_LANE_MAP.zones[1]
    )


def test_a_lane_is_the_same_lane_for_both_sides() -> None:
    """The whole point of dividing west to east: every lane is the same distance
    from both bases, so no order means 'turtle' to one player and 'deep strike'
    to the other."""
    north = objective_position(hold("E"), "north", TWO_LANE_MAP)
    south = objective_position(hold("E"), "south", TWO_LANE_MAP)

    assert north == south
    base_gap = TWO_LANE_MAP.bases["south"].position.y - TWO_LANE_MAP.bases["north"].position.y
    assert north.y == TWO_LANE_MAP.bases["north"].position.y + base_gap / 2


def test_defend_forms_up_in_front_of_its_own_base() -> None:
    assert objective_position(DEFEND_BASE, "north", TWO_LANE_MAP) == strip_centre(TWO_LANE_MAP, "north")


def test_push_walks_at_the_enemy_base() -> None:
    assert objective_position(PUSH_ENEMY_BASE, "north", TWO_LANE_MAP) == (
        TWO_LANE_MAP.bases["south"].position
    )


def test_only_push_may_attack_a_base() -> None:
    allowed = [order for order in legal_orders(TWO_LANE_MAP) if may_attack_base(order)]

    assert allowed == [PUSH_ENEMY_BASE]


def army(side: Side, order: Order) -> ArmySetup:
    return ArmySetup(
        side=side,
        troops=[
            TroopSetup(
                order=order,
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("cinder-hound")],
            )
        ],
    )


def test_every_troop_carries_exactly_one_order() -> None:
    world = create_world(
        TWO_LANE_MAP,
        BattleSetup(unit_types=[ADEPT, HOUND], armies=[army("north", hold("W")), army("south", DEFEND_BASE)]),
        create_rng(1),
    )

    assert [troop.order for troop in world.troops] == [hold("W"), DEFEND_BASE]


def test_a_unit_acts_under_its_troops_order() -> None:
    world = create_world(
        TWO_LANE_MAP,
        BattleSetup(unit_types=[ADEPT, HOUND], armies=[army("north", hold("W")), army("south", DEFEND_BASE)]),
        create_rng(1),
    )

    north = next(unit for unit in world.units if unit.side == "north")
    assert order_of(world, north) == hold("W")


def test_a_troop_cannot_be_built_without_one() -> None:
    with pytest.raises(TypeError):
        TroopSetup(mages=[RosterEntry("ember-adept")])  # type: ignore[call-arg]


def test_an_order_naming_a_zone_the_map_does_not_have_stops_the_battle_being_built() -> None:
    with pytest.raises(ValueError, match="zone"):
        create_world(
            TWO_LANE_MAP,
            BattleSetup(
                unit_types=[ADEPT, HOUND],
                armies=[army("north", hold("Q")), army("south", DEFEND_BASE)],
            ),
            create_rng(1),
        )


#: Words that would mean a plan had been allowed to say where units stand.
PLACEMENT_WORDS = (
    "position",
    "placement",
    "place",
    "stance",
    "facing",
    "formation",
    "spot",
    "anchor",
    "offset",
    "coordinate",
)
#: Everything a plan hands the sim. Nothing here may carry a placement.
PLAN_FACING_TYPES = (Order, TroopSetup, ArmySetup, BattleSetup, RosterEntry)


@pytest.mark.parametrize("plan_type", PLAN_FACING_TYPES)
def test_no_placement_or_stance_input_exists_anywhere_in_the_api(plan_type: type) -> None:
    """The design's central constraint: the player gives an order, never a
    placement (§6.1). A field that let one in would not fail any other test —
    everything would still run, and the plan phase would quietly stop being
    three taps. So the constraint is asserted directly."""
    for field in dataclasses.fields(plan_type):
        assert not any(word in field.name.lower() for word in PLACEMENT_WORDS), field.name
        assert Vec2.__name__ not in str(field.type), field.name
