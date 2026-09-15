"""Tracing changes nothing — proved the only way it can be proved, in child processes.

`tests/sim/test_determinism.py` explains why this has to shell out: `PYTHONHASHSEED`
is fixed once per interpreter, pytest runs the whole suite in one, and so a
determinism test that runs the sim twice in-process samples a single hash seed
and passes unconditionally. This file reuses that harness's approach rather than
inventing a second one — same idea, same child-process shape, aimed at the one
question this ticket adds: **does turning the inspector on change the battle?**

It must not. Not the events, not the state, not the rng stream. A developer tool
that perturbs the thing it is inspecting is worse than no tool, because every
surprising decision it shows you might be its own fault.
"""

from __future__ import annotations

import os
import subprocess
import sys

from app.sim.ai.fixtures import sample_library
from app.sim.ai.inspect.record import DecisionTrace
from app.sim.config import SimConfig
from app.sim.fixtures import placeholder_battle
from app.sim.map import TWO_LANE_MAP
from app.sim.run_battle import run_battle
from app.sim.serialize import serialize_battle

SEED = 20260915
FRESH_RUNS = 5
#: Short enough to run five child processes twice over without the suite
#: noticeably slowing; long enough that units actually meet and decide.
SECONDS = "6"


def emit(*flags: str) -> str:
    """One fresh interpreter's canonical battle serialization."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.scripts.decision_report",
            "--emit",
            "battle",
            "--seed",
            str(SEED),
            "--seconds",
            SECONDS,
            *flags,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.rstrip("\n")


def in_process(trace: DecisionTrace | None) -> str:
    setup = placeholder_battle()
    setup.behavior = sample_library()
    config = SimConfig(max_battle_seconds=float(SECONDS))
    return serialize_battle(run_battle(TWO_LANE_MAP, [], setup, SEED, config, trace=trace))


def test_hash_randomisation_is_not_pinned() -> None:
    """Same guard as the core harness: a pinned seed makes every check below a lie."""
    assert os.environ.get("PYTHONHASHSEED") in (None, "random")


def test_tracing_on_and_off_agree_in_one_process() -> None:
    assert in_process(DecisionTrace()) == in_process(None)


def test_tracing_on_and_off_agree_across_fresh_processes() -> None:
    assert emit("--trace") == emit("--no-trace")


def test_a_fresh_traced_process_reproduces_the_in_process_run() -> None:
    assert emit("--trace") == in_process(DecisionTrace())


def test_five_fresh_traced_interpreters_all_agree() -> None:
    """Five hash seeds, five traced runs, one answer."""
    assert len({emit("--trace") for _ in range(FRESH_RUNS)}) == 1


def test_the_traced_battle_still_depends_on_its_seed() -> None:
    """Guards the guard: if `--emit battle` printed a constant, everything passes."""
    other = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.scripts.decision_report",
            "--emit",
            "battle",
            "--seed",
            str(SEED + 1),
            "--seconds",
            SECONDS,
            "--trace",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip("\n")

    assert other != emit("--trace")


def test_the_report_itself_is_identical_across_fresh_processes() -> None:
    """The explanation has to reproduce too, or it cannot be diffed between runs."""
    reports = {
        subprocess.run(
            [
                sys.executable,
                "-m",
                "app.scripts.decision_report",
                "--emit",
                "report",
                "--json",
                "--seed",
                str(SEED),
                "--seconds",
                SECONDS,
                "--to",
                "20",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for _ in range(3)
    }

    assert len(reports) == 1
