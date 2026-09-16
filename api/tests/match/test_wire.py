"""The wire contract, and the one rule it exists to hold.

JQ-309: *"Never accidentally expose `serialize_battle` as the wire format."*
The first test here is that rule, asserted rather than trusted — the failure
mode is not that someone decides to use it, it is that it is right there,
produces plausible JSON, and saves an afternoon.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.match import fixtures, wire
from app.match.plan import default_plan, resolve_loadout
from app.match.round import AuthoritativeRound
from app.match.wire import CommandError, parse_cast_command
from app.sim.config import SimConfig
from app.sim.types import SIDES, Vec2

WIRE_SOURCE = Path(__file__).resolve().parents[2] / "app" / "match" / "wire.py"


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_the_wire_never_imports_the_determinism_serializer() -> None:
    """`sim/serialize.py` is a determinism harness, not a wire format.

    It is total (it carries the opponent's everything), frozen for a different
    reason (changing it invalidates saved comparisons), and describes a finished
    battle rather than a tick. Three reasons, one import away from being ignored.
    """
    imported = _imported_names(WIRE_SOURCE)
    assert "app.sim.serialize" not in imported
    assert not any("serialize" in name for name in imported)


def test_no_module_outside_the_sim_imports_serialize_battle() -> None:
    """The rule holds for the whole server, not just for `wire.py`.

    Checked on the import graph rather than on the text, so this file and
    `wire.py` may go on *explaining* the rule without tripping it.

    The headless demos are the legitimate callers outside the sim: printing a
    battle's canonical text is precisely what they are for, and the determinism
    checks compare that text across fresh interpreters. What the rule is
    actually about is the *server* — `wire.py`, `session.py`, `round.py`,
    `routes.py`, `ws.py` — none of which may put the sim's own serialisation in
    front of a client. Anything added to this list should be a CLI that prints
    to stdout and nothing else.
    """
    api_root = WIRE_SOURCE.parents[1]
    allowed = {
        Path("scripts/battle_demo.py"),
        Path("scripts/match_demo.py"),
        # JQ-331's decision inspector. `--emit battle` prints the canonical text
        # and nothing else, which is what its determinism checks compare across
        # fresh interpreters — the same reason the two demos are here.
        Path("scripts/decision_report.py"),
    }

    offenders = []
    for path in sorted(api_root.rglob("*.py")):
        relative = path.relative_to(api_root)
        if relative.parts[0] == "sim" or relative in allowed:
            continue
        imported = _imported_names(path)
        if "app.sim.serialize" in imported or "app.sim.serialize_battle" in imported:
            offenders.append(str(relative))
        # `from app.sim import serialize_battle` — the package re-exports it, so
        # the tempting one-liner does not name the serialize module at all.
        if "app.sim.serialize_battle" in imported or "app.sim.digest_battle" in imported:
            offenders.append(str(relative))
    assert offenders == []


# ------------------------------------------------------------- the snapshot --


@pytest.fixture
def live_round() -> AuthoritativeRound:
    plan = default_plan(fixtures.map_config())
    loadout = resolve_loadout(plan)
    return AuthoritativeRound(
        round_number=1,
        map_config=fixtures.map_config(),
        plans={side: plan for side in SIDES},
        loadouts={side: loadout for side in SIDES},
        base_hp={side: 1000.0 for side in SIDES},
        seed=11,
        sim_config=SimConfig(max_battle_seconds=4),
    )


def test_a_battle_snapshot_is_json_serialisable(live_round: AuthoritativeRound) -> None:
    snapshot = wire.battle_snapshot(
        world=live_round.world,
        map_config=live_round.map_config,
        you="north",
        energy=live_round.energy_for("north"),
        loadout=live_round.loadout_for("north"),
        casts=live_round.casts(),
    )
    # Every value crosses a socket as JSON. A stray dataclass or Vec2 in here
    # fails at send time, mid-battle, on one client.
    json.dumps(snapshot)


def test_a_snapshot_carries_only_the_asking_seats_energy(live_round: AuthoritativeRound) -> None:
    for _ in range(10):
        live_round.step()

    north = wire.battle_snapshot(
        world=live_round.world,
        map_config=live_round.map_config,
        you="north",
        energy=live_round.energy_for("north"),
        loadout=live_round.loadout_for("north"),
        casts=live_round.casts(),
    )
    # Hidden information: knowing the opponent's energy tells you which spell is
    # coming. It is absent, not present-and-ignored.
    assert "energy" in north
    assert isinstance(north["energy"], float)
    assert not any("energy" in str(key).lower() and key != "energy" for key in north)


def test_units_are_sorted_so_two_clients_agree_on_draw_order(live_round: AuthoritativeRound) -> None:
    for _ in range(5):
        live_round.step()
    units = wire.battle_units(live_round.world)
    assert [unit["id"] for unit in units] == sorted(unit["id"] for unit in units)


def test_the_deployment_preview_carries_only_your_side(live_round: AuthoritativeRound) -> None:
    snapshot = wire.battle_snapshot(
        world=live_round.world,
        map_config=live_round.map_config,
        you="north",
        energy=0.0,
        loadout=[],
        casts=[],
        only_your_units=True,
    )
    sides = {unit["side"] for unit in snapshot["units"]}
    # The opponent's plan is hidden until the battle starts. Not merely undrawn:
    # not in the payload to be found by anyone reading the network tab.
    assert sides == {"north"}


def test_zone_ids_come_from_the_map_not_from_the_stale_client_fixture(
    live_round: AuthoritativeRound,
) -> None:
    zones = wire.zone_states(live_round.world, live_round.map_config)
    # JQ-376 replaced the three-zone map with two lanes. The client's `ZoneId`
    # union still says A/B/C; the server's answer is the map's, and renaming the
    # sim's lanes to keep a stale fixture happy would be the tail wagging the dog.
    assert [zone["id"] for zone in zones] == ["W", "E"]


def test_base_hp_carries_both_sides(live_round: AuthoritativeRound) -> None:
    bases = wire.base_hp(live_round.world, live_round.map_config)
    assert set(bases) == {"north", "south"}
    assert bases["north"]["maxHp"] == 1000
    # A player who cannot see the opponent's base cannot tell a push from a rout,
    # and base HP is the match's central fact under the 2026-09-13 rule.
    assert bases["south"]["hp"] == 1000


# ----------------------------------------------------------------- endings --


def test_base_destruction_is_its_own_ending_kind() -> None:
    assert wire.base_destroyed("north")["kind"] == "baseDestroyed"
    assert wire.round_complete("north", "timeUp")["kind"] == "roundComplete"
    # Two kinds, never one kind with a `reason`: presenting base destruction as
    # one round lost would misreport the game's central rule, and a client given
    # a reason string would have to know which strings were terminal.
    assert wire.base_destroyed("north") != wire.round_complete("north", "timeUp")


def test_a_test_profile_ending_claims_no_series() -> None:
    ending = wire.match_ending_test_complete("north")
    assert ending["kind"] == "testComplete"
    assert ending["roundWinner"] == "north"
    # Crucially *not* `roundsWon`, which downstream would read as a match won.
    assert "winner" not in ending


def test_a_snapshot_says_whether_the_run_is_a_test() -> None:
    snapshot = wire.match_snapshot(
        run_id="r1",
        match_id="m1",
        you="north",
        round_number=1,
        rounds_won={"north": 0, "south": 0},
        bases={"north": {"hp": 1.0, "maxHp": 1.0}, "south": {"hp": 1.0, "maxHp": 1.0}},
        phase=wire.planning_phase(plan={}, locked=False, deployment=None),
        test_profile=True,
    )
    # The label on screen is the server's claim about the run, not a build-time
    # guess by the client.
    assert snapshot["testProfile"] is True
    assert snapshot["wireVersion"] == wire.WIRE_VERSION


# ---------------------------------------------------------------- commands --


def test_a_cast_command_parses() -> None:
    command = parse_cast_command(
        {"commandId": "c1", "spellId": "meteor", "at": {"x": 100, "y": 200}, "tick": 42}
    )
    assert command.command_id == "c1"
    assert command.at == Vec2(100.0, 200.0)


def test_a_cast_command_may_not_name_its_own_side() -> None:
    command = parse_cast_command(
        {"commandId": "c1", "spellId": "meteor", "at": {"x": 1, "y": 2}, "side": "south"}
    )
    # `side` is filled in on the server from the seat. A client trusted to name
    # its own side is a client that can cast as its opponent, so the field is
    # not read at all rather than read and validated.
    assert not hasattr(command, "side")


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"commandId": "c1", "spellId": "meteor"},
        {"commandId": "", "spellId": "meteor", "at": {"x": 1, "y": 1}},
        {"commandId": "c1", "spellId": "meteor", "at": {"x": "left", "y": 1}},
        {"commandId": "c1", "spellId": "meteor", "at": {"x": float("nan"), "y": 1}},
        {"commandId": "c1", "spellId": "meteor", "at": {"x": float("inf"), "y": 1}},
    ],
)
def test_a_malformed_cast_is_refused(raw: object) -> None:
    # NaN and the infinities parse out of JSON in Python and would reach the sim
    # as a position no comparison is true about.
    with pytest.raises(CommandError):
        parse_cast_command(raw)


def test_a_cast_outcome_names_exactly_one_command() -> None:
    accepted = wire.cast_outcome_message("accepted", "c1")
    rejected = wire.cast_outcome_message("rejected", "c2", "notEnoughEnergy")
    assert accepted == {"type": "castOutcome", "outcome": "accepted", "commandId": "c1"}
    assert rejected["reason"] == "notEnoughEnergy"
    # No `pending` from the server: pending is what the client calls a cast it
    # has sent and not yet heard about.
    assert accepted["outcome"] != "pending"
