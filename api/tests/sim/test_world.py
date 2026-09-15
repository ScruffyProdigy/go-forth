"""The world model and how a battle's opening state is built from roster data."""

from __future__ import annotations

import dataclasses

import pytest

from app.sim.map import THREE_ZONE_MAP
from app.sim.orders import PUSH_ENEMY_BASE
from app.sim.rng import create_rng
from app.sim.types import Side
from app.sim.world import (
    ArmySetup,
    BattleSetup,
    RosterEntry,
    TroopSetup,
    World,
    create_world,
)
from tests.sim.fixtures_units import ADEPT, HOUND


def one_each(side: Side) -> ArmySetup:
    return ArmySetup(
        side=side,
        troops=[
            TroopSetup(
                order=PUSH_ENEMY_BASE,
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("cinder-hound")],
            )
        ],
    )


def setup(armies: list[ArmySetup] | None = None) -> BattleSetup:
    return BattleSetup(
        unit_types=[ADEPT, HOUND],
        armies=armies if armies is not None else [one_each("north"), one_each("south")],
    )


def build(battle_state: BattleSetup | None = None, seed: int = 1) -> World:
    return create_world(THREE_ZONE_MAP, battle_state or setup(), create_rng(seed))


def only_mage(side: Side) -> ArmySetup:
    return ArmySetup(
        side=side, troops=[TroopSetup(order=PUSH_ENEMY_BASE, mages=[RosterEntry("ember-adept")], summons=[])]
    )


def test_starts_at_tick_zero() -> None:
    assert build().tick == 0


def test_opens_both_bases_at_full_hp() -> None:
    world = build()

    assert world.bases["north"].hp == THREE_ZONE_MAP.bases["north"].max_hp
    assert world.bases["south"].hp == THREE_ZONE_MAP.bases["south"].max_hp


def test_opens_with_no_zone_score() -> None:
    assert build().zone_score == {"north": 0, "south": 0}


def test_instantiates_a_unit_per_copy_so_duplicates_are_legal() -> None:
    world = build(
        setup(
            [
                ArmySetup(
                    side="north",
                    troops=[
                        TroopSetup(
                            order=PUSH_ENEMY_BASE,
                            mages=[RosterEntry("ember-adept", 3)],
                            summons=[RosterEntry("cinder-hound", 4)],
                        )
                    ],
                ),
                only_mage("south"),
            ]
        )
    )

    north = [unit for unit in world.units if unit.side == "north"]
    assert len([u for u in north if u.type_id == "ember-adept"]) == 3
    assert len([u for u in north if u.type_id == "cinder-hound"]) == 4


def test_one_unit_a_side_is_a_legal_battle() -> None:
    assert len(build(setup([only_mage("north"), only_mage("south")])).units) == 2


def test_forty_units_a_side_is_the_same_code_path() -> None:
    many = TroopSetup(
        order=PUSH_ENEMY_BASE,
        mages=[RosterEntry("ember-adept", 6)],
        summons=[RosterEntry("cinder-hound", 14)],
    )
    world = build(
        setup(
            [
                ArmySetup(side="north", troops=[many, dataclasses.replace(many)]),
                ArmySetup(
                    side="south",
                    troops=[dataclasses.replace(many), dataclasses.replace(many)],
                ),
            ]
        )
    )

    assert len(world.units) == 80


def test_rejects_a_roster_entry_naming_a_card_not_in_the_catalog() -> None:
    with pytest.raises(ValueError, match="frost-adept"):
        build(
            setup(
                [
                    ArmySetup(
                        side="north",
                        troops=[
                            TroopSetup(order=PUSH_ENEMY_BASE, mages=[RosterEntry("frost-adept")], summons=[])
                        ],
                    ),
                    only_mage("south"),
                ]
            )
        )


def test_gives_every_unit_the_stat_block_the_sim_reads() -> None:
    unit = next(u for u in build().units if u.type_id == "cinder-hound")

    assert (
        unit.kind,
        unit.schools,
        unit.hp,
        unit.max_hp,
        unit.damage,
        unit.range,
        unit.speed,
    ) == (
        "summon",
        ("fire",),
        40,
        40,
        20,
        20,
        60,
    )


def test_puts_every_unit_in_exactly_one_troop() -> None:
    world = build()

    for unit in world.units:
        owning = [t for t in world.troops if unit.id in t.mage_ids or unit.id in t.summon_ids]
        assert len(owning) == 1
        assert owning[0].id == unit.troop_id


def test_a_troop_reaches_its_mages_and_summons_separately() -> None:
    troop = build().troops[0]

    assert len(troop.mage_ids) == 1
    assert len(troop.summon_ids) == 1


def test_every_unit_has_a_unique_id() -> None:
    world = build(
        setup(
            [
                ArmySetup(
                    side="north",
                    troops=[
                        TroopSetup(order=PUSH_ENEMY_BASE, mages=[RosterEntry("ember-adept", 2)], summons=[]),
                        TroopSetup(order=PUSH_ENEMY_BASE, mages=[RosterEntry("ember-adept", 2)], summons=[]),
                    ],
                ),
                only_mage("south"),
            ]
        )
    )

    assert len({unit.id for unit in world.units}) == len(world.units)


def test_rejects_a_summon_no_mage_in_its_troop_can_support() -> None:
    stone_guard = dataclasses.replace(HOUND, id="stone-guard", schools=("stone",))
    battle = BattleSetup(
        unit_types=[ADEPT, HOUND, stone_guard],
        armies=[
            ArmySetup(
                side="north",
                troops=[
                    TroopSetup(
                        order=PUSH_ENEMY_BASE,
                        mages=[RosterEntry("ember-adept")],
                        summons=[RosterEntry("stone-guard")],
                    )
                ],
            ),
            only_mage("south"),
        ],
    )

    with pytest.raises(ValueError, match="support"):
        build(battle)


def test_rejects_a_troop_with_no_mage() -> None:
    with pytest.raises(ValueError, match="mage"):
        build(
            setup(
                [
                    ArmySetup(
                        side="north",
                        troops=[
                            TroopSetup(order=PUSH_ENEMY_BASE, mages=[], summons=[RosterEntry("cinder-hound")])
                        ],
                    ),
                    only_mage("south"),
                ]
            )
        )


def test_rejects_an_army_missing_for_a_side() -> None:
    with pytest.raises(ValueError, match="no army"):
        build(setup([only_mage("north")]))


def test_places_every_unit_inside_its_own_deployment_strip() -> None:
    many = TroopSetup(
        order=PUSH_ENEMY_BASE,
        mages=[RosterEntry("ember-adept", 6)],
        summons=[RosterEntry("cinder-hound", 14)],
    )
    world = build(
        setup(
            [
                ArmySetup(side="north", troops=[many]),
                ArmySetup(side="south", troops=[dataclasses.replace(many)]),
            ]
        )
    )

    for unit in world.units:
        strip = THREE_ZONE_MAP.deployment[unit.side]
        assert strip.lane.start <= unit.position.y <= strip.lane.end
        assert strip.extent.start <= unit.position.x <= strip.extent.end


def test_does_not_stack_two_units_on_the_same_spot() -> None:
    world = build(
        setup(
            [
                ArmySetup(
                    side="north",
                    troops=[
                        TroopSetup(order=PUSH_ENEMY_BASE, mages=[RosterEntry("ember-adept", 6)], summons=[])
                    ],
                ),
                only_mage("south"),
            ]
        )
    )

    spots = [unit.position for unit in world.units]
    assert len(set(spots)) == len(spots)


def test_places_the_same_army_the_same_way_for_the_same_seed() -> None:
    a = build(seed=77)
    b = build(seed=77)

    assert [u.position for u in a.units] == [u.position for u in b.units]


def test_places_it_differently_for_a_different_seed() -> None:
    assert [u.position for u in build(seed=1).units] != [u.position for u in build(seed=2).units]
