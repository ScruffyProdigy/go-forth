"""The checked-in conformance fixture is what this resolver actually produces.

Half of a two-sided agreement. `client/src/plan/spellResolver.test.ts` runs the
same file against the TypeScript copy; this one fails if the file stops
describing Python, so the fixture cannot be edited to make either side green.

The fixture is generated, so most of this is one comparison. The rest guards
the ways a generated fixture goes quietly useless: cases that stopped covering
anything, and an export that runs but writes nothing.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from app.scripts.export_conformance import CASES, FIXTURE, render

FIXTURE_JSON = json.loads(FIXTURE.read_text())


def test_the_checked_in_fixture_matches_the_resolver() -> None:
    """Regenerate with `python -m app.scripts.export_conformance` when this fails.

    A failure here is not necessarily a bug: a deliberate rules change *should*
    move it. What it must never be is a surprise — the client is pinned to this
    file, so a rule that changed without the fixture changing would mean the two
    implementations had silently stopped agreeing.
    """
    assert FIXTURE.read_text() == render()


def test_the_fixture_is_where_both_suites_look_for_it() -> None:
    root = pathlib.Path(__file__).resolve().parents[3]

    assert root / "conformance" / "spell-resolver.json" == FIXTURE
    assert (root / "client" / "src" / "plan" / "spellResolver.test.ts").exists()


def test_every_case_is_named_once() -> None:
    names = [case["name"] for case in FIXTURE_JSON["cases"]]

    assert len(names) == len(set(names))
    assert len(names) == len(CASES)


def test_the_cases_cover_the_criteria_they_were_written_for() -> None:
    """A case list that quietly lost a case would still pass every comparison.

    Named rather than counted: `len(cases) > 8` goes green the moment somebody
    adds a case, whatever was deleted.
    """
    names = {case["name"] for case in FIXTURE_JSON["cases"]}

    assert {
        "zero-support",
        "multi-tag-split",
        "dual-tagged-mage",
        "duplicate-signature-grants",
        "independent-threshold-unlocks-without-raising",
        "independent-exactly-on-the-cap",
        "independent-past-the-cap",
        "independent-not-on-the-roster",
        "a-tag-is-not-a-faction",
        "troop-edit-strands-a-slot",
    } <= names


def test_the_cases_actually_disagree_with_each_other() -> None:
    """The failure mode of a generated fixture: every case resolving the same.

    Thirteen cases that all produced an identical menu would compare clean
    against any implementation that got one of them right, which is the shape of
    a suite that proves nothing.
    """
    menus = {json.dumps(case["expected"]["menu"], sort_keys=True) for case in FIXTURE_JSON["cases"]}

    assert len(menus) > 8


def test_at_least_one_case_expects_a_refused_lock_in() -> None:
    refused = [case for case in FIXTURE_JSON["cases"] if case["expected"]["snapshot"] is None]

    assert any(case["expected"]["snapshotError"] for case in refused)


def test_the_two_boundary_cases_bracket_the_cap() -> None:
    """Exactly-on and past-the-cap must produce the same number, and say so.

    Written out here rather than left to the blanket comparison because it is
    the assertion that would survive somebody regenerating the fixture against a
    broken cap: the two cases agreeing is a property of the *rule*, not of
    whatever the resolver last printed.
    """
    cases = {case["name"]: case for case in FIXTURE_JSON["cases"]}
    exact = _veil_distance(cases["independent-exactly-on-the-cap"])
    past = _veil_distance(cases["independent-past-the-cap"])

    assert exact == past
    assert _veil_scaled(cases["independent-exactly-on-the-cap"])["capped"] is True
    assert _veil_scaled(cases["independent-threshold-unlocks-without-raising"])["capped"] is False


def _veil(case: dict[str, Any]) -> dict[str, Any]:
    entries = case["expected"]["menu"]["entries"]
    found: dict[str, Any] = next(entry["spell"] for entry in entries if entry["spell"]["spellId"] == "veil")
    return found


def _veil_distance(case: dict[str, Any]) -> float:
    return float(_veil(case)["effects"][0]["distance"])


def _veil_scaled(case: dict[str, Any]) -> dict[str, Any]:
    scaled: dict[str, Any] = _veil(case)["scaled"][0]
    return scaled
