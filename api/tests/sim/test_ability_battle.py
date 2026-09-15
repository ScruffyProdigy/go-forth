"""Slice C inside a real battle, and still deterministic with it.

`test_determinism.py` covers the slice-A roster. Everything JQ-288 adds is new
state — gauges, burns, hazards, a spell schedule — and new state is exactly
where a determinism bug hides, so the ability roster gets the same treatment,
fresh interpreter and all.
"""

from __future__ import annotations

import subprocess
import sys

from app.sim.fixtures import ABILITY_UNIT_TYPES, ability_battle
from app.sim.map import THREE_ZONE_MAP
from app.sim.run_battle import BattleResult, run_battle
from app.sim.serialize import digest_battle, serialize_battle
from app.sim.spells import SpellInjection
from app.sim.types import Vec2

SEED = 20260911
FRESH_RUNS = 3
INJECTION = SpellInjection(tick=200, spell_id="meteor", location=Vec2(187.5, 290), side="north")


def run(seed: int = SEED) -> BattleResult:
    return run_battle(THREE_ZONE_MAP, [], ability_battle([INJECTION]), seed)


def demo_output(seed: int) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "app.scripts.battle_demo", "--abilities", "--seed", str(seed)],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.rstrip("\n")


# --- determinism -----------------------------------------------------------


def test_two_runs_in_one_process_produce_identical_event_output() -> None:
    assert [str(event) for event in run().events] == [str(event) for event in run().events]


def test_two_runs_in_one_process_produce_identical_state_tick_by_tick() -> None:
    assert [str(tick.state) for tick in run().ticks] == [str(tick.state) for tick in run().ticks]


def test_a_fresh_interpreter_reproduces_the_battle_byte_for_byte() -> None:
    """The half that matters in Python: `PYTHONHASHSEED` is fixed once per
    interpreter, so a set iterated anywhere in the new code passes every
    in-process check and differs between deployments."""
    outputs = {demo_output(SEED) for _ in range(FRESH_RUNS)}

    assert len(outputs) == 1


def test_a_fresh_interpreter_agrees_with_this_one() -> None:
    assert demo_output(SEED) == serialize_battle(run(SEED))


def test_the_battle_still_depends_on_the_seed() -> None:
    assert digest_battle(run(SEED)) != digest_battle(run(SEED + 1))


# --- the slice actually runs -----------------------------------------------


def test_gauges_fill_and_abilities_fire_without_being_staged() -> None:
    casts = [event for event in run().events if event.type == "abilityCast"]

    assert casts
    assert {event.label for event in casts} <= {
        "cinder-nova",
        "pounce",
        "kindle",
        "ram-charge",
        "molten-seep",
    }


def test_every_card_on_the_demo_seed_gets_its_ability_off() -> None:
    """The demo roster is one card per primitive; if one never fires, the
    headless run stops demonstrating the vocabulary it was built to show.

    Scoped to the demo's own seed on purpose. Whether a particular card comes
    up full depends on how its battle went, so this is a claim about the run a
    reader will actually see printed, not about every battle — and it is the
    check that caught `ram-charge` being priced out of its own demo.

    Expect to re-tune the costs in `fixtures.py` when JQ-287 lands: it derives
    deployment from orders, so these armies start somewhere else and fight a
    different battle. This test going red at that merge means the demo stopped
    demonstrating a primitive, not that anything is broken.
    """
    fired = {event.label for event in run().events if event.type == "abilityCast"}

    assert fired == {unit_type.ability_id for unit_type in ABILITY_UNIT_TYPES}


def test_the_injected_spell_lands_exactly_once_on_its_tick() -> None:
    spells = [event for event in run().events if event.type == "spell"]

    assert [(event.tick, event.label) for event in spells] == [(200, "meteor")]


def test_an_emplacement_never_moves_over_a_whole_battle() -> None:
    result = run()
    start = {unit.id: unit.position for unit in result.ticks[0].state.units if unit.type_id == "slag-wall"}

    for tick in result.ticks:
        for unit in tick.state.units:
            if unit.type_id == "slag-wall":
                assert unit.position == start[unit.id]


def test_the_result_carries_the_energy_rules_the_battle_ran_under() -> None:
    result = run()

    fire = {source.meter: source.energy_per_unit for source in result.energy_rules["fire"]}
    artifice = {source.meter: source.energy_per_unit for source in result.energy_rules["artifice"]}

    assert fire == {"elapsedSeconds": 4.0, "damageDealt": 1.0}
    assert artifice == {"elapsedSeconds": 10.0}
