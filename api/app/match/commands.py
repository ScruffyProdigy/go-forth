"""The command ledger: one answer per command id, however many times it is asked.

A phone on a train loses acknowledgments, not commands. The client sends a cast,
the socket drops before the `castOutcome` comes back, the client reconnects and
sends the same cast again because from where it is sitting nothing happened. If
the server treats that as a second cast, the player is charged twice for one
meteor and two of them land — which is the same bug as a double-tap, except the
player did nothing wrong and cannot avoid it.

So every cast carries a client-minted `commandId`, and this is where it is
spent. The **first** time a command id is seen the cast is evaluated for real;
every time after, the recorded answer is handed back without the round being
touched. That is what makes the wire retry-safe: a client may resend until it
hears something, and the match is the same either way.

## Why the ledger outlives the round

It hangs off `MatchSession`, not off `AuthoritativeRound`. A retry can arrive
after the round it belonged to has ended — that is the *most likely* moment for
one, since a socket that dropped mid-battle reconnects some seconds later — and
a ledger scoped to the round would have been thrown away by then. The retry
would be re-evaluated against a round that no longer exists and answered
`roundOver`, telling a player their meteor failed when it had already landed.

## Why rejections are recorded too

A command id's answer is **final**, accepted or not. A cast refused for
`notEnoughEnergy` and retried ten seconds later, when the seat can afford it,
is still answered `notEnoughEnergy`: the client asked "what happened to c7?",
and the honest answer does not change because time passed. A player who wants
to try again taps again, and the client mints a new id for it — which is the
distinction the whole scheme rests on, and the one rule a client has to keep.

## Why the key is (side, command id)

Client-minted ids are unique per client, not per match. Two phones can
independently mint `c1`, and a ledger keyed on the id alone would answer south's
first cast with north's outcome — a cross-seat information leak reachable
without either player doing anything unusual.

## Why it is bounded

The key is chosen by the client, so the ledger is a dictionary a client can add
to at will — unbounded, that is a memory leak with a retry loop attached, and a
socket is all it takes to drive one. It keeps the most recent
`MAX_ENTRIES_PER_SEAT` ids per seat and drops the oldest beyond that.

Nothing legitimate is lost. What the ledger protects is a client resending a
cast it has not heard about, which happens within seconds; a seat that has spent
five hundred command ids in one match is not waiting on an acknowledgment from
the first of them. `wire.MAX_COMMAND_ID_LENGTH` bounds the other dimension —
how large each key may be — at the point the command is parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.match.wire import CastRejection, cast_outcome_message
from app.sim.types import Side

#: Command ids remembered per seat. Comfortably more than a demo round's worth
#: of casts and retries, and small enough that a client hammering fresh ids
#: costs a bounded amount of memory.
MAX_ENTRIES_PER_SEAT = 512


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """What the server decided about one command id, kept so it can be re-said."""

    command_id: str
    accepted: bool
    #: Present on a rejection only.
    reason: CastRejection | None = None
    #: The round the command was answered in. Diagnostics only — the answer does
    #: not change because the match has moved on.
    round_number: int | None = None
    #: The tick the server scheduled the cast on, and its order within the
    #: round. Both server-assigned; both None on a rejection.
    tick: int | None = None
    order: int | None = None

    def to_message(self) -> dict[str, Any]:
        """The same `castOutcome` the first answer sent."""
        if self.accepted:
            return cast_outcome_message("accepted", self.command_id)
        return cast_outcome_message("rejected", self.command_id, self.reason)


class CommandLedger:
    """Every command id this match has answered, per seat, most recent first out."""

    def __init__(self, max_entries_per_seat: int = MAX_ENTRIES_PER_SEAT) -> None:
        self._max = max_entries_per_seat
        self._entries: dict[Side, dict[str, LedgerEntry]] = {}

    def find(self, side: Side, command_id: str) -> LedgerEntry | None:
        """The answer already given to this seat for this id, or None."""
        return self._entries.get(side, {}).get(command_id)

    def record(self, side: Side, entry: LedgerEntry) -> LedgerEntry:
        """Keep the answer. Never overwrites: the first answer is the answer.

        Returning the stored entry rather than the argument means a caller
        racing itself still sends what the ledger holds, so two paths cannot
        report two different outcomes for one id.
        """
        seat = self._entries.setdefault(side, {})
        existing = seat.get(entry.command_id)
        if existing is not None:
            return existing
        seat[entry.command_id] = entry
        while len(seat) > self._max:
            # Insertion order is age order, and dicts preserve it. The oldest id
            # is the one whose acknowledgment nobody is still waiting for.
            seat.pop(next(iter(seat)))
        return entry

    def count_for(self, side: Side) -> int:
        """How many command ids this seat is still remembered for."""
        return len(self._entries.get(side, {}))
