"""Unit types — the card, not the instance on the field."""

import dataclasses

import pytest

from app.sim.units import UnitType, build_unit_type_catalog

ADEPT = UnitType(
    id="ember-adept",
    kind="mage",
    schools=("fire",),
    max_hp=60,
    damage=8,
    range=90,
    speed=30,
    attack_cooldown_seconds=1.5,
    support_capacity=2,
    resummon_pace_seconds=12,
)
HOUND = UnitType(
    id="cinder-hound",
    kind="summon",
    schools=("fire",),
    max_hp=90,
    damage=12,
    range=18,
    speed=60,
    attack_cooldown_seconds=1,
)


def test_keys_the_catalog_by_unit_type_id() -> None:
    catalog = build_unit_type_catalog([ADEPT, HOUND])

    assert catalog["cinder-hound"].damage == 12


def test_accepts_a_dual_school_card() -> None:
    golem = dataclasses.replace(HOUND, id="furnace-golem", schools=("fire", "artifice"))

    assert build_unit_type_catalog([golem])["furnace-golem"].schools == (
        "fire",
        "artifice",
    )


def test_rejects_two_types_sharing_an_id() -> None:
    with pytest.raises(ValueError, match="twice"):
        build_unit_type_catalog([HOUND, dataclasses.replace(HOUND, max_hp=1)])


def test_rejects_a_unit_belonging_to_no_school() -> None:
    with pytest.raises(ValueError, match="school"):
        build_unit_type_catalog([dataclasses.replace(HOUND, schools=())])


def test_rejects_a_unit_with_no_hp() -> None:
    with pytest.raises(ValueError, match="max_hp"):
        build_unit_type_catalog([dataclasses.replace(HOUND, max_hp=0)])


def test_rejects_a_negative_attack_range() -> None:
    with pytest.raises(ValueError, match="range"):
        build_unit_type_catalog([dataclasses.replace(HOUND, range=-1)])


def test_rejects_a_cooldown_of_zero_which_would_fire_every_tick() -> None:
    with pytest.raises(ValueError, match="cooldown"):
        build_unit_type_catalog([dataclasses.replace(HOUND, attack_cooldown_seconds=0)])


def test_rejects_a_mage_that_could_hold_no_summons() -> None:
    with pytest.raises(ValueError, match="support capacity"):
        build_unit_type_catalog([dataclasses.replace(ADEPT, support_capacity=None)])


def test_rejects_an_unknown_school_name() -> None:
    with pytest.raises(ValueError, match="not a school"):
        build_unit_type_catalog(
            [dataclasses.replace(HOUND, schools=("plasma",))]  # type: ignore[arg-type]
        )
