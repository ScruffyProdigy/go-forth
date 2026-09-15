"""Decisions reproduce across fresh interpreters, not merely within one.

The in-process half of this proves almost nothing on its own, for the reason
`CONVENTIONS.md` spells out: `PYTHONHASHSEED` is fixed once at startup and pytest
runs the whole suite in one interpreter, so anything that depends on hash order is
perfectly self-consistent inside a test run and differs between deployments. The
decision loop is full of exactly the shapes that go wrong that way — sets of trait
tags, mappings of weights, candidate lists assembled from several sources — so the
subprocess checks below are the ones carrying the weight.
"""

from __future__ import annotations

import os
import subprocess
import sys

from app.sim.ai.fixtures import placeholder_behavior
from app.sim.config import SimConfig
from app.sim.fixtures import placeholder_battle
from app.sim.map import TWO_LANE_MAP
from app.sim.run_battle import BattleResult, run_battle
from app.sim.serialize import digest_battle, serialize_battle

SEED = 20260914
FRESH_RUNS = 5
#: A short backstop. These spawn interpreters, and a full ninety-second battle
#: five times over costs more than it proves — a hash-order bug shows up in the
#: first seconds or not at all.
SECONDS = 20.0
SHORT = SimConfig(max_battle_seconds=SECONDS)

#: Printed by a child interpreter: every unit's composed weights and the intent
#: it finished on, every troop's standing assignments, and the provenance behind
#: each personality. The battle serialisation covers positions and damage; this
#: covers the decisions themselves, which are what the ticket asks be reproducible.
#:
#: The assignments and the influences matter here more than they look. Both are
#: built by walking collections and appending, and both reach the output — so
#: either one iterated in hash order would produce a battle that serialised
#: identically while its reasons came out shuffled, which is exactly the class of
#: drift that only shows up once two numbers are close enough to change a choice.
DECISIONS_SCRIPT = """
from app.sim.ai.fixtures import placeholder_behavior
from app.sim.fixtures import placeholder_battle
from app.sim.config import SimConfig
from app.sim.map import TWO_LANE_MAP
from app.sim.run_battle import run_battle

battle = placeholder_battle()
battle.behavior = placeholder_behavior()
result = run_battle(TWO_LANE_MAP, [], battle, {seed}, SimConfig(max_battle_seconds={seconds}))

for unit in sorted(result.final_state.units, key=lambda u: u.id):
    ai = unit.ai
    intent = ai.intent if ai else None
    weights = [f"{{f}}={{w:.4f}}" for f, w in (ai.behavior.weights.items() if ai else [])]
    traits = ",".join(ai.behavior.traits) if ai else ""
    def sources(p):
        return "|".join(f"{{s.mage_id}}={{s.strength}}/{{s.overridden}}" for s in p.sources)

    tags = ",".join(
        f"{{p.tag}}:{{p.strength}}:{{sources(p)}}"
        for p in (ai.behavior.personalities if ai else ())
    )
    influences = ",".join(
        f"{{i.tag}}@{{i.context}}:{{i.factor}}={{i.delta:.4f}}" for i in (intent.influences if intent else ())
    )
    print(f"id={{unit.id}}", f"traits={{traits}}", f"tags={{tags}}", *weights,
          f"kind={{intent.kind if intent else None}}",
          f"target={{intent.target_id if intent else None}}",
          f"why={{influences}}",
          f"score={{intent.score:.6f}}" if intent else "score=None")

for troop in sorted(result.final_state.troops, key=lambda t: t.id):
    duty = ",".join(
        f"{{a.unit_id}}>{{a.target_id}}@{{a.protecting_id}}#{{a.since_tick}}"
        for a in troop.coordination.assignments
    )
    print(f"troop={{troop.id}}", f"duty={{duty}}")
"""


def battle_with_behavior() -> BattleResult:
    battle = placeholder_battle()
    battle.behavior = placeholder_behavior()
    return run_battle(TWO_LANE_MAP, [], battle, SEED, SHORT)


def child(*argv: str) -> str:
    completed = subprocess.run([sys.executable, *argv], capture_output=True, text=True, check=True)
    return completed.stdout.rstrip("\n")


def demo_output(seed: int) -> str:
    return child(
        "-m", "app.scripts.battle_demo", "--behavior", "--seed", str(seed), "--seconds", str(SECONDS)
    )


def decisions(seed: int) -> str:
    return child("-c", DECISIONS_SCRIPT.format(seed=seed, seconds=SECONDS))


def test_hash_randomisation_is_not_pinned() -> None:
    """Pinning it would turn every check below green without testing anything."""
    assert os.environ.get("PYTHONHASHSEED") in (None, "random")


def test_two_runs_in_one_process_produce_the_same_digest() -> None:
    assert digest_battle(battle_with_behavior()) == digest_battle(battle_with_behavior())


def test_a_fresh_process_reproduces_the_in_process_battle_byte_for_byte() -> None:
    assert demo_output(SEED) == serialize_battle(battle_with_behavior())


def test_five_fresh_interpreters_agree_on_the_whole_battle() -> None:
    assert len({demo_output(SEED + 1) for _ in range(FRESH_RUNS)}) == 1


def test_five_fresh_interpreters_agree_on_the_decisions_themselves() -> None:
    """Composed weights, resolved traits and personalities, and the final intent.

    A battle can serialise identically while the weights behind it were composed
    in a different order — the difference would only surface once the numbers
    were close enough to change a choice. This compares the decisions directly.
    """
    assert len({decisions(SEED + 2) for _ in range(FRESH_RUNS)}) == 1


def test_the_decisions_are_not_empty() -> None:
    """Guards the check above: five identical blank strings would also agree."""
    lines = decisions(SEED + 2).splitlines()

    assert len(lines) > 3
    units = [line for line in lines if line.startswith("id=")]
    troops = [line for line in lines if line.startswith("troop=")]
    kinds = [field for line in units for field in line.split() if field.startswith("kind=")]

    assert units and troops
    assert len(kinds) == len(units)
    assert all(kind[len("kind=") :] in ("advance", "attack", "hold") for kind in kinds)


def test_behavior_data_changes_the_battle() -> None:
    """Otherwise every determinism check here would be testing slice A."""
    plain = run_battle(TWO_LANE_MAP, [], placeholder_battle(), SEED, SHORT)

    assert digest_battle(plain) != digest_battle(battle_with_behavior())


def test_the_sample_battle_actually_engages() -> None:
    """Every check above would still pass on a battle where nothing happened.

    Five interpreters agreeing on an empty battle is five interpreters agreeing.
    The fixture stations are hand-placed coordinates on one particular map, so a
    map reshape — the lane change is in flight — could put two armies somewhere
    they never meet, and every determinism test here would stay green while the
    thing they are meant to be checking quietly stopped happening.

    So: across several seeds, the armies must actually fight, and all three
    verbs must be exercised somewhere in the battle. Sampled rather than pinned
    to one seed, because a single-seed assertion is the same trap one layer down.
    """
    for seed in (SEED, SEED + 1, SEED + 2, 1, 7):
        battle = placeholder_battle()
        battle.behavior = placeholder_behavior()
        result = run_battle(TWO_LANE_MAP, [], battle, seed, SHORT)

        defeats = [event for event in result.events if event.type == "unitDefeated"]
        verbs = {
            unit.ai.intent.kind
            for tick in result.ticks
            for unit in tick.state.units
            if unit.ai is not None and unit.ai.intent is not None
        }

        assert defeats, f"seed {seed}: the two armies never engaged"
        assert verbs == {"advance", "attack", "hold"}, f"seed {seed}: only {sorted(verbs)} were ever chosen"
