"""Does the Python sim reproduce the TypeScript sim, battle for battle?

The port was a transliteration, so "it runs and its own tests pass" is a weak
claim — a subtly different targeting rule or cooldown boundary would still be
internally consistent. `tests/golden_battles.json` holds two complete battles
captured from `api/src/sim/` before it was removed: every defeat with its tick,
position and actors, and every survivor's HP and final position.

Positions are compared to nine decimal places rather than byte-for-byte. That is
not a weakened claim, it is a different one: JQ-186's determinism criterion is
*the same implementation reproducing its own output*, which `test_determinism.py`
checks exactly. Two *languages* agreeing on JSON float formatting is a separate
thing and not something the sim promises — JavaScript writes `1e21` where Python
writes `1e+21`. Nine decimals is far beyond rendering precision, so any real
divergence in the simulation shows up here.
"""

import json
import pathlib

import pytest

from app.sim.fixtures import placeholder_battle
from app.sim.map import THREE_ZONE_MAP
from app.sim.run_battle import BattleResult, run_battle

GOLDEN = json.loads((pathlib.Path(__file__).parent / "golden_battles.json").read_text())
SEEDS = sorted(int(seed) for seed in GOLDEN)


def python_battle(seed: int) -> BattleResult:
    return run_battle(THREE_ZONE_MAP, [], placeholder_battle(), seed)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_battle_ends_the_same_way(seed: int) -> None:
    result = python_battle(seed)
    expected = GOLDEN[str(seed)]

    assert result.outcome == expected["outcome"]
    assert result.final_state.tick == expected["finalTick"]


@pytest.mark.parametrize("seed", SEEDS)
def test_every_defeat_happens_on_the_same_tick_to_the_same_unit(seed: int) -> None:
    result = python_battle(seed)
    expected = GOLDEN[str(seed)]["events"]

    actual = [
        {
            "type": event.type,
            "tick": event.tick,
            "source": event.actors.source.unit_id if event.actors.source else None,
            "removed": [unit.unit_id for unit in event.swing.units_removed],
        }
        for event in result.events
    ]
    assert actual == [
        {
            "type": e["type"],
            "tick": e["tick"],
            "source": e["source"],
            "removed": e["removed"],
        }
        for e in expected
    ]


@pytest.mark.parametrize("seed", SEEDS)
def test_every_defeat_happens_in_the_same_place(seed: int) -> None:
    result = python_battle(seed)
    expected = GOLDEN[str(seed)]["events"]

    assert len(result.events) == len(expected)
    for index, want in enumerate(expected):
        event = result.events[index]
        assert event.position.x == pytest.approx(want["x"], abs=1e-9)
        assert event.position.y == pytest.approx(want["y"], abs=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_same_units_survive_on_the_same_hp_in_the_same_place(seed: int) -> None:
    result = python_battle(seed)
    expected = GOLDEN[str(seed)]["survivors"]

    survivors = sorted(result.final_state.units, key=lambda unit: unit.id)
    assert [unit.id for unit in survivors] == [want["id"] for want in expected]

    for index, want in enumerate(expected):
        unit = survivors[index]
        assert unit.hp == pytest.approx(want["hp"])
        assert unit.position.x == pytest.approx(want["x"], abs=1e-9)
        assert unit.position.y == pytest.approx(want["y"], abs=1e-9)
