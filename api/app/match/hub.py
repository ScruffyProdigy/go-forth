"""In-process fan-out for live match state.

The session publishes after every change; each WebSocket subscribes to one match
and projects what arrives for the seat it holds. REST and WebSocket mutations
therefore reach every watcher by the same path, so a plan locked over REST
updates a socket and vice versa.

What travels is the **session**, not a rendered snapshot: one match has as many
views as it has seats once energy and loadouts are in play, and a subscriber has
to say whose view it is asking for. `MatchSession.snapshot_for(side)` is the only
way to get one out, which is what stops a projection for the wrong seat being
constructible by accident.

NOTE: single-process. A multi-replica deployment needs a real fan-out behind
this — Postgres `LISTEN`/`NOTIFY` is the one already in the stack — and the
interface does not change when it arrives.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to the checker
    from app.match.session import MatchSession

MatchListener = Callable[["MatchSession"], None]


class MatchHub:
    def __init__(self) -> None:
        self._listeners: dict[str, list[MatchListener]] = {}

    def subscribe(self, match_id: str, listener: MatchListener) -> Callable[[], None]:
        listeners = self._listeners.setdefault(match_id, [])
        listeners.append(listener)

        def unsubscribe() -> None:
            current = self._listeners.get(match_id)
            if current is None:
                return
            try:
                current.remove(listener)
            except ValueError:
                return
            if not current:
                self._listeners.pop(match_id, None)

        return unsubscribe

    def publish(self, match_id: str, session: MatchSession) -> None:
        """Deliver to every listener, and let none of them stop the others.

        A socket that has gone away raises on send. Without this guard the first
        such listener would swallow the update for everyone after it in the
        list — a bug that only shows up once someone closes a tab.
        """
        for listener in list(self._listeners.get(match_id, ())):
            try:
                listener(session)
            except Exception:
                continue

    def listener_count(self, match_id: str) -> int:
        return len(self._listeners.get(match_id, ()))
