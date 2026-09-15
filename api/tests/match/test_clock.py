"""The only module that knows what a second is.

The split `clock.py` exists for is what makes every other test in this
directory fast: `MatchSession.tick()` reads no clock, so a match runs in
microseconds under a loop and in real time under this. What is left to test
here is the pacing itself — that it does not drift, and that it does not sprint
through a stall in front of a player.
"""

from __future__ import annotations

import asyncio

from app.lobby.manifest import OPENING_ROUND
from app.match import fixtures
from app.match.clock import MAX_CATCH_UP_TICKS, SessionClock
from app.match.hub import MatchHub
from app.match.session import MatchSession
from app.sim.config import SimConfig


def make_session(seconds: float = 2) -> MatchSession:
    session = MatchSession(
        run_id="run-1",
        external_match_id="m-1",
        mode=OPENING_ROUND,
        seats={"1": "north", "2": "south"},
        map_config=fixtures.map_config(),
        sim_config=SimConfig(max_battle_seconds=seconds, tick_rate=200),
    )
    plan = fixtures.opening_plan_json(1, fixtures.map_config())
    session.lock_in("north", plan)
    session.lock_in("south", plan)
    return session


async def test_the_clock_runs_a_match_to_its_end() -> None:
    session = make_session(seconds=0.2)
    hub = MatchHub()
    clock = SessionClock(session, hub)

    clock.start()
    for _ in range(200):
        if session.over:
            break
        await asyncio.sleep(0.01)

    assert session.over
    await clock.stop()
    assert not clock.running


async def test_every_tick_that_changes_something_is_published() -> None:
    session = make_session(seconds=0.2)
    hub = MatchHub()
    seen: list[str] = []
    hub.subscribe("m-1", lambda s: seen.append(s.phase))

    clock = SessionClock(session, hub)
    clock.start()
    for _ in range(200):
        if session.over:
            break
        await asyncio.sleep(0.01)
    await clock.stop()

    assert seen, "the battle ticked but nothing reached a subscriber"
    assert seen[-1] == "matchOver"


async def test_stopping_is_idempotent_and_safe_before_starting() -> None:
    clock = SessionClock(make_session(), MatchHub())
    await clock.stop()  # never started
    clock.start()
    await clock.stop()
    await clock.stop()
    assert not clock.running


async def test_starting_twice_does_not_run_two_loops() -> None:
    session = make_session(seconds=0.2)
    clock = SessionClock(session, MatchHub())
    clock.start()
    first = clock._task
    clock.start()
    # Two loops would advance the same sim twice per tick and halve the battle.
    assert clock._task is first
    await clock.stop()


async def test_a_long_stall_is_not_replayed_in_a_burst() -> None:
    """Catch-up is bounded.

    After a stall the loop skips to the present rather than sprinting through
    every missed tick: a burst of 400 ticks delivered at once is a battle the
    players cannot watch.
    """
    session = make_session(seconds=10)
    hub = MatchHub()

    # A clock whose "now" jumps far past its deadline on the first read, which
    # is what a stalled event loop looks like from inside the loop.
    readings = iter([0.0, 0.0, 100.0] + [100.0 + i * 0.001 for i in range(1, 10_000)])
    clock = SessionClock(session, hub, now=lambda: next(readings))

    clock.start()
    await asyncio.sleep(0.05)
    ticks = session._round.world.tick if session._round else 0
    await clock.stop()

    # 100 seconds at 200 ticks/second is 20,000 missed ticks. Whatever ran, it
    # was not that.
    assert ticks < 20_000
    assert MAX_CATCH_UP_TICKS > 0


async def test_a_crashing_tick_ends_the_match_rather_than_freezing_it() -> None:
    session = make_session(seconds=5)
    hub = MatchHub()

    def explode() -> bool:
        raise RuntimeError("the sim fell over")

    session.tick = explode  # type: ignore[method-assign]
    clock = SessionClock(session, hub)
    clock.start()
    for _ in range(100):
        if session.over:
            break
        await asyncio.sleep(0.01)
    await clock.stop()

    # A crashed tick loop would leave two players staring at a frozen board with
    # no explanation.
    assert session.over
    assert session.snapshot_for("north")["phase"]["result"]["ending"]["kind"] == "abandoned"


async def test_the_finished_callback_runs_once_the_match_is_over() -> None:
    session = make_session(seconds=0.2)
    finished: list[MatchSession] = []

    async def on_finished(s: MatchSession) -> None:
        finished.append(s)

    clock = SessionClock(session, MatchHub(), on_finished=on_finished)
    clock.start()
    for _ in range(200):
        if finished:
            break
        await asyncio.sleep(0.01)
    await clock.stop()

    # This is what persists the result and reports it to the Lobby.
    assert finished == [session]
