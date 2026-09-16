"""Writes the shared spell-resolver conformance fixtures.

    python -m app.scripts.export_conformance          # rewrite the file
    python -m app.scripts.export_conformance --check   # fail if it is stale

JQ-297 lets the client either consume resolved previews or run "an equivalent
local calculation verified by shared JSON conformance fixtures". The client runs
the calculation — a preview is a round trip, and the plan screen has to re-price
a spell on every tap — so this file is what makes "equivalent" a checkable
claim rather than a hope.

**Python is the authority.** The cases below are resolved by `sim/loadout.py`
and the answers are written down; `tests/sim/test_conformance.py` fails if the
checked-in file stops matching what the resolver produces, and the client's
`spellResolver.test.ts` fails if TypeScript stops reproducing it. Neither side
can drift quietly, and neither can be fixed by editing the fixture.

Note what is *not* pinned: the summary sentence, and the spell's prose. Those
are display, they differ by language, and pinning them would make a reworded
card a cross-language build failure. What is pinned is every number, every
eligibility answer, every reason string and every contributor — the things the
two implementations genuinely have to agree on.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from app.sim.effects import AreaDamage, BurningGround, DamageProfile, Knockback
from app.sim.loadout import (
    DeployedMage,
    LoadoutError,
    definition_to_json,
    mage_to_json,
    menu_to_json,
    resolve_menu,
    resolve_slots,
    snapshot_loadout,
    snapshot_to_json,
)
from app.sim.spellbook import (
    AlwaysAvailable,
    EffectScaling,
    IndependentAccess,
    SignatureOf,
    SpellDefinition,
    build_definition_catalog,
)

#: `api/app/scripts/export_conformance.py` -> the repository root.
ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "conformance" / "spell-resolver.json"

#: Bumped when the fixture's *shape* changes, so a client built against an older
#: one says so rather than silently reading a field that has moved.
FIXTURE_VERSION = 1


# The definitions the cases are resolved against. Deliberately not the demo's
# (`match/fixtures.py`): a conformance suite that moved whenever the demo's
# content was tuned would fail for reasons that have nothing to do with the two
# implementations agreeing. These exist to cover the rules, not to be played.
DEFINITIONS: tuple[SpellDefinition, ...] = (
    SpellDefinition(
        id="fireball",
        name="Fireball",
        cost=35.0,
        text="A burst of fire, and ground that keeps burning.",
        access=SignatureOf("adept"),
        effects=(
            AreaDamage(radius=40, damage=DamageProfile(amount=20, bonus_vs_base=1.5)),
            BurningGround(radius=40, damage_per_second=4, duration_seconds=3),
        ),
        scaling=(
            EffectScaling(0, "damage.amount", "evocation", per_mage=10, cap=30),
            EffectScaling(0, "radius", "reckless", per_mage=5, cap=10),
            EffectScaling(1, "damage_per_second", "evocation", per_mage=1.5, cap=4.5),
        ),
    ),
    SpellDefinition(
        id="spark",
        name="Spark",
        cost=5.0,
        text="A cheap jolt of flame.",
        access=AlwaysAvailable(),
        effects=(AreaDamage(radius=15, damage=DamageProfile(amount=6)),),
    ),
    SpellDefinition(
        id="veil",
        name="Smoke Veil",
        cost=20.0,
        text="A shove of hot smoke.",
        access=IndependentAccess(requires_tag="warding", minimum=1),
        effects=(Knockback(radius=30, distance=20),),
        scaling=(EffectScaling(0, "distance", "warding", per_mage=5, cap=15, threshold=1),),
    ),
    SpellDefinition(
        id="rite",
        name="Ashen Rite",
        cost=30.0,
        text="A debt called in.",
        access=IndependentAccess(requires_tag="necromancy", minimum=2),
        effects=(AreaDamage(radius=20, damage=DamageProfile(amount=15)),),
    ),
)

CATALOG = build_definition_catalog(DEFINITIONS)
ROSTER: tuple[str, ...] = ("veil", "rite")


def mage(instance: str, type_id: str, *tags: str, name: str | None = None) -> DeployedMage:
    return DeployedMage(instance_id=instance, type_id=type_id, name=name or instance, tags=tags)


ADEPT = ("adept", "evocation", "reckless")
WARDEN = ("warden", "warding", "patient")

#: `(name, why, mages, roster access, selection)`. One per acceptance criterion
#: JQ-297 asks to be tested, plus the two boundaries that have bitten this repo
#: before — a value landing exactly on a cap, and a threshold that unlocks
#: without raising anything.
CASES: tuple[tuple[str, str, list[DeployedMage], tuple[str, ...], list[str | None]], ...] = (
    (
        "zero-support",
        "Nothing fielded: every number is its base, and only the fallback is eligible.",
        [],
        ROSTER,
        [None, None],
    ),
    (
        "one-evocation-mage",
        "One tag at one step. Damage and the burning ground both move; radius does not.",
        [mage("m1", "adept", "evocation")],
        ROSTER,
        ["fireball", "spark"],
    ),
    (
        "multi-tag-split",
        "One Evocation mage and two Reckless ones move damage and radius by different amounts.",
        [
            mage("m1", "adept", "evocation"),
            mage("m2", "brute", "reckless"),
            mage("m3", "brute", "reckless"),
        ],
        ROSTER,
        ["fireball", None],
    ),
    (
        "dual-tagged-mage",
        "One mage carrying both tags raises each number once. Nothing multiplies.",
        [mage("m1", *ADEPT)],
        ROSTER,
        ["fireball", "spark"],
    ),
    (
        "duplicate-signature-grants",
        "Two of the same mage: one menu entry, two grantors, support counted twice.",
        [mage("m1", *ADEPT), mage("m2", *ADEPT)],
        ROSTER,
        ["fireball", None],
    ),
    (
        "independent-threshold-unlocks-without-raising",
        "One warding mage makes the Veil legal and adds nothing to it.",
        [mage("m1", *WARDEN)],
        ROSTER,
        ["veil", "spark"],
    ),
    (
        "independent-exactly-on-the-cap",
        "Four warding mages land on the cap exactly. Reported as capped.",
        [mage(f"m{i}", *WARDEN) for i in range(1, 5)],
        ROSTER,
        ["veil", None],
    ),
    (
        "independent-past-the-cap",
        "Nine warding mages get no more than four did.",
        [mage(f"m{i}", *WARDEN) for i in range(1, 10)],
        ROSTER,
        ["veil", None],
    ),
    (
        "independent-not-on-the-roster",
        "The tag is carried and the spell is still refused: access is explicit data.",
        [mage("m1", *WARDEN)],
        (),
        [None, None],
    ),
    (
        "independent-minimum-not-met",
        "One necromancy mage against a minimum of two, reported in the plural.",
        [mage("m1", "acolyte", "necromancy")],
        ROSTER,
        [None, None],
    ),
    (
        "a-tag-is-not-a-faction",
        "A mage tagged `artifice` unlocks nothing but the fallback.",
        [mage("m1", "smith", "artifice")],
        ROSTER,
        [None, None],
    ),
    (
        "troop-edit-strands-a-slot",
        "The Adept has been swapped out and the Fireball slot is now illegal.",
        [mage("m1", *WARDEN)],
        ROSTER,
        ["fireball", "veil"],
    ),
    (
        "one-spell-in-both-slots",
        "Two buttons for one spell collapse to one entry in the battle's catalog.",
        [mage("m1", *ADEPT)],
        ROSTER,
        ["spark", "spark"],
    ),
)


def _case_json(
    name: str,
    why: str,
    mages: list[DeployedMage],
    roster: tuple[str, ...],
    selection: list[str | None],
) -> dict[str, Any]:
    menu = resolve_menu(mages=mages, roster_access=roster, definitions=CATALOG)
    slots = resolve_slots(menu, selection)

    payload: dict[str, Any] = {
        "name": name,
        "why": why,
        "mages": [mage_to_json(entry) for entry in mages],
        "rosterAccess": list(roster),
        "selection": list(selection),
        "expected": {
            "menu": menu_to_json(menu),
            "slots": [
                {
                    "index": slot.index,
                    "spellId": slot.definition_id,
                    "eligible": slot.eligible,
                    "reason": slot.reason,
                    "stranded": slot.stranded,
                }
                for slot in slots
            ],
        },
    }

    # A stranded selection has no snapshot — lock-in refuses it. That is the
    # expectation, so it is written down as one rather than left absent.
    try:
        snapshot = snapshot_loadout(
            namespace="north",
            mages=mages,
            selection=selection,
            roster_access=roster,
            definitions=CATALOG,
        )
    except LoadoutError as err:
        payload["expected"]["snapshot"] = None
        payload["expected"]["snapshotError"] = str(err)
    else:
        payload["expected"]["snapshot"] = snapshot_to_json(snapshot)
        payload["expected"]["snapshotError"] = None

    return payload


def build() -> dict[str, Any]:
    return {
        "version": FIXTURE_VERSION,
        "rules": {"slots": 2, "reselectEachRound": True, "snapshotAtLockIn": True},
        "namespace": "north",
        "spells": [definition_to_json(definition) for definition in DEFINITIONS],
        "cases": [_case_json(*case) for case in CASES],
    }


def render() -> str:
    """The file's exact bytes. Two spaces and a trailing newline, like the JSON
    the client's tooling writes, so a regeneration is a content diff or nothing."""
    return json.dumps(build(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the fixture is out of date")
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        if not FIXTURE.exists() or FIXTURE.read_text() != rendered:
            print(f"{FIXTURE} is out of date; run `python -m app.scripts.export_conformance`")
            return 1
        return 0

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(rendered)
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
