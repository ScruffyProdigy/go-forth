"""What makes a session move in real time.

`MatchSession.tick()` advances the match exactly one tick and reads no clock.
This is the only module that knows what a second is, which is the split worth
keeping: every test in `tests/match/` drives a whole match by calling `tick()`
in a loop, in microseconds, over the same code that runs the real thing.

The loop paces itself against a monotonic deadline rather than sleeping a fixed
interval. Sleeping `1/tick_rate` between ticks drifts by however long the tick
itself took, so a battle would run measurably slow on a loaded host and the two
phones in JQ-313's smoke test would disagree about when 90 seconds had passed.
Catch-up is **bounded**: after a long stall the loop skips to the present rather
than sprinting through every missed tick, because a burst of 400 ticks delivered
at once is a battle the players cannot watch.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

from app.match.hub import MatchHub
from app.match.session import MatchSession
from app.sim.config import seconds_per_tick

log = logging.getLogger(__name__)

#: Ticks the loop will run back to back to catch up after a stall. Beyond this
#: the missed time is dropped: the match is behind the wall clock, which is
#: visible and survivable, rather than fast-forwarded past the players.
MAX_CATCH_UP_TICKS = 10


class SessionClock:
    """Drives one session's ticks until the match is over."""

    def __init__(
        self,
        session: MatchSession,
        hub: MatchHub,
        *,
        now: Callable[[], float] = time.monotonic,
        on_finished: Callable[[MatchSession], object] | None = None,
    ) -> None:
        self._session = session
        self._hub = hub
        self._now = now
        self._on_finished = on_finished
        self._task: asyncio.Task[None] | None = None
        self._interval = seconds_per_tick(session.sim_config)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"match:{self._session.external_match_id}")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        deadline = self._now()
        try:
            while not self._session.over:
                deadline += self._interval
                delay = deadline - self._now()
                if delay > 0:
                    await asyncio.sleep(delay)
                elif delay < -self._interval * MAX_CATCH_UP_TICKS:
                    # Long stall: give up on the missed ticks rather than run
                    # them all at once in front of a player.
                    deadline = self._now()

                if self._session.tick():
                    self._hub.publish(self._session.external_match_id, self._session)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A crashed tick loop would leave two players staring at a frozen
            # board with no explanation, so the match is ended rather than
            # abandoned in place, and the exception is logged whole.
            log.exception("[match] %s tick loop failed", self._session.external_match_id)
            self._session.abandon()
            self._hub.publish(self._session.external_match_id, self._session)

        if self._on_finished is not None:
            result = self._on_finished(self._session)
            if asyncio.iscoroutine(result):
                await result
