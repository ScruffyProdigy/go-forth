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
    resolve_snapshot,
    spell_menu,
    to_army_setup,
    validate_plan,
)
from app.sim.spellbook import read_field

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
    assert plan.spell_slots == ("fireball", "ember-spark")


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
        parse_plan(_plan(spellSlots=["fireball", "fireball", "fireball"]))


def test_a_spell_whose_requirement_is_unmet_is_refused() -> None:
    # Fireball is Ember Adept's signature. With no Ember Adept fielded it is not
    # merely greyed out on screen — the server refuses to field it, because a
    # client that ignored the grey-out would otherwise be taking it anyway.
    plan = parse_plan(_plan(troops=[], spellSlots=["fireball"]))
    with pytest.raises(PlanError):
        validate_plan(plan, MAP)


def test_an_empty_spell_slot_is_legal() -> None:
    validate_plan(parse_plan(_plan(spellSlots=[None, None])), MAP)


# ------------------------------------------------------------ resolution --


def test_a_loadout_carries_the_resolved_cost_and_effect() -> None:
    loadout = resolve_loadout(default_plan(MAP))
    assert [spell.spell_id for spell in loadout] == ["fireball", "ember-spark"]

    fireball = loadout[0]
    assert fireball.cost == 35.0
    # Three fielded Ember Adepts, each tagged `evocation` and `reckless`. Damage
    # 28 + 3x8 capped at 24 -> 52; radius 45 + 3x6 capped at 12 -> 57. Two tags,
    # two numbers, two caps, and nothing multiplied.
    assert "damage amount 52" in fireball.effect
    assert "radius 57" in fireball.effect
    assert fireball.tag_support == (("evocation", 3), ("reckless", 3))


def test_a_loadout_names_the_mages_that_raised_it() -> None:
    fireball = resolve_loadout(default_plan(MAP))[0]

    assert [(who.mage_id, who.tag) for who in fireball.contributors] == [
        ("troop-1", "evocation"),
        ("troop-1", "reckless"),
        ("troop-2", "evocation"),
        ("troop-2", "reckless"),
        ("troop-3", "evocation"),
        ("troop-3", "reckless"),
    ]


def test_a_fallback_in_the_loadout_carries_its_printed_numbers() -> None:
    """Ember Spark scales with nothing, so three mages change it not at all."""
    spark = resolve_loadout(default_plan(MAP))[1]

    assert spark.cost == 12.0
    assert spark.contributors == ()


def test_the_snapshot_is_what_the_battle_will_fire() -> None:
    snapshot = resolve_snapshot(default_plan(MAP), "north")
    spells = {spell.id: spell for spell in snapshot.sim_spells()}

    assert sorted(spells) == ["north:ember-spark", "north:fireball"]
    blast = spells["north:fireball"].effects[0]
    assert read_field(blast, "damage.amount") == 52
    assert read_field(blast, "radius") == 57


def test_the_two_sides_get_their_own_copies_of_one_spell() -> None:
    plan = default_plan(MAP)
    ids = [spell.id for side in ("north", "south") for spell in resolve_snapshot(plan, side).sim_spells()]

    assert len(set(ids)) == len(ids)


def test_an_independent_spell_off_the_roster_is_greyed_with_its_reason() -> None:
    """Smoke Veil is owned, and no fielded mage carries `warding`."""
    entry = spell_menu(default_plan(MAP)).entry("smoke-veil")

    assert entry is not None and not entry.eligible
    assert entry.reason == "needs a fielded warding mage"


def test_resolution_is_stable_across_processes() -> None:
    """No set iteration anywhere in the resolved loadout.

    Two servers resolving the same plan to different numbers or a differently
    ordered contributor list is the hash-ordering hazard `api/CONVENTIONS.md` is
    about, in a place nobody would think to look for it.
    """
    plan = default_plan(MAP)
    first = resolve_loadout(plan)
    for _ in range(20):
        assert resolve_loadout(plan) == first


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
