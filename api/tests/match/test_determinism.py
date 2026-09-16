"""An assembled round is deterministic — in this process, and in a fresh one.

JQ-308 asks for "assembled fresh-process determinism" to be preserved, and the
match layer is where it is easiest to lose. The sim's own rule (see
`api/CONVENTIONS.md`) is that a `set` of strings iterates in a different order
in every interpreter, and this layer is full of the containers that tempt you
into one: which mages a plan fields, which spells resolved, whose seat is
locked, which sides still have a base. Any of those iterated as a set would give
a different round per deployment while passing every in-process test.

Hence the subprocess half. `PYTHONHASHSEED` is fixed once at interpreter startup
and pytest runs the whole suite in one interpreter, so running a round twice in
this process samples a single hash seed and proves nothing.

`--seconds` keeps each child to a short round; the property under test is
reproducibility, not length.
"""

from __future__ import annotations

import os
import subprocess
import sys

from app.match import fixtures
from app.match.plan import default_plan, resolve_snapshot
from app.scripts.match_demo import play
from app.sim.serialize import serialize_battle

SEED = 20260915
FRESH_RUNS = 5
SHORT = 8.0


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


def test_two_rounds_in_one_process_agree() -> None:
    first, second = play(SEED, SHORT), play(SEED, SHORT)
    assert serialize_battle(first.result()) == serialize_battle(second.result())
    assert first.ending == second.ending


def test_fresh_interpreters_agree() -> None:
    """The half that matters. See the module docstring."""
    assert len({demo_output() for _ in range(FRESH_RUNS)}) == 1


def test_the_round_actually_depends_on_the_seed() -> None:
    """A determinism check passes trivially if the thing under test ignores its
    inputs. This is the complement that says it does not."""
    assert demo_output("--seed", str(SEED)) != demo_output("--seed", str(SEED + 1))


def _stable_across_processes(script: str) -> bool:
    outputs = {
        subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True).stdout
        for _ in range(FRESH_RUNS)
    }
    return len(outputs) == 1


def test_the_default_plan_is_stable_across_processes() -> None:
    """It is what a seat that never locks in gets fielded, so a default that
    varied by interpreter would make an absent player's army differ per
    deployment — and the missed-plan path is the one nobody watches."""
    assert _stable_across_processes(
        "from app.match import fixtures;"
        "from app.match.plan import default_plan;"
        "print(default_plan(fixtures.map_config()))"
    )


def test_the_resolved_loadout_is_stable_across_processes() -> None:
    """`resolve_snapshot` walks fielded mages and spell tags to price a loadout.
    Mage order, tag order and the tag-support counts are all load-bearing, and
    all three are the kind of thing a set would scramble."""
    assert _stable_across_processes(
        "from app.match import fixtures;"
        "from app.match.plan import default_plan, resolve_snapshot;"
        "print(resolve_snapshot(default_plan(fixtures.map_config()), 'north'))"
    )


def test_a_live_cast_lands_where_a_prescheduled_one_would() -> None:
    """`BattleRunner.inject` inserts into an already-sorted queue rather than
    re-sorting it, so it has to land exactly where `schedule_injections` would
    have put it. If it did not, a cast taken live would resolve in a different
    order from the same cast handed over up front — and only a round with two
    spells on one tick would ever show it."""
    from app.sim.run_battle import create_runner
    from app.sim.spells import SpellInjection, injection_order
    from app.sim.types import SIDES, Vec2
    from app.sim.world import BattleSetup

    map_config = fixtures.map_config()
    plan = default_plan(map_config)
    snapshots = {side: resolve_snapshot(plan, side) for side in SIDES}

    from app.match.plan import to_army_setup

    setup = BattleSetup(
        unit_types=fixtures.unit_types(),
        armies=[to_army_setup(plan, side) for side in SIDES],
        abilities=fixtures.abilities(),
        spells=[spell for side in SIDES for spell in snapshots[side].sim_spells()],
    )
    runner = create_runner(map_config, [], setup, SEED)
    catalog = list(runner.spells)

    same_tick = [
        SpellInjection(tick=50, spell_id=catalog[0], location=Vec2(200.0, 300.0), side="south"),
        SpellInjection(tick=50, spell_id=catalog[0], location=Vec2(100.0, 200.0), side="north"),
        SpellInjection(tick=50, spell_id=catalog[-1], location=Vec2(120.0, 300.0), side="north"),
    ]
    for injection in same_tick:
        runner.inject(injection)

    assert runner.world.pending_spells == sorted(same_tick, key=injection_order)
