"""Spell definitions: what the catalog accepts, and what it refuses.

The refusals matter more than the acceptances here. Every one of them is a
mistake that would otherwise reach a battle as a number that quietly failed to
scale — a typo in a field path scales nothing, and a second curve on one field
is the multiplication JQ-297 rules out.
"""

from __future__ import annotations

import pytest

from app.sim.effects import AreaDamage, BurningGround, DamageProfile, Knockback
from app.sim.spellbook import (
    TAGS,
    AlwaysAvailable,
    EffectScaling,
    IndependentAccess,
    SignatureOf,
    SpellDefinition,
    access_kind,
    build_definition_catalog,
    effect_to_json,
    read_field,
    validate_definition,
    write_field,
)

BLAST = AreaDamage(radius=40, damage=DamageProfile(amount=20, bonus_vs_base=1.5))


def definition(**overrides: object) -> SpellDefinition:
    base: dict[str, object] = {
        "id": "test-spell",
        "name": "Test Spell",
        "cost": 10.0,
        "text": "It does a thing.",
        "access": AlwaysAvailable(),
        "effects": (BLAST,),
        "scaling": (),
    }
    base.update(overrides)
    return SpellDefinition(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- field paths --


def test_reads_a_nested_field_by_path() -> None:
    assert read_field(BLAST, "radius") == 40
    assert read_field(BLAST, "damage.amount") == 20


def test_writing_a_field_leaves_the_original_untouched() -> None:
    """The base effects of a definition are shared by every resolution of it.

    Both sides resolve the same `SpellDefinition` object, so a write that
    mutated in place would leak one seat's scaled damage into the other's.
    """
    raised = write_field(BLAST, "damage.amount", 99)

    assert read_field(raised, "damage.amount") == 99
    assert read_field(BLAST, "damage.amount") == 20
    # Everything else on the way down the path survives the rebuild.
    assert read_field(raised, "damage.bonus_vs_base") == 1.5
    assert read_field(raised, "radius") == 40


# ---------------------------------------------------------------- validation --


def test_a_field_takes_one_curve() -> None:
    """The refusal JQ-297 turns on: two tags may not stack on one number."""
    with pytest.raises(ValueError, match="a number takes one curve"):
        validate_definition(
            definition(
                scaling=(
                    EffectScaling(0, "damage.amount", "evocation", per_mage=5, cap=20),
                    EffectScaling(0, "damage.amount", "reckless", per_mage=5, cap=20),
                )
            )
        )


def test_two_tags_on_two_fields_of_one_effect_are_fine() -> None:
    validate_definition(
        definition(
            scaling=(
                EffectScaling(0, "damage.amount", "evocation", per_mage=5, cap=20),
                EffectScaling(0, "radius", "reckless", per_mage=5, cap=20),
            )
        )
    )


def test_one_tag_may_drive_two_different_effects() -> None:
    """A tag is not spent. It raises each number it is pointed at, once each."""
    validate_definition(
        definition(
            effects=(BLAST, BurningGround(radius=40, damage_per_second=4, duration_seconds=3)),
            scaling=(
                EffectScaling(0, "damage.amount", "evocation", per_mage=5, cap=20),
                EffectScaling(1, "damage_per_second", "evocation", per_mage=1, cap=3),
            ),
        )
    )


def test_refuses_a_field_that_does_not_exist() -> None:
    with pytest.raises(ValueError, match="no such number"):
        validate_definition(definition(scaling=(EffectScaling(0, "splash", "evocation", 5, 20),)))


def test_refuses_a_field_that_is_not_a_number() -> None:
    """`hits_base` is a bool, and a bool is an int in Python. Caught anyway."""
    with pytest.raises(ValueError, match="no such number"):
        validate_definition(definition(scaling=(EffectScaling(0, "hits_base", "evocation", 5, 20),)))


def test_refuses_an_effect_index_past_the_end() -> None:
    with pytest.raises(ValueError, match="but it has 1"):
        validate_definition(definition(scaling=(EffectScaling(3, "radius", "evocation", 5, 20),)))


def test_refuses_a_tag_outside_the_vocabulary() -> None:
    with pytest.raises(ValueError, match="not a tag"):
        validate_definition(definition(scaling=(EffectScaling(0, "radius", "pyromancer", 5, 20),)))


def test_refuses_a_spell_with_no_effects() -> None:
    with pytest.raises(ValueError, match="casting it would do nothing"):
        validate_definition(definition(effects=()))


def test_refuses_a_duplicate_id() -> None:
    with pytest.raises(ValueError, match="defined twice"):
        build_definition_catalog([definition(), definition()])


def test_refuses_an_independent_minimum_below_one() -> None:
    with pytest.raises(ValueError, match="a minimum is at least 1"):
        validate_definition(definition(access=IndependentAccess(requires_tag="warding", minimum=0)))


# -------------------------------------------------------------------- curves --


def test_the_curve_is_bounded_at_both_ends() -> None:
    curve = EffectScaling(0, "radius", "warding", per_mage=5, cap=15, threshold=1)

    # Below and at the threshold, nothing at all.
    assert curve.bonus_at(0) == 0
    assert curve.bonus_at(1) == 0
    # Then linear, then flat.
    assert curve.bonus_at(2) == 5
    assert curve.bonus_at(4) == 15
    assert curve.bonus_at(40) == 15


def test_bonus_never_goes_negative_below_the_threshold() -> None:
    """`max(0, ...)` rather than a subtraction: four mages short is not -20."""
    assert EffectScaling(0, "radius", "warding", per_mage=5, cap=15, threshold=4).bonus_at(0) == 0


# --------------------------------------------------------------------- access --


def test_access_kinds_are_reported_by_rule() -> None:
    assert access_kind(AlwaysAvailable()) == "fallback"
    assert access_kind(SignatureOf("ember-adept")) == "signature"
    assert access_kind(IndependentAccess()) == "independent"


def test_the_vocabulary_carries_the_two_names_that_collide_with_factions() -> None:
    """Deliberate, and the reason JQ-297's faction rule is testable at all.

    A vocabulary without `artifice` and `necromancy` in it could not express the
    mage the rule is about, so the rule would pass by being unreachable.
    """
    assert "artifice" in TAGS
    assert "necromancy" in TAGS


def test_tags_are_sorted_and_unique() -> None:
    assert list(TAGS) == sorted(set(TAGS))


# ---------------------------------------------------------------- effect json --


def test_effect_json_is_camel_cased_and_kinded() -> None:
    payload = effect_to_json(BurningGround(radius=40, damage_per_second=4, duration_seconds=3))

    assert payload == {
        "kind": "burningGround",
        "radius": 40,
        "damagePerSecond": 4,
        "durationSeconds": 3,
        "bonusVsMage": 1.0,
    }


def test_effect_json_descends_into_the_damage_profile() -> None:
    payload = effect_to_json(BLAST)

    assert payload["kind"] == "areaDamage"
    assert payload["damage"] == {"amount": 20, "bonusVsMage": 1.0, "bonusVsBase": 1.5}


def test_every_primitive_has_a_json_name() -> None:
    """A new effect with no name would serialise as a `KeyError` at fixture time."""
    from app.sim.effects import EFFECT_KINDS as PRIMITIVES
    from app.sim.spellbook import EFFECT_KINDS as NAMES

    assert set(PRIMITIVES) == set(NAMES)


def test_knockback_round_trips_through_a_field_write() -> None:
    shove = Knockback(radius=30, distance=20)
    assert effect_to_json(write_field(shove, "distance", 35))["distance"] == 35
