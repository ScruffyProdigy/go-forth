"""The per-school multiplier record — the seam slices C and D trade through."""

import dataclasses

import pytest

from app.sim.schools import (
    IDENTITY_MULTIPLIERS,
    SCHOOLS,
    SchoolConfig,
    resolve_school_multipliers,
)


def test_ships_identity_values_for_every_school() -> None:
    table = resolve_school_multipliers([])

    for school in SCHOOLS:
        assert table[school] == IDENTITY_MULTIPLIERS


def test_carries_the_three_levers_slices_c_and_d_trade_through() -> None:
    assert dataclasses.asdict(IDENTITY_MULTIPLIERS) == {
        "energy_gain_multiplier": 1.0,
        "resummon_pace_multiplier": 1.0,
        "stat_axis_multiplier": 1.0,
    }


def test_honours_an_override_a_school_config_supplies() -> None:
    table = resolve_school_multipliers([SchoolConfig(id="fire", multipliers={"energy_gain_multiplier": 1.5})])

    assert table["fire"].energy_gain_multiplier == 1.5


def test_leaves_unmentioned_levers_at_identity() -> None:
    table = resolve_school_multipliers([SchoolConfig(id="fire", multipliers={"energy_gain_multiplier": 1.5})])

    assert table["fire"].resummon_pace_multiplier == 1.0
    assert table["fire"].stat_axis_multiplier == 1.0


def test_leaves_unmentioned_schools_at_identity() -> None:
    table = resolve_school_multipliers([SchoolConfig(id="fire", multipliers={"stat_axis_multiplier": 2})])

    assert table["stone"] == IDENTITY_MULTIPLIERS


def test_rejects_a_multiplier_that_is_not_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        resolve_school_multipliers([SchoolConfig(id="stone", multipliers={"stat_axis_multiplier": 0})])


def test_rejects_an_unknown_lever_name() -> None:
    with pytest.raises(ValueError, match="not a multiplier"):
        resolve_school_multipliers([SchoolConfig(id="fire", multipliers={"speed": 2})])


def test_rejects_the_same_school_configured_twice() -> None:
    with pytest.raises(ValueError, match="twice"):
        resolve_school_multipliers([SchoolConfig(id="fire"), SchoolConfig(id="fire")])


def test_resolves_once_and_cannot_be_rewritten_mid_battle() -> None:
    table = resolve_school_multipliers([])

    with pytest.raises(TypeError):
        table["fire"] = IDENTITY_MULTIPLIERS  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        table["fire"].energy_gain_multiplier = 9.0  # type: ignore[misc]
