"""Bases: who may hit one, what that costs, and what it ends."""

from __future__ import annotations

import copy

import pytest

from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig
from app.sim.context import TickContext, create_tick_context
from app.sim.map import TWO_LANE_MAP, MapConfig
from app.sim.orders import DEFEND_BASE, PUSH_ENEMY_BASE, Order, hold
from app.sim.phases.combat import combat_phase
from app.sim.rng import create_rng
from app.sim.run_battle import run_battle
from app.sim.schools import resolve_side_multipliers
from app.sim.types import Side, Vec2
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, Unit, World, create_world
from tests.sim.fixtures_units import ADEPT, HOUND


def base_in_reach() -> MapConfig:
    """The south base moved up to meet the north deployment strip, so a pushing
    troop is swinging at the wall on the first tick rather than the hundredth."""
    config = copy.deepcopy(TWO_LANE_MAP)
    config.id = "base-in-reach"
    config.bases["south"].position = Vec2(187.5, 110)
    return config


CLOSE_MAP = base_in_reach()
#: Long enough to land a blow, short enough that a full base survives the round.
ONE_SECOND = SimConfig(tick_rate=20, max_battle_seconds=1)


def battle(order: Order, base_hp: dict[Side, float] | None = None) -> BattleSetup:
    return BattleSetup(
        unit_types=[ADEPT, HOUND],
        armies=[
            ArmySetup(
                side="north",
                troops=[
                    TroopSetup(
                        order=order,
                        mages=[RosterEntry("ember-adept")],
                        summons=[RosterEntry("cinder-hound")],
                    )
                ],
            ),
            ArmySetup(
                side="south",
                troops=[TroopSetup(order=DEFEND_BASE, mages=[RosterEntry("ember-adept")])],
            ),
        ],
        base_hp=base_hp or {},
    )


def context() -> TickContext:
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=CLOSE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(3),
    )


def world_under(order: Order) -> World:
    return create_world(CLOSE_MAP, battle(order), create_rng(3))


def hound(world: World) -> Unit:
    return next(unit for unit in world.units if unit.type_id == "cinder-hound")


def test_a_pushing_unit_damages_the_enemy_base() -> None:
    world = world_under(PUSH_ENEMY_BASE)

    combat_phase.run(world, context())

    assert world.bases["south"].hp < world.bases["south"].max_hp


@pytest.mark.parametrize("order", [hold("W"), hold("E"), DEFEND_BASE])
def test_no_other_order_may_touch_a_base(order: Order) -> None:
    world = world_under(order)

    combat_phase.run(world, context())

    assert world.bases["south"].hp == world.bases["south"].max_hp


def test_a_pushing_unit_fights_what_is_in_front_of_it_first() -> None:
    world, ctx = world_under(PUSH_ENEMY_BASE), context()
    defender = next(unit for unit in world.units if unit.side == "south")
    defender.position = hound(world).position

    combat_phase.run(world, ctx)

    assert defender.hp < defender.max_hp
    assert [event.type for event in ctx.emitter.events if event.type == "baseHit"] == []


def test_a_base_hit_is_emitted_carrying_what_it_cost() -> None:
    world, ctx = world_under(PUSH_ENEMY_BASE), context()

    combat_phase.run(world, ctx)

    hits = [event for event in ctx.emitter.events if event.type == "baseHit"]
    assert [event.swing.base_hp["south"] for event in hits] == [-ADEPT.damage, -HOUND.damage]
    assert all(event.swing.base_hp["north"] == 0 for event in hits)


def test_a_base_hit_names_the_unit_that_landed_it() -> None:
    world, ctx = world_under(PUSH_ENEMY_BASE), context()

    combat_phase.run(world, ctx)

    hit = next(event for event in ctx.emitter.events if event.type == "baseHit")
    assert hit.actors.source is not None
    assert hit.actors.source.unit_id == next(unit for unit in world.units if unit.kind == "mage").id


def test_the_last_blow_takes_only_what_is_left() -> None:
    world, ctx = world_under(PUSH_ENEMY_BASE), context()
    world.bases["south"].hp = 5

    combat_phase.run(world, ctx)

    assert world.bases["south"].hp == 0
    assert [event.swing.base_hp["south"] for event in ctx.emitter.events if event.type == "baseHit"] == [-5]


def test_a_base_at_zero_ends_the_battle_at_once() -> None:
    result = run_battle(CLOSE_MAP, [], battle(PUSH_ENEMY_BASE, {"south": 30}), 1)

    assert result.outcome == "baseDestroyed"
    assert result.final_state.tick == 1


def test_the_side_whose_base_fell_is_named_so_the_match_can_be_lost() -> None:
    result = run_battle(CLOSE_MAP, [], battle(PUSH_ENEMY_BASE, {"south": 30}), 1)

    assert result.destroyed_base == "south"


def test_an_ordinary_battle_names_nobody() -> None:
    result = run_battle(CLOSE_MAP, [], battle(DEFEND_BASE), 1)

    assert result.outcome != "baseDestroyed"
    assert result.destroyed_base is None


def test_a_base_opens_on_the_hp_it_was_carried_in_with() -> None:
    world = create_world(CLOSE_MAP, battle(DEFEND_BASE, {"south": 400}), create_rng(1))

    assert world.bases["south"].hp == 400
    assert world.bases["north"].hp == CLOSE_MAP.bases["north"].max_hp


def test_what_is_left_comes_back_out_to_be_carried_on() -> None:
    result = run_battle(CLOSE_MAP, [], battle(PUSH_ENEMY_BASE, {"south": 400}), 1)

    assert result.base_hp["south"] == result.final_state.bases["south"].hp
    assert result.base_hp["south"] < 400


def test_a_round_boundary_never_refills_a_base() -> None:
    first = run_battle(CLOSE_MAP, [], battle(PUSH_ENEMY_BASE), 1, ONE_SECOND)
    second = run_battle(CLOSE_MAP, [], battle(PUSH_ENEMY_BASE, first.base_hp), 1, ONE_SECOND)

    assert second.ticks[0].state.bases["south"].hp == first.base_hp["south"]
    assert second.base_hp["south"] < first.base_hp["south"]


def test_a_base_cannot_be_carried_in_above_its_maximum() -> None:
    with pytest.raises(ValueError, match="do not recover"):
        create_world(CLOSE_MAP, battle(DEFEND_BASE, {"south": 2000}), create_rng(1))


def test_a_base_carried_in_at_zero_is_a_match_that_is_already_over() -> None:
    with pytest.raises(ValueError, match="already over"):
        create_world(CLOSE_MAP, battle(DEFEND_BASE, {"south": 0}), create_rng(1))
