"""Legal plans, the suggested default, and every way a plan can be refused.

Rejections are asserted on their `reason` code rather than on message text: the
codes are what a client keys off, and JQ-308 asks for the policy to be explicit.
"""

from __future__ import annotations

import pytest

from app.match import (
    OPENING_CATALOG,
    SINGLE_ROUND_TEST_PROFILE,
    MagePackage,
    PackageCatalog,
    Plan,
    PlanRejected,
    TroopPlan,
    suggested_plan,
    validate_plan,
)
from app.match.packages import PROVISIONAL_SPELLS
from app.sim import (
    DEFEND_BASE,
    PLACEHOLDER_UNIT_TYPES,
    PUSH_ENEMY_BASE,
    TWO_LANE_MAP,
    RosterEntry,
    Side,
    hold,
    legal_orders,
)
from tests.match.helpers import STONE_SUMMON, STRAINED_MAGE

PROFILE = SINGLE_ROUND_TEST_PROFILE


def check(plan: Plan, catalog: PackageCatalog = OPENING_CATALOG) -> None:
    validate_plan(plan, catalog, TWO_LANE_MAP, PROFILE)


def rejection(plan: Plan, catalog: PackageCatalog = OPENING_CATALOG) -> str:
    with pytest.raises(PlanRejected) as raised:
        check(plan, catalog)
    return raised.value.reason


def legal() -> Plan:
    return suggested_plan("north", OPENING_CATALOG, TWO_LANE_MAP, PROFILE)


# --- the suggested default -------------------------------------------------


@pytest.mark.parametrize("side", ["north", "south"])
def test_the_suggested_default_is_itself_legal(side: Side) -> None:
    """The whole point of it. A default that could be illegal would turn a
    missed plan into a crash at the worst possible moment."""
    check(suggested_plan(side, OPENING_CATALOG, TWO_LANE_MAP, PROFILE))


def test_the_suggested_default_is_the_same_for_both_sides() -> None:
    """The map is symmetric; a default that differed by side would hand one of
    them an opening the other has to find."""
    north = suggested_plan("north", OPENING_CATALOG, TWO_LANE_MAP, PROFILE)
    south = suggested_plan("south", OPENING_CATALOG, TWO_LANE_MAP, PROFILE)
    assert north == south


def test_the_suggested_default_spreads_across_the_lanes_then_pushes() -> None:
    orders = [troop.order for troop in legal().troops]
    assert orders == [hold("W"), hold("E"), PUSH_ENEMY_BASE]


def test_the_suggested_default_carries_a_full_spell_loadout() -> None:
    assert len(legal().spell_ids) == PROFILE.spells_per_round


# --- troop composition -----------------------------------------------------


def test_a_legal_plan_passes() -> None:
    check(
        Plan(
            troops=(
                TroopPlan("hound-pair", hold("W")),
                TroopPlan("ram-guard", hold("E")),
                TroopPlan("skirmish", DEFEND_BASE),
            ),
            spell_ids=("meteor", "scorch-line"),
        )
    )


@pytest.mark.parametrize("count", [2, 4])
def test_the_wrong_number_of_troops_is_refused(count: int) -> None:
    ids = ["hound-pair", "ram-and-sprite", "sprite-pair", "ram-guard"][:count]
    plan = Plan(
        troops=tuple(TroopPlan(pid, PUSH_ENEMY_BASE) for pid in ids),
        spell_ids=("meteor", "ember-surge"),
    )
    assert rejection(plan) == "wrongTroopCount"


def test_choosing_the_same_package_twice_is_refused() -> None:
    plan = Plan(
        troops=(
            TroopPlan("hound-pair", hold("W")),
            TroopPlan("hound-pair", hold("E")),
            TroopPlan("sprite-pair", PUSH_ENEMY_BASE),
        ),
        spell_ids=("meteor", "ember-surge"),
    )
    assert rejection(plan) == "duplicatePackage"


def test_a_package_that_is_not_on_the_menu_is_refused() -> None:
    plan = Plan(
        troops=(
            TroopPlan("hound-pair", hold("W")),
            TroopPlan("smuggled-in", hold("E")),
            TroopPlan("sprite-pair", PUSH_ENEMY_BASE),
        ),
        spell_ids=("meteor", "ember-surge"),
    )
    assert rejection(plan) == "unknownPackage"


def test_an_order_the_map_does_not_offer_is_refused() -> None:
    plan = Plan(
        troops=(
            TroopPlan("hound-pair", hold("N")),
            TroopPlan("ram-and-sprite", hold("E")),
            TroopPlan("sprite-pair", PUSH_ENEMY_BASE),
        ),
        spell_ids=("meteor", "ember-surge"),
    )
    assert rejection(plan) == "illegalOrder"


def test_every_order_the_map_offers_is_accepted() -> None:
    """The complement of the test above. An allow-list that rejects a legal
    order is the failure nobody writes a test for."""
    for order in legal_orders(TWO_LANE_MAP):
        check(
            Plan(
                troops=(
                    TroopPlan("hound-pair", order),
                    TroopPlan("ram-and-sprite", order),
                    TroopPlan("sprite-pair", order),
                ),
                spell_ids=("meteor", "ember-surge"),
            )
        )


# --- capacity and support --------------------------------------------------


def _catalog_with(package: MagePackage) -> PackageCatalog:
    return PackageCatalog(
        packages=(*OPENING_CATALOG.packages[:2], package, *OPENING_CATALOG.packages[3:]),
        unit_types=(*PLACEHOLDER_UNIT_TYPES, STRAINED_MAGE, STONE_SUMMON),
        spells=tuple(PROVISIONAL_SPELLS),
    )


def _plan_including(package_id: str) -> Plan:
    return Plan(
        troops=(
            TroopPlan("hound-pair", hold("W")),
            TroopPlan("ram-and-sprite", hold("E")),
            TroopPlan(package_id, PUSH_ENEMY_BASE),
        ),
        spell_ids=("meteor", "ember-surge"),
    )


def test_an_entourage_larger_than_its_mage_supports_is_refused() -> None:
    catalog = _catalog_with(
        MagePackage(
            "overloaded",
            "Overloaded",
            "spent-adept",
            (RosterEntry("cinder-hound", 2),),
            ("meteor", "ember-surge"),
        )
    )
    assert rejection(_plan_including("overloaded"), catalog) == "overCapacity"


def test_a_summon_no_mage_in_its_troop_can_support_is_refused() -> None:
    """Support is mandatory and local (§4.2) — the same rule `world.py` enforces
    at build time, applied early so it is a rejection rather than a crash."""
    catalog = _catalog_with(
        MagePackage(
            "mismatched",
            "Mismatched",
            "ember-adept",
            (RosterEntry("granite-ward"),),
            ("meteor", "ember-surge"),
        )
    )
    assert rejection(_plan_including("mismatched"), catalog) == "unsupportedSummon"


# --- the round loadout -----------------------------------------------------


@pytest.mark.parametrize("spells", [(), ("meteor",), ("meteor", "ember-surge", "scorch-line")])
def test_the_wrong_number_of_spells_is_refused(spells: tuple[str, ...]) -> None:
    plan = Plan(troops=legal().troops, spell_ids=spells)
    assert rejection(plan) == "wrongSpellCount"


def test_carrying_the_same_spell_twice_is_refused() -> None:
    plan = Plan(troops=legal().troops, spell_ids=("meteor", "meteor"))
    assert rejection(plan) == "duplicateSpell"


def test_a_spell_no_chosen_package_offers_is_refused() -> None:
    """`scorch-line` is real, and belongs to packages this plan did not take."""
    plan = Plan(
        troops=(
            TroopPlan("hound-pair", hold("W")),
            TroopPlan("ram-and-sprite", hold("E")),
            TroopPlan("sprite-pair", PUSH_ENEMY_BASE),
        ),
        spell_ids=("meteor", "scorch-line"),
    )
    assert rejection(plan) == "ineligibleSpell"


def test_a_spell_becomes_eligible_once_its_package_is_chosen() -> None:
    """The complement: the rule is about the chosen set, not a fixed list."""
    check(
        Plan(
            troops=(
                TroopPlan("hound-pair", hold("W")),
                TroopPlan("ram-and-sprite", hold("E")),
                TroopPlan("ram-guard", PUSH_ENEMY_BASE),
            ),
            spell_ids=("meteor", "scorch-line"),
        )
    )
