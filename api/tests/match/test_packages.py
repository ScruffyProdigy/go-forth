"""The five-package menu, and what makes one valid."""

from __future__ import annotations

import pytest

from app.match import OPENING_CATALOG, MagePackage, PackageCatalog, validate_catalog
from app.match.packages import PROVISIONAL_SPELLS
from app.sim import PLACEHOLDER_UNIT_TYPES, RosterEntry
from tests.match.helpers import STONE_SUMMON


def test_the_opening_menu_offers_five_unique_packages() -> None:
    validate_catalog(OPENING_CATALOG, expected=5)
    assert len({package.id for package in OPENING_CATALOG.packages}) == 5


def test_every_package_has_a_fixed_entourage_and_two_eligible_spells() -> None:
    for package in OPENING_CATALOG.packages:
        assert package.entourage, f"{package.id} fields no summons"
        assert len(package.spell_ids) == 2, f"{package.id} does not offer two spells"


def test_every_entourage_fits_the_mage_that_carries_it() -> None:
    """Capacity is a property of the menu, not only of a plan: a package that
    could never be fielded legally should never be on offer."""
    types = OPENING_CATALOG.types
    for package in OPENING_CATALOG.packages:
        capacity = types[package.mage_type_id].support_capacity or 0
        size = sum(entry.count for entry in package.entourage)
        assert size <= capacity, f"{package.id} fields {size} behind a capacity of {capacity}"


def test_eligible_spells_are_the_union_of_the_chosen_packages() -> None:
    eligible = OPENING_CATALOG.eligible_spells(["hound-pair", "ram-guard"])
    assert eligible == ("meteor", "ember-surge", "scorch-line")


def test_eligible_spells_come_back_in_menu_order_not_hash_order() -> None:
    """Ordering is stable across processes because it is derived from the menu
    rather than from a set. See the hash-ordering note in `sim/rng.py`."""
    forwards = OPENING_CATALOG.eligible_spells(["hound-pair", "ram-guard", "sprite-pair"])
    backwards = OPENING_CATALOG.eligible_spells(["sprite-pair", "ram-guard", "hound-pair"])
    assert forwards == backwards


def test_a_menu_of_the_wrong_size_is_rejected() -> None:
    catalog = PackageCatalog(
        packages=OPENING_CATALOG.packages[:4],
        unit_types=OPENING_CATALOG.unit_types,
        spells=OPENING_CATALOG.spells,
    )
    with pytest.raises(ValueError, match="offers 5 packages"):
        validate_catalog(catalog, expected=5)


def test_a_package_fielding_an_unknown_card_is_rejected() -> None:
    catalog = PackageCatalog(
        packages=(*OPENING_CATALOG.packages[:4], MagePackage("ghost", "Ghost", "no-such-mage")),
        unit_types=OPENING_CATALOG.unit_types,
        spells=OPENING_CATALOG.spells,
    )
    with pytest.raises(ValueError, match="not a card"):
        validate_catalog(catalog, expected=5)


def test_a_package_offering_an_unknown_spell_is_rejected() -> None:
    broken = MagePackage("odd", "Odd", "ember-adept", (RosterEntry("cinder-hound"),), ("no-such-spell",))
    catalog = PackageCatalog(
        packages=(*OPENING_CATALOG.packages[:4], broken),
        unit_types=OPENING_CATALOG.unit_types,
        spells=OPENING_CATALOG.spells,
    )
    with pytest.raises(ValueError, match="not in the catalog"):
        validate_catalog(catalog, expected=5)


def test_a_package_listing_a_mage_as_a_summon_is_rejected() -> None:
    broken = MagePackage("odd", "Odd", "ember-adept", (RosterEntry("ember-adept"),), ("meteor",))
    catalog = PackageCatalog(
        packages=(*OPENING_CATALOG.packages[:4], broken),
        unit_types=OPENING_CATALOG.unit_types,
        spells=OPENING_CATALOG.spells,
    )
    with pytest.raises(ValueError, match="as a summon"):
        validate_catalog(catalog, expected=5)


def test_a_stone_summon_passes_the_catalog_and_is_caught_by_the_plan_instead() -> None:
    """The catalog checks card *kinds*; school support is a troop-level rule and
    belongs to plan validation, which `test_plan.py` covers. Asserting it here
    keeps the division deliberate rather than accidental."""
    broken = MagePackage("odd", "Odd", "ember-adept", (RosterEntry("granite-ward"),), ("meteor",))
    catalog = PackageCatalog(
        packages=(*OPENING_CATALOG.packages[:4], broken),
        unit_types=(*PLACEHOLDER_UNIT_TYPES, STONE_SUMMON),
        spells=tuple(PROVISIONAL_SPELLS),
    )
    validate_catalog(catalog, expected=5)
