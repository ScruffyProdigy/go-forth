"""Canonical text for a battle result, and the placeholder armies."""

import json

from app.sim.fixtures import PLACEHOLDER_UNIT_TYPES, placeholder_battle
from app.sim.map import THREE_ZONE_MAP
from app.sim.run_battle import BattleResult, run_battle
from app.sim.serialize import digest_battle, serialize_battle


def run(seed: int = 7) -> BattleResult:
    return run_battle(THREE_ZONE_MAP, [], placeholder_battle(), seed)


def test_is_stable_for_the_same_battle() -> None:
    assert serialize_battle(run()) == serialize_battle(run())


def test_opens_with_a_header_naming_the_seed_and_outcome() -> None:
    header = json.loads(serialize_battle(run()).split("\n")[0])

    assert header["seed"] == 7
    assert header["map"] == THREE_ZONE_MAP.id
    assert header["outcome"]


def test_writes_one_line_per_event() -> None:
    result = run()
    lines = [line for line in serialize_battle(result).split("\n") if '"event"' in line]

    assert len(lines) == len(result.events)


def test_closes_with_the_surviving_units() -> None:
    result = run()
    last = json.loads(serialize_battle(result).split("\n")[-1])

    assert len(last["finalUnits"]) == len(result.final_state.units)


def test_lists_survivors_in_a_stable_order() -> None:
    last = json.loads(serialize_battle(run()).split("\n")[-1])
    ids = [unit["id"] for unit in last["finalUnits"]]

    assert ids == sorted(ids)


def test_digest_matches_for_two_runs_on_the_same_seed() -> None:
    assert digest_battle(run()) == digest_battle(run())


def test_digest_differs_for_a_different_seed() -> None:
    assert digest_battle(run(7)) != digest_battle(run(8))


def test_the_placeholder_armies_field_a_fire_mirror() -> None:
    battle = placeholder_battle()

    assert len(battle.armies) == 2
    assert all(army.troops for army in battle.armies)


def test_the_placeholder_armies_open_at_the_starting_mage_cap_of_three() -> None:
    for army in placeholder_battle().armies:
        total = sum(entry.count for troop in army.troops for entry in troop.mages)
        assert total == 3


def test_the_placeholder_cards_pass_catalog_validation() -> None:
    assert PLACEHOLDER_UNIT_TYPES
    run_battle(THREE_ZONE_MAP, [], placeholder_battle(), 1)
