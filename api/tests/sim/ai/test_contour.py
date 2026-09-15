"""Reading a stat block's pattern, and turning it into what a creature wants."""

from __future__ import annotations

from app.sim.ai.contour import MAX_WEIGHT_CHECK, contour_of, derived_weights, roster_scale
from app.sim.ai.factors import FACTORS
from app.sim.units import UnitType


def card(id: str, hp: float, speed: float, reach: float, damage: float) -> UnitType:
    return UnitType(
        id=id,
        kind="summon",
        schools=("fire",),
        max_hp=hp,
        damage=damage,
        range=reach,
        speed=speed,
        attack_cooldown_seconds=1.0,
    )


BRUTE = card("brute", hp=200, speed=20, reach=14, damage=20)
SNIPER = card("sniper", hp=40, speed=50, reach=120, damage=8)
RUSHER = card("rusher", hp=160, speed=60, reach=16, damage=12)
HELPLESS = card("helpless", hp=10, speed=0, reach=0, damage=0)
ROSTER = [BRUTE, SNIPER, RUSHER, HELPLESS]
SCALE = roster_scale(ROSTER)


def read(unit_type: UnitType, scale=SCALE):  # type: ignore[no-untyped-def]
    return contour_of(unit_type.max_hp, unit_type.speed, unit_type.range, unit_type.damage, scale)


# --- the two axes -----------------------------------------------------------


def test_tough_and_slow_absorbs_while_quick_and_frail_evades() -> None:
    assert read(BRUTE).defence == "absorb"
    assert read(SNIPER).defence == "evade"


def test_something_quick_and_sturdy_is_not_treated_as_evasive() -> None:
    """The trap the naive reading falls into, and the reason for the damping.

    Quicker than it is tough looks like evasion until you notice a creature can
    be high on *both*. One that is is not avoiding a fight, it is winning one
    slowly — and it should not end up warier than something half its size.
    """
    rusher, sniper = read(RUSHER), read(SNIPER)

    assert rusher.mobility > rusher.durability  # quicker than it is tough...
    assert rusher.evasiveness < sniper.evasiveness  # ...but not the evasive one
    assert derived_weights(rusher)["danger"] < derived_weights(sniper)["danger"]


def test_reach_and_force_name_how_a_creature_hurts_things() -> None:
    assert read(SNIPER).offence == "ranged"
    assert read(BRUTE).offence == "brute"


def test_a_creature_that_cannot_attack_is_not_called_a_brute() -> None:
    """Zero force tying with zero reach is not a fighting style."""
    assert read(HELPLESS).offence == "none"


# --- the scale --------------------------------------------------------------


def test_a_roster_with_nothing_to_say_ranks_everything_dead_centre() -> None:
    """Not zero, which would read as "the frailest" rather than "unknown"."""
    identical = [card("a", 50, 30, 20, 10), card("b", 50, 30, 20, 10)]

    only = read(identical[0], roster_scale(identical))

    assert only.durability == only.mobility == only.reach == only.force == 0.5


def test_the_same_card_reads_differently_in_different_company() -> None:
    """Deliberate: tough and quick only mean anything relative to something.

    The tabletop original gets this free from a shared 3-18 scale. Hit points
    and map units per second share no scale, so the battle's own cards supply
    one — and a card that is the sturdiest thing in one roster is not in another.
    """
    among_brutes = read(SNIPER, roster_scale([SNIPER, BRUTE, RUSHER]))
    among_weaklings = read(SNIPER, roster_scale([SNIPER, HELPLESS]))

    assert among_weaklings.durability > among_brutes.durability


# --- what comes out ---------------------------------------------------------


def test_the_heavy_hitter_values_a_good_target_most() -> None:
    assert (
        derived_weights(read(BRUTE))["target_suitability"]
        > derived_weights(read(SNIPER))["target_suitability"]
    )


def test_the_frailest_values_company_most() -> None:
    """Small weak things travel in packs, and nobody had to write that down."""
    assert derived_weights(read(HELPLESS))["ally_support"] > derived_weights(read(BRUTE))["ally_support"]


def test_every_derived_weight_stays_inside_the_bounds() -> None:
    """However lopsided a stat block, a derived profile stays a profile."""
    extremes = [
        card("min", 1, 0, 0, 0),
        card("max", 9999, 999, 999, 999),
        *ROSTER,
    ]
    scale = roster_scale(extremes)

    for unit_type in extremes:
        weights = derived_weights(read(unit_type, scale))

        assert set(weights) == set(FACTORS)
        assert all(0.0 <= value <= MAX_WEIGHT_CHECK for value in weights.values())
