"""Reading, refusing and fielding a submitted plan.

**The server owns validation and the energy spend.** A plan arrives from a phone
over a socket, so nothing about it is trusted. JQ-308 deepens these rules; what
is pinned here is that an illegal plan never becomes an army.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.match import fixtures
from app.match.plan import (
    PlanError,
    default_plan,
    fielded_mages,
    parse_plan,
    resolve_loadout,
    to_army_setup,
    validate_plan,
)

MAP = fixtures.map_config()


def _plan(**overrides: Any) -> dict[str, Any]:
    base = fixtures.opening_plan_json(1, MAP)
    base.update(overrides)
    return base


def test_the_suggested_default_is_one_the_server_would_accept() -> None:
    # A player who does nothing still fields an army (JQ-308's lifecycle rule).
    # A default the validator rejects would strand exactly that player.
    plan = default_plan(MAP)
    validate_plan(plan, MAP)
    assert len(plan.troops) == fixtures.MAGE_CAP


def test_the_default_spreads_its_troops_across_the_orders() -> None:
    plan = default_plan(MAP)
    orders = {(troop.order.kind, troop.order.zone_id) for troop in plan.troops}
    # Three troops stacked on one lane makes the demo's first battle a rout and
    # teaches a first-time player the wrong thing about orders.
    assert len(orders) == 3


def test_a_plan_round_trips_through_the_parser() -> None:
    plan = parse_plan(_plan())
    assert [troop.mage_id for troop in plan.troops] == ["ember-adept"] * 3
    assert plan.spell_slots == ("meteor", None)


# ------------------------------------------------------------- refusals --


def test_an_empty_plan_is_refused() -> None:
    with pytest.raises(PlanError, match="at least one troop"):
        validate_plan(parse_plan(_plan(troops=[])), MAP)


def test_more_troops_than_the_mage_cap_is_refused() -> None:
    troops = _plan()["troops"]
    with pytest.raises(PlanError, match="at most 3 mages"):
        validate_plan(parse_plan(_plan(troops=[*troops, troops[0]])), MAP)


def test_a_mage_not_on_the_roster_is_refused() -> None:
    with pytest.raises(PlanError, match="not a mage on this roster"):
        validate_plan(
            parse_plan(
                _plan(
                    troops=[
                        {
                            "mageId": "archmage-of-cheating",
                            "summonIds": [],
                            "order": {"kind": "defendBase"},
                        }
                    ]
                )
            ),
            MAP,
        )


def test_a_summon_not_on_the_roster_is_refused() -> None:
    with pytest.raises(PlanError, match="not a summon on this roster"):
        validate_plan(
            parse_plan(
                _plan(
                    troops=[
                        {"mageId": "ember-adept", "summonIds": ["dragon"], "order": {"kind": "defendBase"}}
                    ]
                )
            ),
            MAP,
        )


def test_an_order_this_map_cannot_be_given_is_refused() -> None:
    with pytest.raises(PlanError):
        validate_plan(
            parse_plan(
                _plan(
                    troops=[
                        {
                            "mageId": "ember-adept",
                            "summonIds": [],
                            "order": {"kind": "holdZone", "zoneId": "Q"},
                        }
                    ]
                )
            ),
            MAP,
        )


def test_a_hold_order_naming_no_zone_is_refused() -> None:
    with pytest.raises(PlanError, match="must name the zone"):
        parse_plan(_plan(troops=[{"mageId": "ember-adept", "summonIds": [], "order": {"kind": "holdZone"}}]))


def test_exceeding_a_mages_support_capacity_is_refused() -> None:
    # Ember Adept supports 3 points; Ash Ram and Slag Wall cost 2 each.
    with pytest.raises(PlanError, match="supports 3 points"):
        validate_plan(
            parse_plan(
                _plan(
                    troops=[
                        {
                            "mageId": "ember-adept",
                            "summonIds": ["ash-ram", "slag-wall"],
                            "order": {"kind": "defendBase"},
                        }
                    ]
                )
            ),
            MAP,
        )


def test_the_summon_pool_is_counted_across_the_whole_plan() -> None:
    """The roster is a multiset owned by the *side*, not by each troop.

    Counting per troop is the mistake that lets three troops each field the one
    Slag Wall the side owns.
    """
    troop = {"mageId": "ember-adept", "summonIds": ["slag-wall"], "order": {"kind": "defendBase"}}
    hold_w = {**troop, "order": {"kind": "holdZone", "zoneId": "W"}}
    with pytest.raises(PlanError, match="only 1 Slag Wall available"):
        validate_plan(parse_plan(_plan(troops=[troop, hold_w])), MAP)


def test_more_spells_than_there_are_slots_is_refused() -> None:
    with pytest.raises(PlanError, match="at most 2 spells"):
        parse_plan(_plan(spellSlots=["meteor", "meteor", "meteor"]))


def test_a_spell_whose_requirement_is_unmet_is_refused() -> None:
    # Meteor is Ember Adept's signature. With no Ember Adept fielded it is not
    # merely greyed out on screen — the server refuses to field it, because a
    # client that ignored the grey-out would otherwise be taking it anyway.
    plan = parse_plan(_plan(troops=[], spellSlots=["meteor"]))
    with pytest.raises(PlanError):
        validate_plan(plan, MAP)


def test_an_empty_spell_slot_is_legal() -> None:
    validate_plan(parse_plan(_plan(spellSlots=[None, None])), MAP)


# ------------------------------------------------------------ resolution --


def test_a_loadout_carries_the_resolved_cost_and_effect() -> None:
    loadout = resolve_loadout(default_plan(MAP))
    assert len(loadout) == 1
    spell = loadout[0]
    assert spell.spell_id == "meteor"
    assert spell.cost == 35.0
    # Three fielded Ember Adepts, each tagged `pyromancer`: 30 + 3 x 11.
    assert "63" in spell.effect
    assert "3 fielded mages" in spell.effect


def test_resolution_is_stable_across_processes() -> None:
    """No set iteration anywhere in the resolved sentence.

    Two servers resolving the same plan to differently-worded effects is the
    hash-ordering hazard `api/CONVENTIONS.md` is about, in a place nobody would
    think to look for it.
    """
    plan = default_plan(MAP)
    first = resolve_loadout(plan)[0].effect
    for _ in range(20):
        assert resolve_loadout(plan)[0].effect == first


def test_fielded_mages_are_returned_in_troop_order() -> None:
    plan = default_plan(MAP)
    assert [mage.id for mage in fielded_mages(plan)] == [troop.mage_id for troop in plan.troops]


# -------------------------------------------------------------- sim input --


def test_an_army_carries_orders_and_no_positions() -> None:
    army = to_army_setup(default_plan(MAP), "north")
    assert army.side == "north"
    assert len(army.troops) == 3
    for troop in army.troops:
        assert troop.order is not None
        # The design's central constraint (§6.1): a plan gives an order, never a
        # placement. `formation.py` derives the rest.
        assert not hasattr(troop, "position")
        assert not hasattr(troop, "stance")
