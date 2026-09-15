"""Determinism: identical inputs and seed produce byte-identical state and event
output — in this process, and in a fresh one.

The fresh-process half is not paranoia, and in Python it is the half that matters.
`PYTHONHASHSEED` is fixed once at interpreter startup, and pytest runs the whole
suite in one interpreter — so any bug that depends on hash order is perfectly
self-consistent within a test run and differs between deployments. Iterating a
`set` of strings is the classic way in. Only shelling out to a real child process
can catch it.
"""

import os
import subprocess
import sys

from app.sim.fixtures import placeholder_battle
from app.sim.map import TWO_LANE_MAP
from app.sim.run_battle import BattleResult, run_battle
from app.sim.serialize import digest_battle, serialize_battle

SEED = 20260911
FRESH_RUNS = 5


def run(seed: int = SEED) -> BattleResult:
    return run_battle(TWO_LANE_MAP, [], placeholder_battle(), seed)


def demo_output(seed: int) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "app.scripts.battle_demo", "--seed", str(seed)],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.rstrip("\n")


def test_hash_randomisation_is_not_pinned() -> None:
    """If someone "fixes" a flake by pinning PYTHONHASHSEED, the fresh-process
    checks below stop testing anything at all — every child would inherit one
    seed and agree trivially. Fail loudly rather than pass silently."""
    assert os.environ.get("PYTHONHASHSEED") in (None, "random")


def test_two_runs_in_one_process_produce_identical_event_output() -> None:
    assert [str(event) for event in run().events] == [str(event) for event in run().events]


def test_two_runs_in_one_process_produce_identical_state_tick_by_tick() -> None:
    assert [str(tick.state) for tick in run().ticks] == [str(tick.state) for tick in run().ticks]


def test_two_runs_in_one_process_produce_the_same_digest() -> None:
    assert digest_battle(run()) == digest_battle(run())


def test_the_battle_actually_depends_on_the_seed() -> None:
    assert serialize_battle(run(SEED)) != serialize_battle(run(SEED + 1))


def test_a_fresh_process_reproduces_the_in_process_run_byte_for_byte() -> None:
    assert demo_output(SEED) == serialize_battle(run(SEED))


def test_five_fresh_interpreters_all_agree() -> None:
    """Five separate interpreters, five different hash seeds. Agreement here is
    real evidence; agreement inside one process would be none."""
    outputs = {demo_output(SEED + 1) for _ in range(FRESH_RUNS)}

    assert len(outputs) == 1
