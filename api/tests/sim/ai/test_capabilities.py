"""Capabilities are read off live stats, never off the creature type."""

from __future__ import annotations

import pytest

from app.sim.ai.capabilities import capabilities_of, missing_capabilities, supports
from app.sim.types import Vec2
from tests.sim.ai.helpers import make_unit
from tests.sim.fixtures_units import ADEPT, HOUND, WISP

HERE = Vec2(100, 100)


def test_reach_decides_the_engagement_band_not_the_card() -> None:
    """The hound melees because its range is 20, not because it is a hound."""
    assert capabilities_of(make_unit("a", HOUND, "north", HERE)).engagement == "melee"
    assert capabilities_of(make_unit("b", ADEPT, "north", HERE)).engagement == "ranged"


def test_a_unit_whose_reach_is_cut_stops_being_ranged() -> None:
    """This is the whole point: fighting style follows the stats as they stand.

    Nothing has edited a profile, and no new creature type exists. The adept's
    range dropped, so the adept is no longer something that can skirmish.
    """
    adept = make_unit("a", ADEPT, "north", HERE)
    assert supports(capabilities_of(adept), "ranged_attack")

    adept.range = 10

    assert capabilities_of(adept).engagement == "melee"
    assert not supports(capabilities_of(adept), "ranged_attack")


def test_a_rooted_unit_cannot_move_and_a_harmless_one_cannot_attack() -> None:
    wisp = capabilities_of(make_unit("w", WISP, "north", HERE))

    assert not wisp.can_move
    assert not wisp.can_attack
    assert missing_capabilities(wisp, ("move", "attack")) == ("move", "attack")


def test_health_fraction_tracks_damage_taken() -> None:
    hound = make_unit("h", HOUND, "north", HERE, hp=HOUND.max_hp / 4)

    assert capabilities_of(hound).health_fraction == pytest.approx(0.25)


def test_an_unknown_capability_is_a_clear_error() -> None:
    capabilities = capabilities_of(make_unit("h", HOUND, "north", HERE))

    with pytest.raises(ValueError, match="is not a capability"):
        supports(capabilities, "teleport")  # type: ignore[arg-type]
