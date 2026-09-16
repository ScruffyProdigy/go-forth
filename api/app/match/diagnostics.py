"""Why a run went the way it did — as structured events, not prose in a log line.

The demo's two failure stories are *"my spell didn't go off"* and *"I got kicked
out"*, and neither is answerable from a battle log. Both are decisions the
server made about a **command** or a **connection**, so those are the two
channels here, and they stay two.

## Channels are separated on purpose

| channel      | what it records                                            |
|--------------|------------------------------------------------------------|
| `command`    | a cast refused, and a retry answered from the ledger        |
| `connection` | a seat arriving, returning, dropping, or being turned away  |

Keeping them apart is the point rather than tidiness. "Fourteen casts were
refused for `stale`" and "one player reconnected fourteen times" are different
findings with different fixes, and a single stream where a reconnect storm and a
rejection storm are interleaved makes each look like noise in the other.

**AI diversion and return diagnostics are JQ-331's**, and stay in JQ-331's own
sink rather than gaining a channel here. Why a *unit* changed its mind is a
question about the evaluator, answered against a scenario; why a *command* was
refused is a question about one socket at one moment. Folding them together
would mean every AI scenario dump carried socket noise and every recovery
investigation carried decision scores.

## No secrets, enforced rather than asked for

A diagnostic is written to be read by someone who is not in the match, so it
must not carry anything that would let them into it. The one that matters is
`player_id`: it is not an identifier, it is *the gameplay credential* — the
WebSocket subscribes with it, the seat binding is checked against it, and a
diagnostic carrying one is a diagnostic that seats its reader. Lobby service
tokens and seat JWTs are the same hazard by a shorter argument.

`record()` raises on those field names rather than documenting them, because a
rule that is only written down is a rule that holds until the first hurried
addition. Seats are named by `seatKey` and `side`, which identify a chair and
not a person.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

log = logging.getLogger(__name__)

Channel = Literal["command", "connection"]

#: Field names a diagnostic may never carry, matched case-insensitively against
#: the whole name so `playerId`, `player_id` and `lobbyPlayerIdHint` are all
#: caught. Substrings rather than exact names: the failure mode is a new field
#: spelled slightly differently, not a re-use of the exact name already refused.
FORBIDDEN_FIELD_PARTS: tuple[str, ...] = ("playerid", "token", "secret", "authorization", "cookie", "jwt")

#: Events kept in memory per match. Enough to cover a whole demo run's worth of
#: refusals and reconnects; bounded because this is a live server and an
#: unbounded deque behind a socket a client controls is a memory leak with a
#: retry loop attached.
MAX_EVENTS_PER_MATCH = 256


class SecretInDiagnostic(ValueError):
    """A diagnostic field that would have carried a credential."""


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    channel: Channel
    #: Dotted and stable — `command.rejected`, `connection.reconnected`. What a
    #: reader greps for, so it is spelled once here and never formatted.
    kind: str
    match_id: str
    run_id: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_json(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "kind": self.kind,
            "matchId": self.match_id,
            "runId": self.run_id,
            "at": self.at.isoformat(),
            **dict(self.fields),
        }


def _check_fields(fields: Mapping[str, Any]) -> None:
    for name in fields:
        flattened = name.replace("_", "").lower()
        for forbidden in FORBIDDEN_FIELD_PARTS:
            if forbidden in flattened:
                raise SecretInDiagnostic(
                    f"{name!r} would put a credential in a diagnostic; name the seat instead"
                )


class DiagnosticsLog:
    """A bounded, per-match record of command and connection decisions."""

    def __init__(self, max_events: int = MAX_EVENTS_PER_MATCH) -> None:
        self._max_events = max_events
        self._events: dict[str, deque[DiagnosticEvent]] = {}

    def record(
        self,
        *,
        channel: Channel,
        kind: str,
        match_id: str,
        run_id: str,
        **fields: Any,
    ) -> DiagnosticEvent:
        _check_fields(fields)
        event = DiagnosticEvent(
            channel=channel, kind=kind, match_id=match_id, run_id=run_id, fields=dict(fields)
        )
        bucket = self._events.get(match_id)
        if bucket is None:
            bucket = deque(maxlen=self._max_events)
            self._events[match_id] = bucket
        bucket.append(event)
        # Logged as well as kept: the in-memory copy is for the run record and
        # for tests, and dies with the process. What an operator reads after a
        # demo is the log.
        log.info("[%s] %s %s", event.channel, event.kind, event.to_json())
        return event

    def events(self, match_id: str, *, channel: Channel | None = None) -> list[DiagnosticEvent]:
        """This match's events, oldest first, optionally one channel only."""
        bucket = self._events.get(match_id, ())
        if channel is None:
            return list(bucket)
        return [event for event in bucket if event.channel == channel]

    def summary(self, match_id: str) -> dict[str, int]:
        """How many of each kind. Sorted, so two processes print the same thing."""
        counts: dict[str, int] = {}
        for event in self._events.get(match_id, ()):
            counts[event.kind] = counts.get(event.kind, 0) + 1
        return dict(sorted(counts.items()))

    def forget(self, match_id: str) -> None:
        self._events.pop(match_id, None)

    def __iter__(self) -> Iterator[str]:
        """The match ids held. Sorted — nothing here may leak dict order."""
        return iter(sorted(self._events))


def redacted(fields: Iterable[str]) -> list[str]:
    """Which of these names `record` would refuse. For tests and for review."""
    refused: list[str] = []
    for name in fields:
        try:
            _check_fields({name: None})
        except SecretInDiagnostic:
            refused.append(name)
    return refused
