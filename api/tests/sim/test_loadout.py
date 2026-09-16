"""The resolver: eligibility, counting, per-effect curves, and the snapshot.

The acceptance criteria JQ-297 lists as testable are here, one section each:
zero support, multi-tag contribution, duplicate grants, independent and
fallback access, invalidation after a troop edit, and the early and late values
of a capped curve. Two criteria are exercised where they actually live rather
than here — a contributor dying after lock-in is `tests/match/test_round.py`,
and cross-language agreement is `tests/sim/test_conformance.py`.
"""

from __future__ import annotations

import pytest

from app.sim.effects import AreaDamage, BurningGround, DamageProfile, Knockback
from app.sim.loadout import (
    DeployedMage,
    LoadoutError,
    LoadoutMenu,
    LoadoutRules,
    LoadoutSnapshot,
    ResolvedSpell,
    preserved_selection,
    resolve_menu,
    resolve_slots,
    resolve_spell,
    snapshot_loadout,
    tag_support,
)
from app.sim.spellbook import (
    AlwaysAvailable,
    EffectScaling,
    IndependentAccess,
    SignatureOf,
    SpellDefinition,
    build_definition_catalog,
    read_field,
)

# A two-tag spell, the shape JQ-292 asks to see demonstrated: damage rises with
# one tag's count and radius with another's, each on its own bounded curve.
FIREBALL = SpellDefinition(
    id="fireball",
    name="Fireball",
    cost=35.0,
    text="A burst of fire.",
    access=SignatureOf("adept"),
    effects=(
        AreaDamage(radius=40, damage=DamageProfile(amount=20)),
        BurningGround(radius=40, damage_per_second=4, duration_seconds=3),
    ),
    scaling=(
        EffectScaling(0, "damage.amount", "evocation", per_mage=10, cap=30),
        EffectScaling(0, "radius", "reckless", per_mage=5, cap=10),
    ),
)

SPARK = SpellDefinition(
    id="spark",
    name="Spark",
    cost=5.0,
    text="A cheap jolt.",
    access=AlwaysAvailable(),
    effects=(AreaDamage(radius=15, damage=DamageProfile(amount=6)),),
)

# Threshold 1: the first warding mage unlocks it and adds nothing.
VEIL = SpellDefinition(
    id="veil",
    name="Veil",
    cost=20.0,
    text="A shove of smoke.",
    access=IndependentAccess(requires_tag="warding", minimum=1),
    effects=(Knockback(radius=30, distance=20),),
    scaling=(EffectScaling(0, "distance", "warding", per_mage=5, cap=15, threshold=1),),
)

CATALOG = build_definition_catalog([FIREBALL, SPARK, VEIL])
ROSTER = ("veil",)


def mage(instance: str, type_id: str = "adept", *tags: str, name: str = "") -> DeployedMage:
    return DeployedMage(instance_id=instance, type_id=type_id, name=name or instance, tags=tags)


def menu(*mages: DeployedMage, roster: tuple[str, ...] = ROSTER) -> LoadoutMenu:
    return resolve_menu(mages=mages, roster_access=roster, definitions=CATALOG)


def _spell(resolved: LoadoutMenu, definition_id: str) -> ResolvedSpell:
    """The menu entry that must be there. Raises rather than silently returning
    None, which an `assert x is not None` on every call site would only hide."""
    entry = resolved.entry(definition_id)
    assert entry is not None
    return entry.spell


# ------------------------------------------------------------------ counting --


def test_a_mage_counts_once_per_tag_it_carries() -> None:
    assert tag_support([mage("m1", "adept", "evocation", "reckless")]) == (
        ("evocation", 1),
        ("reckless", 1),
    )


def test_two_instances_of_one_mage_type_count_twice() -> None:
    """Two mages on the field are two mages, however they were authored."""
    support = tag_support([mage("m1", "adept", "evocation"), mage("m2", "adept", "evocation")])

    assert support == (("evocation", 2),)


def test_a_tag_listed_twice_on_one_mage_counts_once() -> None:
    assert tag_support([mage("m1", "adept", "evocation", "evocation")]) == (("evocation", 1),)


def test_tag_combinations_are_never_counted() -> None:
    """A mage carrying both tags raises both counts by one, and nothing else.

    The negative half of JQ-297's "never count tag combinations": there is no
    third count anywhere that a spell could read as "mages carrying both".
    """
    support = dict(tag_support([mage("m1", "adept", "evocation", "reckless")]))

    assert support == {"evocation": 1, "reckless": 1}


def test_support_is_sorted_by_tag() -> None:
    support = tag_support([mage("m1", "adept", "warding", "evocation", "reckless")])

    assert [tag for tag, _ in support] == sorted(tag for tag, _ in support)


# -------------------------------------------------------------- zero support --


def test_zero_support_leaves_every_number_at_its_base() -> None:
    resolved = resolve_spell(FIREBALL, [])

    assert read_field(resolved.effects[0], "damage.amount") == 20
    assert read_field(resolved.effects[0], "radius") == 40
    assert [entry.bonus for entry in resolved.scaled] == [0, 0]
    assert resolved.contributors == ()


def test_a_spell_that_scales_with_nothing_resolves_to_its_card() -> None:
    resolved = resolve_spell(SPARK, [mage("m1", "adept", "evocation")])

    assert resolved.effects == SPARK.effects
    assert resolved.scaled == ()


# ------------------------------------------------------------------ multi-tag --


def test_two_tags_raise_two_different_numbers_independently() -> None:
    """One `evocation` mage and two `reckless` ones move damage and radius by
    different amounts, from different counts, with nothing multiplied."""
    resolved = resolve_spell(
        FIREBALL,
        [
            mage("m1", "adept", "evocation"),
            mage("m2", "adept", "reckless"),
            mage("m3", "adept", "reckless"),
        ],
    )

    assert read_field(resolved.effects[0], "damage.amount") == 20 + 10  # one evocation
    assert read_field(resolved.effects[0], "radius") == 40 + 10  # two reckless, at the cap


def test_a_dual_tagged_mage_raises_each_number_once() -> None:
    """The multiplication that must not happen.

    One mage carrying both tags contributes 1 to each count. Damage moves by one
    step and radius by one step — not by one step each *times* anything, and not
    by a step for the pair.
    """
    resolved = resolve_spell(FIREBALL, [mage("m1", "adept", "evocation", "reckless")])

    assert read_field(resolved.effects[0], "damage.amount") == 30
    assert read_field(resolved.effects[0], "radius") == 45


def test_the_untouched_effect_keeps_its_base_numbers() -> None:
    """Scaling is per field. The burning ground has no curve, so it does not move."""
    resolved = resolve_spell(FIREBALL, [mage("m1", "adept", "evocation", "reckless")])

    assert resolved.effects[1] == FIREBALL.effects[1]


def test_contributors_name_every_carrier_in_plan_order() -> None:
    resolved = resolve_spell(
        FIREBALL,
        [mage("m1", "adept", "reckless"), mage("m2", "adept", "evocation", "reckless")],
    )

    assert [(who.instance_id, who.tag) for who in resolved.contributors] == [
        ("m1", "reckless"),
        # Tag order is the spell's — evocation is read first — not the mage's.
        ("m2", "evocation"),
        ("m2", "reckless"),
    ]


# ----------------------------------------------------------------------- caps --


def test_the_early_value_of_a_curve_with_a_threshold_is_the_base() -> None:
    """One warding mage unlocks the veil and moves nothing."""
    resolved = resolve_spell(VEIL, [mage("m1", "warden", "warding")])

    assert read_field(resolved.effects[0], "distance") == 20
    assert resolved.scaled[0].support == 1
    assert resolved.scaled[0].bonus == 0
    assert not resolved.scaled[0].capped


def test_the_late_value_of_a_curve_stops_at_its_cap() -> None:
    wardens = [mage(f"m{i}", "warden", "warding") for i in range(9)]
    resolved = resolve_spell(VEIL, wardens)

    assert read_field(resolved.effects[0], "distance") == 20 + 15
    assert resolved.scaled[0].capped


def test_landing_exactly_on_the_cap_reports_as_capped() -> None:
    """The boundary the conventions file keeps catching in geometry, in scoring.

    Four wardens is `5 * (4 - 1) = 15`, exactly the cap. A strict `>` here would
    report the first fully-capped plan as still climbing, and a screen saying
    "one more mage helps" when it does not is worse than no screen.
    """
    wardens = [mage(f"m{i}", "warden", "warding") for i in range(4)]
    entry = resolve_spell(VEIL, wardens).scaled[0]

    assert entry.bonus == 15
    assert entry.capped


def test_a_spell_with_no_cap_to_reach_is_never_reported_as_capped() -> None:
    """`cap=0` is a curve that does nothing, not a curve permanently at its cap."""
    flat = SpellDefinition(
        id="flat",
        name="Flat",
        cost=1.0,
        text="",
        access=AlwaysAvailable(),
        effects=(AreaDamage(radius=10, damage=DamageProfile(amount=1)),),
        scaling=(EffectScaling(0, "radius", "evocation", per_mage=0, cap=0),),
    )

    entry = resolve_spell(flat, [mage("m1", "adept", "evocation")]).scaled[0]

    assert entry.bonus == 0
    assert not entry.capped


# --------------------------------------------------------------------- access --


def test_a_signature_needs_its_mage_on_the_field() -> None:
    absent = menu(mage("m1", "warden", "warding")).entry("fireball")
    present = menu(mage("m1", "adept", "evocation")).entry("fireball")

    assert absent is not None and not absent.eligible
    assert absent.reason == "needs its mage on the field"
    assert present is not None and present.eligible


def test_duplicate_signature_grants_produce_one_menu_entry() -> None:
    resolved = menu(mage("m1", "adept", "evocation"), mage("m2", "adept", "evocation"))

    fireballs = [entry for entry in resolved.entries if entry.spell.definition_id == "fireball"]
    assert len(fireballs) == 1
    # Both are still named — the screen has to be able to say who granted it.
    assert fireballs[0].spell.granted_by == ("m1", "m2")


def test_a_fallback_is_available_with_nothing_fielded() -> None:
    entry = menu().entry("spark")

    assert entry is not None and entry.eligible


def test_an_independent_spell_off_the_roster_is_refused_before_its_tag_is_read() -> None:
    """Two gates, and the roster one is first.

    The reason never says "and you also lack the tag": that would enumerate a
    roster the player does not own, one greyed card at a time.
    """
    entry = menu(mage("m1", "warden", "warding"), roster=()).entry("veil")

    assert entry is not None and not entry.eligible
    assert entry.reason == "is not on this roster"


def test_an_independent_spell_on_the_roster_still_needs_its_tag() -> None:
    entry = menu(mage("m1", "adept", "evocation")).entry("veil")

    assert entry is not None and not entry.eligible
    assert entry.reason == "needs a fielded warding mage"


def test_an_independent_spell_with_both_gates_open_is_eligible() -> None:
    entry = menu(mage("m1", "warden", "warding")).entry("veil")

    assert entry is not None and entry.eligible


def test_a_higher_minimum_is_reported_in_the_plural() -> None:
    catalog = build_definition_catalog(
        [
            SpellDefinition(
                id="rite",
                name="Rite",
                cost=1.0,
                text="",
                access=IndependentAccess(requires_tag="necromancy", minimum=2),
                effects=(AreaDamage(radius=10, damage=DamageProfile(amount=1)),),
            )
        ]
    )
    resolved = resolve_menu(
        mages=[mage("m1", "adept", "necromancy")], roster_access=("rite",), definitions=catalog
    )

    entry = resolved.entry("rite")
    assert entry is not None and not entry.eligible
    assert entry.reason == "needs 2 fielded necromancy mages"


def test_a_tag_never_grants_faction_membership() -> None:
    """JQ-297, stated as a test rather than as a comment.

    A Fire mage tagged `artifice` is a mage who works in artifice. It grants
    access to exactly the spells whose rules name the tag, and to nothing that
    belongs to the Artifice faction — which here is the whole of the rest of the
    menu, because the resolver is never given a school to consult.
    """
    artificer = DeployedMage(instance_id="m1", type_id="smith", name="Fire mage", tags=("artifice",))
    resolved = menu(artificer)

    assert resolved.eligible_ids() == ("spark",)
    assert resolved.support_for("artifice") == 1


def test_ineligible_spells_stay_on_the_menu_with_their_numbers() -> None:
    """A greyed card still shows what it would do, so the link teaches itself."""
    entry = menu(mage("m1", "adept", "evocation"), roster=()).entry("veil")

    assert entry is not None and not entry.eligible
    assert read_field(entry.spell.effects[0], "distance") == 20


# ----------------------------------------------------------------- troop edits --


def test_editing_troops_changes_eligibility_immediately() -> None:
    with_adept = menu(mage("m1", "adept", "evocation"))
    without = menu(mage("m1", "warden", "warding"))

    assert "fireball" in with_adept.eligible_ids()
    assert "fireball" not in without.eligible_ids()


def test_editing_troops_changes_the_preview_immediately() -> None:
    one = menu(mage("m1", "adept", "evocation"))
    two = menu(mage("m1", "adept", "evocation"), mage("m2", "adept", "evocation"))

    assert read_field(_spell(one, "fireball").effects[0], "damage.amount") == 30
    assert read_field(_spell(two, "fireball").effects[0], "damage.amount") == 40


def test_a_slot_stranded_by_a_troop_edit_is_reported_not_cleared() -> None:
    edited = menu(mage("m1", "warden", "warding"))
    slots = resolve_slots(edited, ["fireball", "spark"])

    assert slots[0].stranded
    assert slots[0].definition_id == "fireball"
    assert slots[0].reason == "needs its mage on the field"
    assert not slots[1].stranded


def test_an_empty_slot_is_legal() -> None:
    slots = resolve_slots(menu(mage("m1", "adept", "evocation")), ["fireball", None])

    assert not slots[1].stranded
    assert slots[1].spell is None


def test_a_slot_naming_an_unknown_spell_is_stranded() -> None:
    slots = resolve_slots(menu(mage("m1", "adept", "evocation")), ["pyroclasm"])

    assert slots[0].stranded
    assert slots[0].reason == "is not a spell on this roster"


def test_more_slots_than_the_rules_allow_are_refused() -> None:
    with pytest.raises(LoadoutError, match="at most 2 spells"):
        resolve_slots(menu(mage("m1", "adept", "evocation")), ["spark", "spark", "spark"])


# ------------------------------------------------------ preserved reselection --


def test_a_new_round_keeps_the_choices_that_are_still_legal() -> None:
    kept = preserved_selection(menu(mage("m1", "adept", "evocation")), ["fireball", "veil"])

    assert kept == ("fireball", None)


def test_a_selection_shorter_than_the_slots_is_padded() -> None:
    assert preserved_selection(menu(mage("m1", "adept", "evocation")), ["fireball"]) == (
        "fireball",
        None,
    )


def test_a_policy_that_does_not_reselect_hands_back_what_it_was_given() -> None:
    rules = LoadoutRules(reselect_each_round=False)
    resolved = menu(mage("m1", "warden", "warding"))

    assert preserved_selection(resolved, ["fireball", None], rules) == ("fireball", None)


# ------------------------------------------------------------------- snapshot --


def snapshot(*mages: DeployedMage, selection: list[str | None]) -> LoadoutSnapshot:
    return snapshot_loadout(
        namespace="north",
        mages=mages,
        selection=selection,
        roster_access=ROSTER,
        definitions=CATALOG,
    )


def test_a_snapshot_carries_the_resolved_effects_the_sim_will_fire() -> None:
    frozen = snapshot(mage("m1", "adept", "evocation", "reckless"), selection=["fireball", None])

    spells = frozen.sim_spells()
    assert [spell.id for spell in spells] == ["north:fireball"]
    assert read_field(spells[0].effects[0], "damage.amount") == 30
    assert read_field(spells[0].effects[0], "radius") == 45


def test_the_two_sides_resolve_one_definition_to_two_catalog_entries() -> None:
    """Why the sim id is namespaced.

    Both seats equip Fireball; one fields two Evocation mages and the other one.
    A catalog keyed on the definition id would hold one of those two answers and
    silently give it to both.
    """
    north = snapshot_loadout(
        namespace="north",
        mages=[mage("m1", "adept", "evocation"), mage("m2", "adept", "evocation")],
        selection=["fireball"],
        definitions=CATALOG,
    )
    south = snapshot_loadout(
        namespace="south",
        mages=[mage("s1", "adept", "evocation")],
        selection=["fireball"],
        definitions=CATALOG,
    )

    ids = [spell.id for spell in north.sim_spells() + south.sim_spells()]
    assert ids == ["north:fireball", "south:fireball"]
    assert read_field(north.sim_spells()[0].effects[0], "damage.amount") == 40
    assert read_field(south.sim_spells()[0].effects[0], "damage.amount") == 30


def test_a_snapshot_refuses_an_illegal_selection() -> None:
    with pytest.raises(LoadoutError, match="needs its mage on the field"):
        snapshot(mage("m1", "warden", "warding"), selection=["fireball"])


def test_a_snapshot_of_empty_slots_is_a_legal_empty_loadout() -> None:
    frozen = snapshot(mage("m1", "adept", "evocation"), selection=[None, None])

    assert frozen.spells == ()
    assert frozen.sim_spells() == []


def test_one_spell_in_both_slots_becomes_one_catalog_entry() -> None:
    """Two buttons for one id would build a catalog with a duplicate key."""
    frozen = snapshot(mage("m1", "adept", "evocation"), selection=["spark", "spark"])

    assert [spell.id for spell in frozen.sim_spells()] == ["north:spark"]


def test_a_snapshot_records_the_tag_support_it_was_taken_at() -> None:
    frozen = snapshot(mage("m1", "adept", "evocation", "reckless"), selection=["fireball"])

    assert frozen.tag_support == (("evocation", 1), ("reckless", 1))


def test_turning_the_snapshot_policy_off_is_refused_rather_than_ignored() -> None:
    """A configuration field that silently did nothing would be worse than none.

    Resolving live is not something this layer can honour by itself — the
    battle's spell catalog is built once from the snapshot — so the flag says so
    where somebody would try it, instead of looking configurable and not being.
    """
    with pytest.raises(LoadoutError, match="not implemented"):
        snapshot_loadout(
            namespace="north",
            mages=[mage("m1", "adept", "evocation")],
            selection=["fireball"],
            roster_access=ROSTER,
            definitions=CATALOG,
            rules=LoadoutRules(snapshot_at_lock_in=False),
        )
