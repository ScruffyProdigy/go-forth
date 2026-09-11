"""Tick settings."""

import pytest

from app.sim.config import (
    DEFAULT_SIM_CONFIG,
    SimConfig,
    max_ticks,
    seconds_per_tick,
    to_ticks,
    validate_sim_config,
)


def test_the_shipped_config_is_valid() -> None:
    validate_sim_config(DEFAULT_SIM_CONFIG)


def test_fixes_a_whole_number_of_ticks_per_second() -> None:
    assert isinstance(DEFAULT_SIM_CONFIG.tick_rate, int)


def test_backstops_a_battle_at_the_design_doc_length() -> None:
    assert DEFAULT_SIM_CONFIG.max_battle_seconds >= 60


def test_seconds_per_tick_is_the_inverse_of_the_tick_rate() -> None:
    assert seconds_per_tick(
        SimConfig(tick_rate=20, max_battle_seconds=90)
    ) == pytest.approx(0.05)


def test_max_ticks_is_the_battle_length_in_ticks() -> None:
    assert max_ticks(SimConfig(tick_rate=20, max_battle_seconds=90)) == 1800


def test_rejects_a_tick_rate_that_is_not_a_positive_whole_number() -> None:
    with pytest.raises(ValueError, match="tick rate"):
        validate_sim_config(SimConfig(tick_rate=0, max_battle_seconds=90))
    with pytest.raises(ValueError, match="tick rate"):
        validate_sim_config(SimConfig(tick_rate=1.5, max_battle_seconds=90))  # type: ignore[arg-type]


def test_rejects_a_battle_with_no_length() -> None:
    with pytest.raises(ValueError, match="length"):
        validate_sim_config(SimConfig(tick_rate=20, max_battle_seconds=0))


def test_durations_are_counted_in_whole_ticks() -> None:
    """Subtracting 0.05 twenty times does not reliably land on zero."""
    assert to_ticks(1, SimConfig(tick_rate=20, max_battle_seconds=90)) == 20
    assert to_ticks(0.0001, SimConfig(tick_rate=20, max_battle_seconds=90)) == 1
