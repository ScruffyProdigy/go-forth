"""Canonical text for a battle result.

The determinism requirement is byte-identical *state and events*, which needs one
agreed rendering: two runs are compared by comparing this text. It is also what
the headless demo prints, so a fresh process can be checked against an in-process
run without a second format existing.

Line-delimited JSON, with the survivors sorted by id — list order is an
implementation detail of how units died, and comparing it would fail runs that
are in fact identical.
"""

from __future__ import annotations

import json

from app.sim.run_battle import BattleResult

MASK32 = 0xFFFFFFFF


def _event_line(event) -> str:  # type: ignore[no-untyped-def]
    return json.dumps(
        {
            "event": event.type,
            "tick": event.tick,
            "position": {"x": event.position.x, "y": event.position.y},
            "actors": {
                "source": event.actors.source.unit_id if event.actors.source else None,
                "targets": [target.unit_id for target in event.actors.targets],
            },
            "swing": {
                "zoneScore": dict(event.swing.zone_score),
                "baseHp": dict(event.swing.base_hp),
                "unitsRemoved": [unit.unit_id for unit in event.swing.units_removed],
            },
        },
        sort_keys=False,
        separators=(",", ":"),
    )


def serialize_battle(result: BattleResult) -> str:
    header = json.dumps(
        {
            "seed": result.seed,
            "map": result.map.id,
            "tickRate": result.config.tick_rate,
            "outcome": result.outcome,
            "ticks": result.final_state.tick,
        },
        separators=(",", ":"),
    )

    survivors = [
        {
            "id": unit.id,
            "side": unit.side,
            "typeId": unit.type_id,
            "hp": unit.hp,
            "position": {"x": unit.position.x, "y": unit.position.y},
        }
        for unit in sorted(result.final_state.units, key=lambda unit: unit.id)
    ]

    footer = json.dumps(
        {
            "finalUnits": survivors,
            "bases": {
                "north": result.final_state.bases["north"].hp,
                "south": result.final_state.bases["south"].hp,
            },
            "zoneScore": dict(result.final_state.zone_score),
        },
        separators=(",", ":"),
    )

    return "\n".join([header, *(_event_line(event) for event in result.events), footer])


def digest_battle(result: BattleResult) -> str:
    """A short fingerprint of a battle, for comparing runs at a glance.

    FNV-1a, written out rather than taken from `hashlib`: the sim imports nothing
    outside itself, and `tests/test_purity.py` enforces that.
    """
    text = serialize_battle(result)
    value = 0x811C9DC5

    for char in text:
        value ^= ord(char) & 0xFF
        value = (value * 0x01000193) & MASK32

    return format(value, "08x")
