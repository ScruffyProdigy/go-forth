"""The energy gauge and the rule that fills it.

The claim under test is not "a gauge fills" — it is that *how* it fills is
school data. The last test in this file adds a third rule without touching a
line of `app/`, which is the acceptance criterion written as code.
"""

from __future__ import annotations

import pytest

from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.energy import (
    ALLY_DEFEATED,
    DAMAGE_DEALT,
    DAMAGE_TAKEN,
    ELAPSED_SECONDS,
    ENERGY_METERS,
    EnergyRule,
    EnergySource,
    energy_gain,
    energy_multiplier_for,
    energy_rule_for,
    new_energy_meters,
    resolve_school_energy_rules,
)
from app.sim.schools import SCHOOLS, SchoolConfig, resolve_school_multipliers


def rates(rule: EnergyRule) -> dict[str, float]:
    """A rule as `{meter: rate}`, which is easier to assert against."""
    return {source.meter: source.energy_per_unit for source in rule}


def rules(*configs: SchoolConfig) -> dict[str, dict[str, float]]:
    table = resolve_school_energy_rules(list(configs))
    return {school: rates(rule) for school, rule in table.items()}


def test_fire_charges_off_damage_dealt_over_the_common_clock() -> None:
    assert rules()["fire"] == {ELAPSED_SECONDS: 4.0, DAMAGE_DEALT: 1.0}


def test_stone_charges_off_damage_taken() -> None:
    """§4.4 names it, and it cost a row rather than a branch."""
    assert rules()["stone"] == {ELAPSED_SECONDS: 4.0, DAMAGE_TAKEN: 1.0}


def test_necromancy_charges_off_ally_deaths() -> None:
    assert rules()["necromancy"] == {ELAPSED_SECONDS: 4.0, ALLY_DEFEATED: 25.0}


def test_artifice_charges_on_a_faster_clock_and_nothing_else() -> None:
    """The clock is Artifice's character (§4.4), not a floor under something
    else — which is what lets an emplacement that never swings come online."""
    assert rules()["artifice"] == {ELAPSED_SECONDS: 10.0}


def test_every_school_trickles_so_no_unit_is_ever_wholly_inert() -> None:
    table = resolve_school_energy_rules([])

    for school in SCHOOLS:
        assert rates(table[school]).get(ELAPSED_SECONDS, 0) > 0


def test_a_rule_is_an_ordered_tuple_of_named_sources() -> None:
    """Not a mapping keyed by meter. Ordered, so the sum is reproducible
    without a separate list of meter names to walk; and a school could hold
    two sources on one meter, which a mapping cannot express."""
    rule = resolve_school_energy_rules([])["fire"]

    assert isinstance(rule, tuple)
    assert all(isinstance(source, EnergySource) for source in rule)


def test_a_source_rejects_a_meter_the_sim_does_not_measure() -> None:
    with pytest.raises(ValueError, match="is not a meter"):
        EnergySource("vibes", 1)


def test_a_school_config_overrides_its_default_rule() -> None:
    table = rules(SchoolConfig(id="fire", energy_rule={DAMAGE_TAKEN: 2}))

    assert table["fire"] == {DAMAGE_TAKEN: 2.0}


def test_a_third_rule_is_data_rather_than_a_new_branch() -> None:
    """JQ-288's actual acceptance criterion: a school that charges off being
    hit, and off its troop-mates dying, is a dict literal. Nothing in `app/`
    knows this rule exists."""
    table = resolve_school_energy_rules(
        [SchoolConfig(id="necromancy", energy_rule={DAMAGE_TAKEN: 0.5, ALLY_DEFEATED: 25})]
    )
    meters = new_energy_meters()
    meters[DAMAGE_TAKEN] = 10
    meters[ALLY_DEFEATED] = 2

    assert energy_gain(meters, table["necromancy"], 1.0) == 5 + 50


def test_an_unknown_meter_is_rejected_rather_than_silently_ignored() -> None:
    with pytest.raises(ValueError, match="not meters"):
        resolve_school_energy_rules([SchoolConfig(id="fire", energy_rule={"vibes": 1})])


def test_a_negative_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        resolve_school_energy_rules([SchoolConfig(id="fire", energy_rule={DAMAGE_DEALT: -1})])


def test_a_school_configured_twice_is_rejected() -> None:
    with pytest.raises(ValueError, match="configured twice"):
        resolve_school_energy_rules([SchoolConfig(id="fire"), SchoolConfig(id="fire")])


def test_a_dual_card_takes_the_best_rate_per_meter_across_its_schools() -> None:
    table = resolve_school_energy_rules(
        [
            SchoolConfig(id="fire", energy_rule={DAMAGE_DEALT: 1, ELAPSED_SECONDS: 2}),
            SchoolConfig(id="artifice", energy_rule={ELAPSED_SECONDS: 10}),
        ]
    )

    merged = energy_rule_for(("fire", "artifice"), table)

    assert rates(merged) == {DAMAGE_DEALT: 1.0, ELAPSED_SECONDS: 10.0}


def test_a_dual_card_is_not_charged_twice_for_a_meter_both_schools_share() -> None:
    table = resolve_school_energy_rules(
        [
            SchoolConfig(id="fire", energy_rule={DAMAGE_DEALT: 1}),
            SchoolConfig(id="stone", energy_rule={DAMAGE_DEALT: 1}),
        ]
    )

    assert rates(energy_rule_for(("fire", "stone"), table)) == {DAMAGE_DEALT: 1.0}


def test_gain_is_scaled_by_the_schools_energy_gain_multiplier() -> None:
    meters = new_energy_meters()
    meters[DAMAGE_DEALT] = 10
    rule = resolve_school_energy_rules([])["fire"]

    assert energy_gain(meters, rule, 1.5) == 15


def test_the_multiplier_is_read_from_the_cores_record_not_computed_here() -> None:
    multipliers = resolve_school_multipliers(
        [SchoolConfig(id="fire", multipliers={"energy_gain_multiplier": 2.0})]
    )

    assert energy_multiplier_for(("fire",), multipliers) == 2.0


def test_a_dual_card_charges_under_the_better_of_its_two_multipliers() -> None:
    multipliers = resolve_school_multipliers(
        [
            SchoolConfig(id="fire", multipliers={"energy_gain_multiplier": 2.0}),
            SchoolConfig(id="artifice", multipliers={"energy_gain_multiplier": 0.5}),
        ]
    )

    assert energy_multiplier_for(("fire", "artifice"), multipliers) == 2.0


def test_a_meter_the_rule_does_not_name_is_worth_nothing() -> None:
    meters = new_energy_meters()
    meters[DAMAGE_TAKEN] = 1000
    rule = resolve_school_energy_rules([])["fire"]

    assert energy_gain(meters, rule, 1.0) == 0


def test_the_meter_vocabulary_is_an_ordered_tuple_not_a_set() -> None:
    """Walking a set would order a unit's meters by `PYTHONHASHSEED`."""
    assert isinstance(ENERGY_METERS, tuple)
    assert sorted(new_energy_meters()) == sorted(ENERGY_METERS)


def test_a_timer_rule_is_worth_its_rate_every_second_of_ticks() -> None:
    table = resolve_school_energy_rules([])
    rule = table["artifice"]
    seconds_per_tick = 1 / DEFAULT_SIM_CONFIG.tick_rate

    total = 0.0
    for _ in range(DEFAULT_SIM_CONFIG.tick_rate):
        meters = new_energy_meters()
        meters[ELAPSED_SECONDS] = seconds_per_tick
        total += energy_gain(meters, rule, 1.0)

    assert total == pytest.approx(10.0)
