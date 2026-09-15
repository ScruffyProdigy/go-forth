"""The registry says what this package covers, and what it does not yet.

Four of the seven scenarios the ticket names need behaviors that are still being
written — JQ-329's positioning, screening and bounded pursuit, and JQ-330's troop
coordination. Registering them as pending rather than leaving them out is the
difference between "this package covers three scenarios" and "this package
covers three of seven, and here is which four are outstanding and who owns them".

These tests exist so that statement cannot go stale silently: a pending scenario
has to name a real ticket, a runnable one has to name a module that exists, and
nothing may claim both or neither.
"""

from __future__ import annotations

import importlib
import pathlib

from tests.sim.ai.scenarios import PENDING, RUNNABLE, SCENARIOS

HERE = pathlib.Path(__file__).resolve().parent

#: Every scenario the ticket's acceptance names, spelled as the ticket spells it.
REQUIRED = {
    "ranged spacing",
    "screening",
    "repeated bait",
    "regroup",
    "personality comparison with identical entourage",
    "combined traits",
    "invalid and dead targets",
}


def test_every_scenario_the_ticket_names_is_registered() -> None:
    assert {scenario.name for scenario in SCENARIOS} == REQUIRED


def test_a_scenario_is_either_runnable_or_blocked_never_both() -> None:
    for scenario in SCENARIOS:
        assert (scenario.blocked_on is None) != (scenario.module is None), scenario.name


def test_every_runnable_scenario_has_a_module_that_exists_and_imports() -> None:
    for scenario in RUNNABLE:
        module = importlib.import_module(f"tests.sim.ai.scenarios.{scenario.module}")
        assert module is not None


def test_every_runnable_scenario_module_is_a_file_in_this_package() -> None:
    for scenario in RUNNABLE:
        assert (HERE / f"{scenario.module}.py").is_file(), scenario.name


def test_every_pending_scenario_names_the_ticket_that_unblocks_it() -> None:
    for scenario in PENDING:
        assert scenario.blocked_on == "JQ-329", scenario.name


def test_every_scenario_says_what_it_asserts() -> None:
    """A registry entry with no stated invariant is a name, not a scenario."""
    for scenario in SCENARIOS:
        assert len(scenario.asserts.split()) >= 6, scenario.name


def test_the_split_is_four_runnable_and_three_pending() -> None:
    """Pinned so that landing a pending scenario is a deliberate edit here too."""
    assert len(RUNNABLE) == 4
    assert len(PENDING) == 3


def test_no_scenario_module_is_registered_twice() -> None:
    modules = [scenario.module for scenario in RUNNABLE]

    assert len(modules) == len(set(modules))
