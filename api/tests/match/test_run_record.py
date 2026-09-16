"""The run record, and the replay that proves it is complete.

JQ-310: *store run/match ID, rules/content version, resolved initial state,
seeds, plans, accepted spells with tick/order, outcome. Reproduce the
interactive run from this record.*

The reproduction is the test that matters, and it is the only one that can
actually fail for the right reason. Asserting that a field is present proves the
field is present; replaying the whole run and getting the same battle proves the
record carried **everything the battle was a function of**. The first kind of
test passes happily while something quietly stops being recorded.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.lobby.manifest import OPENING_ROUND, STARTER
from app.match import fixtures
from app.match.plan import parse_plan, validate_plan
from app.match.run_record import RECORD_VERSION, ReplayError, RunRecord, replay_run
from app.match.session import MatchSession
from app.match.versions import CONTENT_VERSION, RULES_VERSION
from app.match.wire import CastCommand
from app.service import GameService
from app.sim.config import SimConfig
from app.sim.serialize import digest_battle
from app.sim.types import SIDES, Vec2
from tests.conftest import RecordingLobby, fake_token, provision_body

MATCH = "lobby-match-1"
MAP = fixtures.map_config()
SHORT = SimConfig(max_battle_seconds=3)
#: Short enough that a multi-round Starter match plays out in a test.
TINY = SimConfig(max_battle_seconds=1)
#: Enough for several casts without waiting out the gauge. The record stores
#: what a round opened on, so a test that changes it is testing the same code
#: path rather than a special one.
RICH = 400.0


def make_session(
    mode: Any = OPENING_ROUND,
    sim_config: SimConfig = SHORT,
    *,
    starting_energy: float = RICH,
) -> MatchSession:
    session = MatchSession(
        run_id="run-1",
        external_match_id="m-1",
        mode=mode,
        seats={"1": "north", "2": "south"},
        map_config=MAP,
        sim_config=sim_config,
        seed=7,
        starting_energy=starting_energy,
    )
    for index, seat in enumerate(session.seats.values()):
        seat.player_id = f"player-{index + 1}"
        seat.lobby_user_id = f"user-{index + 1}"
    return session


def plan() -> dict[str, Any]:
    return fixtures.opening_plan_json(1, MAP)


def lean_plan() -> dict[str, Any]:
    """One mage, one hound, one spell.

    Legal, and a quarter of the units the suggested default fields — which is
    what keeps a file full of whole replayed matches from taking minutes. What
    is under test here is the record, not the battle, and a smaller battle is
    the same record with fewer rows in it.
    """
    return {
        "troops": [
            {
                "mageId": "ember-adept",
                "summonIds": ["cinder-hound"],
                "order": {"kind": "pushEnemyBase"},
            }
        ],
        "spellSlots": ["meteor", None],
    }


def played_run(*, casts: int = 1) -> MatchSession:
    """A whole opening-round run, with real casts in it, driven to its end."""
    session = make_session()
    session.lock_in("north", lean_plan())
    session.lock_in("south", lean_plan())

    cast_at = [Vec2(120, 300), Vec2(250, 260)]
    placed = 0
    while not session.over:
        session.tick()
        if placed < casts and not session.over:
            outcome = session.cast(
                "north",
                CastCommand(f"c{placed}", "meteor", cast_at[placed % len(cast_at)], session.round.world.tick),
            )
            assert outcome["outcome"] == "accepted", outcome
            placed += 1
    assert placed == casts, "the run under test has to contain the casts it claims to"
    return session


# ------------------------------------------------------------- what is stored --


def test_a_finished_run_records_who_it_was_and_what_it_was_played_under() -> None:
    session = played_run()
    record = session.run_record

    assert record.run_id == "run-1"
    assert record.match_id == "m-1"
    assert record.game_mode == OPENING_ROUND.key
    assert record.test_profile is True
    assert record.map_id == MAP.id
    assert (record.record_version, record.rules_version, record.content_version) == (
        RECORD_VERSION,
        RULES_VERSION,
        CONTENT_VERSION,
    )
    assert record.tick_rate == SHORT.tick_rate
    assert record.max_battle_seconds == SHORT.max_battle_seconds


def test_a_finished_run_records_the_outcome_base_hp_and_terminal_reason() -> None:
    """Ryan, 2026-09-13: a record says how much base was left and why it stopped."""
    session = played_run()
    record = session.run_record

    assert record.ending is not None
    assert record.terminal_reason
    assert record.rounds_won == dict(session.rounds_won)
    assert set(record.base_hp) == set(SIDES)
    assert record.base_hp == {side: session.round.world.bases[side].hp for side in SIDES}


def test_a_round_records_its_seed_its_plans_and_the_hp_it_opened_on() -> None:
    session = played_run()
    entry = session.run_record.rounds[0]

    assert entry.number == 1
    # Derived from the run and the round, never from a clock — that is what
    # makes a replay possible at all.
    assert entry.seed == session.seed + 1
    assert entry.starting_energy == RICH
    assert entry.base_hp_at_start == {side: MAP.bases[side].max_hp for side in SIDES}
    assert entry.base_hp_at_end is not None
    assert entry.ending is not None
    assert set(entry.plans) == set(SIDES)
    assert [spell["spellId"] for spell in entry.loadouts["north"]] == ["meteor"]


def test_a_recorded_plan_is_one_the_parser_reads_back() -> None:
    """The round trip is the requirement, not the field names.

    A record whose plan the parser would refuse is a record that cannot be
    replayed — and it would not be discovered until someone tried, weeks later,
    on the one run they actually needed.
    """
    entry = played_run().run_record.rounds[0]
    for side in SIDES:
        reparsed = parse_plan(entry.plans[side])
        validate_plan(reparsed, MAP)


def test_accepted_casts_are_recorded_with_the_tick_and_order_the_server_gave_them() -> None:
    session = played_run(casts=2)
    casts = session.run_record.rounds[0].casts

    assert len(casts) == 2
    assert [entry.order for entry in casts] == [1, 2]
    assert all(entry.side == "north" for entry in casts)
    assert all(entry.spell_id == "meteor" for entry in casts)
    # Strictly increasing, so (tick, order) is a total order over the round.
    assert casts[0].tick <= casts[1].tick


def test_refused_casts_are_not_recorded() -> None:
    """A rejection changed nothing about the battle, so it cannot affect a replay.

    It belongs in the diagnostics, where it can be counted against reconnects.
    Here it would make the record grow with a client's retry loop and imply,
    falsely, that replaying it mattered.
    """
    session = make_session()
    session.lock_in("north", lean_plan())
    session.lock_in("south", lean_plan())
    session.tick()
    assert session.cast("north", CastCommand("bad", "meteor", Vec2(-5, -5), 0))["outcome"] == "rejected"

    assert session.run_record.rounds[0].casts == []


def test_a_record_carries_no_credentials() -> None:
    """A run record is read by someone investigating a match, not playing in one."""
    session = played_run()
    payload = repr(session.run_record.to_json())

    for seat in session.seats.values():
        assert seat.player_id is not None
        assert seat.player_id not in payload, "player_id is the gameplay credential"
    for forbidden in ("playerId", "serviceToken", "token", "returnUrl", "graphqlUrl"):
        assert forbidden not in payload


# --------------------------------------------------------------- the round trip --


def test_a_record_survives_json() -> None:
    original = played_run(casts=2).run_record
    assert RunRecord.from_json(original.to_json()).to_json() == original.to_json()


# ------------------------------------------------------------------ the replay --


def test_replaying_a_record_reproduces_the_run() -> None:
    """The acceptance criterion itself, and the only test here that proves it.

    Compared on `digest_battle` — a fingerprint of the *whole* battle, every
    tick and every event — and not on the outcome. A mirror match on a short
    round ends `timeUp` with no winner under almost any seed, so two runs
    agreeing on their ending says nothing about whether they were the same
    battle. That is not a hypothetical: the first version of this file compared
    endings, and the deliberate-tamper test below passed a seed change straight
    through.

    `digest_battle` is the sim's own determinism harness and app code outside
    `sim/` may not reach for it (`test_wire.py` enforces that on the import
    graph). A test is not app code, and this is exactly what the harness is for.
    """
    session = played_run(casts=2)
    record = session.run_record

    result = replay_run(record)

    assert result.endings_json() == [entry.ending for entry in record.rounds]
    assert result.base_hp == record.base_hp
    assert [entry.casts_applied for entry in result.rounds] == [len(e.casts) for e in record.rounds]
    assert digest_battle(result.rounds[-1].result) == digest_battle(session.round.result())


def test_a_replay_reproduces_a_run_with_no_casts_in_it_too() -> None:
    session = make_session()
    session.lock_in("north", lean_plan())
    session.lock_in("south", lean_plan())
    while not session.over:
        session.tick()

    result = replay_run(session.run_record)
    assert result.endings_json() == [entry.ending for entry in session.run_record.rounds]


def test_a_replay_runs_from_the_stored_json_and_not_from_the_live_object() -> None:
    """What an investigation actually has is a row, not a session."""
    record = played_run(casts=1).run_record
    from_storage = RunRecord.from_json(record.to_json())

    result = replay_run(from_storage)
    assert result.base_hp == record.base_hp


def test_a_replay_refuses_a_record_from_another_rules_version() -> None:
    """A silent divergence is the failure mode worth spending an exception on.

    The value of a replay is that it is *the same run*. One that is merely
    similar would be used to draw conclusions about a match that never happened.
    """
    raw = played_run().run_record.to_json()
    raw["rulesVersion"] = RULES_VERSION + 1

    with pytest.raises(ReplayError, match="rules"):
        replay_run(RunRecord.from_json(raw))


def test_a_replay_refuses_a_record_from_another_content_version() -> None:
    raw = played_run().run_record.to_json()
    raw["contentVersion"] = CONTENT_VERSION + 1

    with pytest.raises(ReplayError, match="content"):
        replay_run(RunRecord.from_json(raw))


def test_a_replay_refuses_a_record_played_on_another_map() -> None:
    raw = played_run().run_record.to_json()
    raw["mapId"] = "three-zone"

    with pytest.raises(ReplayError, match="map"):
        replay_run(RunRecord.from_json(raw))


@pytest.mark.parametrize(
    ("field", "change"),
    [
        ("seed", lambda value: int(value) + 1_000),
        ("startingEnergy", lambda value: float(value) + 100.0),
        ("baseHpAtStart", lambda value: {side: float(hp) - 100.0 for side, hp in dict(value).items()}),
    ],
)
def test_a_replay_notices_a_recorded_input_that_does_not_belong_to_the_run(field: str, change: Any) -> None:
    """The falsification: change one recorded input and the replay diverges.

    A reproduction test that cannot fail proves nothing, and the way to find out
    is to break the record on purpose — one input at a time, each of which
    should change the battle and nothing else. Every case asserts the tamper
    *landed* before trusting the result, because "I broke it and the test
    passed" and "I believe I broke it and the test passed" read identically in a
    terminal (`CONVENTIONS.md`).

    This test earned its keep immediately: against an earlier version that
    compared endings rather than battles, the seed case passed — a short mirror
    round ends `timeUp` with no winner whatever the seed, so the comparison had
    a blind spot exactly where it mattered.
    """
    session = played_run(casts=1)
    faithful = digest_battle(replay_run(session.run_record).rounds[-1].result)
    assert faithful == digest_battle(session.round.result()), "the untampered replay reproduces the run"

    raw = session.run_record.to_json()
    raw["rounds"][0][field] = change(raw["rounds"][0][field])
    tampered = RunRecord.from_json(raw)
    assert getattr(tampered.rounds[0], _ATTR[field]) != getattr(session.run_record.rounds[0], _ATTR[field]), (
        "the tamper actually applied"
    )

    try:
        diverged = digest_battle(replay_run(tampered).rounds[-1].result)
    except ReplayError:
        # A different battle can end before the recorded casts were reached, or
        # refuse one the server accepted live. The replay says so rather than
        # papering over it — which is also a divergence, loudly.
        return
    assert diverged != faithful


#: The record field names, and the attribute each parses into.
_ATTR = {"seed": "seed", "startingEnergy": "starting_energy", "baseHpAtStart": "base_hp_at_start"}


# -------------------------------------------------- base HP across rounds --


def test_a_multi_round_record_shows_base_damage_carried_without_recovery() -> None:
    """Full Starter carries base damage between rounds (Ryan, 2026-09-13).

    The damage is dealt by hand. A one-second round on a mirror map does not
    get anybody near a base, and a test that waited for real siege damage would
    be asserting "1000 == 1000" in two rounds running — which passes just as
    well against a server that heals bases between them.
    """
    session = make_session(STARTER, TINY)
    session.lock_in("north", lean_plan())
    session.lock_in("south", lean_plan())

    session.tick()
    session.round.world.bases["south"].hp -= 250.0

    # Play out round one and the pause after it, into round two's plan phase.
    while session.phase != "planning":
        session.tick()
    session.lock_in("north", lean_plan())
    session.lock_in("south", lean_plan())

    record = session.run_record
    assert len(record.rounds) == 2, "this test needs a second round to say anything"

    first, second = record.rounds
    assert first.base_hp_at_end is not None
    assert first.base_hp_at_end["south"] == 750.0, "the round ended on the damage it took"
    # Nothing between two rounds touches base HP. Asserted as equality and not
    # as "no more than it was", because a partial heal would slip past that.
    assert second.base_hp_at_start == first.base_hp_at_end
    assert second.base_hp_at_start["north"] == MAP.bases["north"].max_hp


# ------------------------------------------------------------- persistence --


async def test_a_record_is_stored_only_once_the_run_is_over(service: GameService) -> None:
    """A record of a match in progress would be a way to read a hidden plan."""
    session = make_session()
    session.lock_in("north", lean_plan())
    session.lock_in("south", lean_plan())
    session.tick()

    await service.persist_run_record(session)
    assert await service.run_record("run-1") is None, "nothing to read while there is still a reveal"

    while not session.over:
        session.tick()
    await service.persist_run_record(session)

    stored = await service.run_record("run-1")
    assert stored is not None
    assert stored["matchId"] == "m-1"
    assert stored["record"]["runId"] == "run-1"


async def test_storing_a_record_twice_leaves_one(service: GameService) -> None:
    """The finish path is retried; a record that stacked would be two runs."""
    session = played_run()
    await service.persist_run_record(session)
    await service.persist_run_record(session)

    stored = await service.run_record("run-1")
    assert stored is not None
    assert stored["record"] == session.run_record.to_json()


async def test_the_run_endpoint_serves_a_finished_run_and_nothing_else(
    client: TestClient, service: GameService
) -> None:
    client.post("/api/v1/matches", json=provision_body())
    for user, seat_key in (("user-north", "1"), ("user-south", "2")):
        client.post(
            f"/api/v1/matches/{MATCH}/claim",
            headers={"authorization": f"Bearer {fake_token(user, MATCH, seat_key)}"},
        )
    session = service.require_session(MATCH)

    assert client.get(f"/api/v1/runs/{session.run_id}").status_code == 404

    session.abandon()
    await service.persist_run_record(session)

    response = client.get(f"/api/v1/runs/{session.run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["record"]["runId"] == session.run_id
    assert body["record"]["terminalReason"] == "abandoned"


def test_an_unknown_run_is_a_404(client: TestClient) -> None:
    assert client.get("/api/v1/runs/nope").status_code == 404


async def test_finishing_a_match_twice_leaves_one_of_everything(
    client: TestClient, service: GameService, lobby: RecordingLobby
) -> None:
    """Retry-safe logical result completion, over the whole finish path.

    The path is retried by design — a Lobby that was briefly unreachable leaves
    a finished-and-unreported row for a sweep to find — so every write in it has
    to be idempotent, not just the Lobby call that motivated the retry. A second
    run must not report a second match, stack a second history row, or write a
    second record claiming to be the same run.

    Driven through `_on_match_finished` because that is the seam the clock
    actually calls; running the steps by hand here would be testing this test's
    idea of the order rather than the server's.
    """
    client.post("/api/v1/matches", json=provision_body())
    for user, seat_key in (("user-north", "1"), ("user-south", "2")):
        client.post(
            f"/api/v1/matches/{MATCH}/claim",
            headers={"authorization": f"Bearer {fake_token(user, MATCH, seat_key)}"},
        )
    session = service.require_session(MATCH)
    session.abandon(winner="north")

    await service._on_match_finished(session)
    await service._on_match_finished(session)

    assert len(lobby.results) == 1
    assert len(await service.history_for("user-north")) == 1
    stored = await service.run_record(session.run_id)
    assert stored is not None
    assert stored["record"]["terminalReason"] == "abandoned"
