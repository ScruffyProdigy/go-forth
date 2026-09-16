"""Where matches and players are kept, and the two places they are kept.

`Repository` is the seam. `MemoryRepository` is the whole of what the contract
tests need, and `PgRepository` is what runs. Both satisfy the same protocol, and
the split is not a testing convenience but a fact about CI: `api-tests.yml` has
no Postgres service, so a contract suite that needed a database would be a
contract suite that never ran.

The rule that keeps the two honest: **nothing here knows what a battle is.** A
repository stores identity, seating, outcomes — and, since JQ-310, the *record*
of a finished run as an opaque document.

A run record is not an exception to that rule, and the distinction is worth
being exact about because it looks like one. Live match state still lives in
`MatchSession` and is still not persisted: a server restart loses the match in
progress, exactly as before. What is stored is what a finished run *was* — the
inputs it was a function of — written once when the match ends, read only by a
replay. Nothing resumes from it, and a schema that let something try would be
the promise this layer has always declined to make.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol


class NotFoundError(Exception):
    """No such match, seat or player. A 404."""


class ConflictError(Exception):
    """The seat is taken by someone else. A 409."""


class ReservationError(Exception):
    """This seat is reserved for a different Lobby user. A 403."""


@dataclass
class StoredSeat:
    seat_key: str
    position: int
    reserved_for_lobby_user: str | None = None
    #: Set when a player claims it.
    player_id: str | None = None
    player_name: str | None = None
    lobby_user_id: str | None = None


@dataclass
class StoredMatch:
    id: str
    external_match_id: str
    game_mode: str
    run_id: str
    test_profile: bool
    lobby_issuer: str | None = None
    return_url: str | None = None
    graphql_url: str | None = None
    service_token: str | None = None
    status: str = "waiting"
    seats: list[StoredSeat] = field(default_factory=list)
    finished_at: datetime | None = None
    reported_at: datetime | None = None

    def seat(self, seat_key: str) -> StoredSeat | None:
        for seat in self.seats:
            if seat.seat_key == seat_key:
                return seat
        return None


@dataclass
class StoredResult:
    """One person's outcome in one match."""

    match_id: str
    lobby_user_id: str
    seat_key: str
    side: str
    ending: str
    won: bool | None
    rounds_won: int
    base_hp: float | None
    test_profile: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ClaimResult:
    match: StoredMatch
    seat: StoredSeat
    #: True when the seat was already this player's — a reconnect, not a join.
    #: The claim route answers 200 for a re-claim and 201 for a first sitting.
    reclaimed: bool


class Repository(Protocol):
    async def upsert_match(
        self,
        *,
        external_match_id: str,
        game_mode: str,
        run_id: str,
        test_profile: bool,
        seats: Sequence[tuple[str, str | None]],
        lobby_issuer: str | None,
        return_url: str | None,
        graphql_url: str | None,
        service_token: str | None,
    ) -> StoredMatch:
        """Create the match, or return the existing one unchanged.

        **Idempotent on `external_match_id`** — the checklist's
        `provision.idempotent_repush` row. Lobby re-pushes on its own retries,
        and a second push must not re-seat a match already being played.
        """
        ...

    async def get_match(self, external_match_id: str) -> StoredMatch | None: ...

    async def claim_seat(
        self,
        *,
        external_match_id: str,
        seat_key: str,
        lobby_user_id: str | None,
        display_name: str,
    ) -> ClaimResult: ...

    async def record_player(self, lobby_user_id: str, display_name: str) -> None: ...

    async def record_result(self, result: StoredResult) -> None: ...

    async def results_for_player(self, lobby_user_id: str, limit: int = 20) -> list[StoredResult]: ...

    async def mark_finished(self, external_match_id: str, *, reported: bool) -> None: ...

    async def record_run(self, *, run_id: str, external_match_id: str, record: dict[str, Any]) -> None:
        """Store a finished run's record, keyed by run id.

        Idempotent on `run_id`: `_on_match_finished` can run more than once for
        one match — a retry sweep, a clock that finished twice — and a record
        that stacked would leave two documents claiming to be the same run.
        """
        ...

    async def get_run(self, run_id: str) -> dict[str, Any] | None: ...


class MemoryRepository:
    """Everything the contract tests need, and nothing that outlives the process."""

    def __init__(self) -> None:
        self._matches: dict[str, StoredMatch] = {}
        self._players: dict[str, dict[str, Any]] = {}
        self._results: dict[tuple[str, str], StoredResult] = {}
        self._runs: dict[str, dict[str, Any]] = {}

    async def upsert_match(
        self,
        *,
        external_match_id: str,
        game_mode: str,
        run_id: str,
        test_profile: bool,
        seats: Sequence[tuple[str, str | None]],
        lobby_issuer: str | None,
        return_url: str | None,
        graphql_url: str | None,
        service_token: str | None,
    ) -> StoredMatch:
        existing = self._matches.get(external_match_id)
        if existing is not None:
            # Endpoints are refreshed because a Lobby may legitimately move
            # between pushes; seats and run id are not, because they are what
            # the match already is.
            existing.return_url = return_url or existing.return_url
            existing.graphql_url = graphql_url or existing.graphql_url
            existing.service_token = service_token or existing.service_token
            return existing

        match = StoredMatch(
            id=str(uuid.uuid4()),
            external_match_id=external_match_id,
            game_mode=game_mode,
            run_id=run_id,
            test_profile=test_profile,
            lobby_issuer=lobby_issuer,
            return_url=return_url,
            graphql_url=graphql_url,
            service_token=service_token,
            seats=[
                StoredSeat(seat_key=seat_key, position=index, reserved_for_lobby_user=reserved)
                for index, (seat_key, reserved) in enumerate(seats)
            ],
        )
        self._matches[external_match_id] = match
        return match

    async def get_match(self, external_match_id: str) -> StoredMatch | None:
        return self._matches.get(external_match_id)

    async def claim_seat(
        self,
        *,
        external_match_id: str,
        seat_key: str,
        lobby_user_id: str | None,
        display_name: str,
    ) -> ClaimResult:
        match = self._matches.get(external_match_id)
        if match is None:
            raise NotFoundError("match not found")
        seat = match.seat(seat_key)
        if seat is None:
            raise NotFoundError("seat not found")

        reserved = seat.reserved_for_lobby_user
        if reserved and lobby_user_id and reserved != lobby_user_id:
            raise ReservationError("that seat is reserved for another player")

        if seat.player_id is not None:
            # The re-claim rule (§6): the same `sub` returning gets the seat
            # back; anyone else is refused. This is the half that lets a player
            # who lost their tab get back in while still keeping others out.
            if lobby_user_id and seat.lobby_user_id == lobby_user_id:
                seat.player_name = display_name or seat.player_name
                return ClaimResult(match=match, seat=seat, reclaimed=True)
            raise ConflictError("that seat is already taken")

        seat.player_id = str(uuid.uuid4())
        seat.player_name = display_name
        seat.lobby_user_id = lobby_user_id
        if lobby_user_id:
            await self.record_player(lobby_user_id, display_name)
        return ClaimResult(match=match, seat=seat, reclaimed=False)

    async def record_player(self, lobby_user_id: str, display_name: str) -> None:
        now = datetime.now(UTC)
        row = self._players.get(lobby_user_id)
        if row is None:
            self._players[lobby_user_id] = {
                "display_name": display_name,
                "first_seen_at": now,
                "last_seen_at": now,
                "matches_played": 0,
            }
            return
        row["display_name"] = display_name or row["display_name"]
        row["last_seen_at"] = now

    async def record_result(self, result: StoredResult) -> None:
        key = (result.match_id, result.lobby_user_id)
        first_time = key not in self._results
        self._results[key] = result
        row = self._players.get(result.lobby_user_id)
        if row is not None and first_time:
            row["matches_played"] += 1

    async def results_for_player(self, lobby_user_id: str, limit: int = 20) -> list[StoredResult]:
        rows = [row for row in self._results.values() if row.lobby_user_id == lobby_user_id]
        rows.sort(key=lambda row: (row.created_at, row.match_id), reverse=True)
        return rows[:limit]

    async def mark_finished(self, external_match_id: str, *, reported: bool) -> None:
        match = self._matches.get(external_match_id)
        if match is None:
            return
        now = datetime.now(UTC)
        match.status = "finished"
        match.finished_at = match.finished_at or now
        if reported:
            match.reported_at = match.reported_at or now

    async def record_run(self, *, run_id: str, external_match_id: str, record: dict[str, Any]) -> None:
        # What arrives is an already-serialised document, not the live
        # `RunRecord` — `service.persist_run_record` calls `to_json()` on the
        # way in. That is what keeps this store from aliasing an object the
        # session could still append to, and it is also what `PgRepository`
        # receives, so the two are handed the same thing.
        self._runs[run_id] = {
            "runId": run_id,
            "matchId": external_match_id,
            "record": dict(record),
        }

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._runs.get(run_id)
        return dict(row) if row is not None else None

    # -------------------------------------------------------------- testing --

    def player_row(self, lobby_user_id: str) -> dict[str, Any] | None:
        """Read a player row directly. Tests only — not on the protocol."""
        return self._players.get(lobby_user_id)
