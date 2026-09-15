"""An assembled match is deterministic — in this process, and in a fresh one.

JQ-308 asks for "assembled fresh-process determinism" to be preserved, and the
match layer is where it is easiest to lose. The sim's own rule (see
`api/CONVENTIONS.md`) is that a `set` of strings iterates in a different order in
every interpreter, and this layer is full of the containers that tempt you into
one: which packages were chosen, which spells are eligible, whose plan is
locked, which sides still have a base. Any of those iterated as a set would give
a different battle per deployment while passing every in-process test.

Hence the subprocess half. `PYTHONHASHSEED` is fixed once at interpreter startup
and pytest runs the whole suite in one interpreter, so running a match twice in
this process samples a single hash seed and proves nothing.

`--seconds` keeps each child to a short battle; the property under test is
reproducibility, not length.
"""

from __future__ import annotations

import os
import subprocess
import sys

from app.match import OPENING_CATALOG, SINGLE_ROUND_TEST_PROFILE, new_match
from app.scripts.match_demo import play
from app.sim import TWO_LANE_MAP, serialize_battle

SEED = 20260915
FRESH_RUNS = 5
SHORT = 12.0


def demo_output(*args: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "app.scripts.match_demo", "--seconds", str(SHORT), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.rstrip("\n")


def test_hash_randomisation_is_not_pinned() -> None:
    """If someone "fixes" a flake by pinning PYTHONHASHSEED, every check below
    stops testing anything at all. Fail loudly rather than pass silently."""
    assert os.environ.get("PYTHONHASHSEED") in (None, "random")


def test_two_matches_in_one_process_agree() -> None:
    first, first_outcome = play(SEED, None, SHORT)
    second, second_outcome = play(SEED, None, SHORT)
    assert first.runner is not None and second.runner is not None

    assert serialize_battle(first.runner.result()) == serialize_battle(second.runner.result())
    assert first_outcome == second_outcome


def test_fresh_interpreters_agree() -> None:
    """The half that matters. See the module docstring."""
    assert len({demo_output() for _ in range(FRESH_RUNS)}) == 1


def test_fresh_interpreters_agree_on_the_missed_plan_path() -> None:
    """Run separately because it exercises the auto-lock, which walks `SIDES`
    to decide who to default — an ordering a set would scramble."""
    assert len({demo_output("--miss-plan", "south") for _ in range(FRESH_RUNS)}) == 1


def test_the_match_actually_depends_on_the_seed() -> None:
    """A determinism check passes trivially if the thing under test ignores its
    inputs. This is the complement that says it does not."""
    assert demo_output("--seed", str(SEED)) != demo_output("--seed", str(SEED + 1))


def test_the_eligible_spell_menu_is_stable_across_processes() -> None:
    """The menu is derived from the package list rather than from a set, so its
    order is a property of the catalog rather than of this interpreter."""
    script = (
        "from app.match import OPENING_CATALOG;"
        "print(OPENING_CATALOG.eligible_spells(['skirmish','hound-pair','ram-guard']))"
    )
    outputs = {
        subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True).stdout
        for _ in range(FRESH_RUNS)
    }
    assert len(outputs) == 1


def test_the_suggested_default_is_stable_across_processes() -> None:
    """It is what a missed plan locks in, so a default that varied by
    interpreter would make an absent player's army differ per deployment."""
    script = (
        "from app.match import OPENING_CATALOG, SINGLE_ROUND_TEST_PROFILE, suggested_plan;"
        "from app.sim import TWO_LANE_MAP;"
        "print(suggested_plan('north', OPENING_CATALOG, TWO_LANE_MAP, SINGLE_ROUND_TEST_PROFILE))"
    )
    outputs = {
        subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True).stdout
        for _ in range(FRESH_RUNS)
    }
    assert len(outputs) == 1


def test_a_live_cast_and_a_prescheduled_one_resolve_identically() -> None:
    """`BattleRunner.inject` inserts into an already-sorted list rather than
    re-sorting it, so it has to land where `schedule_injections` would have put
    it. If it did not, a cast made live would resolve in a different order from
    the same cast handed over up front — and only a battle with two spells on
    one tick would ever show it."""
    from app.sim import SpellInjection, Vec2, injection_order

    match = new_match(
        profile=SINGLE_ROUND_TEST_PROFILE,
        catalog=OPENING_CATALOG,
        map_config=TWO_LANE_MAP,
        seed=SEED,
    )
    for side in ("north", "south"):
        match.submit_plan(side, match.suggested(side))
    assert match.runner is not None

    same_tick = [
        SpellInjection(tick=50, spell_id="meteor", location=Vec2(200.0, 300.0), side="south"),
        SpellInjection(tick=50, spell_id="ember-surge", location=Vec2(100.0, 200.0), side="north"),
        SpellInjection(tick=50, spell_id="meteor", location=Vec2(120.0, 300.0), side="north"),
    ]
    for injection in same_tick:
        match.runner.inject(injection)

    assert match.runner.world.pending_spells == sorted(same_tick, key=injection_order)
