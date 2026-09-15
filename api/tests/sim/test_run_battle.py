"""The tick loop — the sim's entry point."""

from __future__ import annotations

import copy

import pytest

from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig
from app.sim.map import THREE_ZONE_MAP, MapConfig
from app.sim.orders import DEFEND_BASE, PUSH_ENEMY_BASE, Order
from app.sim.run_battle import run_battle
from app.sim.schools import (
    DEFAULT_RESONANCE_CURVE,
    IDENTITY_MULTIPLIERS,
    SchoolConfig,
    resonance_step,
)
from app.sim.types import Side, Span
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup
from tests.sim.fixtures_units import ADEPT, WISP


def narrow_map() -> MapConfig:
    """A one-column map: both armies deploy in the same narrow lane, so a unit
    advancing on the enemy base walks straight into the enemy rather than past
    it. Engaging something not already in weapon range is slice B's job."""
    config = copy.deepcopy(THREE_ZONE_MAP)
    config.id = "test-lane"
    config.size_width = 40
    for zone in config.zones:
        zone.extent = Span(0, 40)
    for side in ("north", "south"):
        config.deployment[side].extent = Span(0, 40)
        config.bases[side].position = config.bases[side].position._replace(x=20)
    return config


NARROW_MAP = narrow_map()


def army(side: Side, type_id: str, order: Order = PUSH_ENEMY_BASE) -> ArmySetup:
    return ArmySetup(
        side=side,
        troops=[TroopSetup(order=order, mages=[RosterEntry(type_id)], summons=[])],
    )


HUNTER_VS_WISP = BattleSetup(
    unit_types=[ADEPT, WISP],
    armies=[army("north", "ember-adept"), army("south", "dying-wisp")],
)
STANDOFF = BattleSetup(
    unit_types=[WISP],
    armies=[
        army("north", "dying-wisp", DEFEND_BASE),
        army("south", "dying-wisp", DEFEND_BASE),
    ],
)
ONE_SECOND = SimConfig(tick_rate=20, max_battle_seconds=1)


def test_reports_the_opening_state_as_tick_zero() -> None:
    result = run_battle(NARROW_MAP, [], HUNTER_VS_WISP, 1)

    assert result.ticks[0].tick == 0
    assert result.ticks[0].events == ()
    assert len(result.ticks[0].state.units) == 2


def test_reports_state_tick_by_tick_numbered_in_order() -> None:
    result = run_battle(THREE_ZONE_MAP, [], STANDOFF, 1, ONE_SECOND)

    assert [entry.tick for entry in result.ticks] == list(range(21))


def test_snapshots_each_tick_so_a_later_tick_cannot_rewrite_an_earlier_one() -> None:
    result = run_battle(NARROW_MAP, [], HUNTER_VS_WISP, 1)

    assert result.final_state.units[0].position != result.ticks[0].state.units[0].position


def test_stops_once_a_side_has_been_wiped_out() -> None:
    result = run_battle(NARROW_MAP, [], HUNTER_VS_WISP, 1)

    assert result.outcome == "annihilation"
    assert all(unit.side == "north" for unit in result.final_state.units)


def test_stops_at_the_configured_battle_length_when_both_sides_survive() -> None:
    result = run_battle(THREE_ZONE_MAP, [], STANDOFF, 1, ONE_SECOND)

    assert result.outcome == "timeUp"
    assert result.final_state.tick == 20


def test_reads_the_tick_rate_from_config() -> None:
    slow = run_battle(THREE_ZONE_MAP, [], STANDOFF, 1, SimConfig(tick_rate=10, max_battle_seconds=1))

    assert slow.final_state.tick == 10


def test_collects_every_event_stamped_with_the_tick_it_happened_on() -> None:
    result = run_battle(NARROW_MAP, [], HUNTER_VS_WISP, 1)

    defeats = [event for event in result.events if event.type == "unitDefeated"]
    assert len(defeats) == 1
    assert defeats[0].tick == result.final_state.tick
    assert defeats[0].swing.units_removed[0].type_id == "dying-wisp"


def test_files_each_event_under_its_tick_as_well_as_in_the_stream() -> None:
    result = run_battle(NARROW_MAP, [], HUNTER_VS_WISP, 1)

    from_ticks = [event for entry in result.ticks for event in entry.events]
    assert from_ticks == list(result.events)


def test_resolves_the_school_multipliers_once_and_hands_them_back() -> None:
    result = run_battle(NARROW_MAP, [], HUNTER_VS_WISP, 1)

    # One Fire mage a side, so Fire sits on the curve's weakest step; a school
    # neither player fielded stays at identity.
    assert result.multipliers["north"]["fire"] == resonance_step(DEFAULT_RESONANCE_CURVE, 1)
    assert result.multipliers["north"]["stone"] == IDENTITY_MULTIPLIERS


def test_carries_a_school_config_override_through_to_the_battle() -> None:
    result = run_battle(
        NARROW_MAP,
        [SchoolConfig(id="fire", multipliers={"energy_gain_multiplier": 2})],
        HUNTER_VS_WISP,
        1,
    )

    assert result.multipliers["north"]["fire"].energy_gain_multiplier == 2


def test_defaults_to_the_shipped_sim_config() -> None:
    assert run_battle(THREE_ZONE_MAP, [], STANDOFF, 1).config == DEFAULT_SIM_CONFIG


def test_carries_the_seed_it_ran_on() -> None:
    assert run_battle(NARROW_MAP, [], HUNTER_VS_WISP, 4242).seed == 4242


def test_rejects_a_seed_that_is_not_an_integer() -> None:
    with pytest.raises(TypeError, match="seed"):
        run_battle(THREE_ZONE_MAP, [], STANDOFF, 1.5)  # type: ignore[arg-type]
