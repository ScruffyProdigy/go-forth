"""What the routes and the WebSocket both go through.

One object owns the two stores that must not disagree: the repository, which
outlives a process, and the live `MatchSession` registry, which does not. Every
mutation that touches both goes through here, so there is no path where a seat
is claimed in the database and not in the session.

Seats to sides: Lobby's template expansion numbers seats `"1"`, `"2"`, and the
sim's sides are `north`/`south`. The mapping is **positional and fixed** — seat
1 is north, seat 2 is south — so a player who reconnects lands on the side they
were playing. Deriving it from anything mutable (claim order, say) would move a
player's army under them on a reconnect.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Sequence
from typing import Any

from app.lobby.client import LobbyClient, resolve_display_name
from app.lobby.manifest import GameMode, mode_or_default, seat_keys_for_mode
from app.lobby.provision import LobbyProvision
from app.lobby.seat_binding import SeatBinding
from app.lobby.tokens import AssignmentClaims
from app.match import fixtures
from app.match.clock import SessionClock
from app.match.hub import MatchHub
from app.match.session import MatchSession
from app.repository import (
    ClaimResult,
    ConflictError,
    NotFoundError,
    Repository,
    StoredMatch,
    StoredResult,
)
from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig
from app.sim.types import SIDES, Side

log = logging.getLogger(__name__)


class BannedPlayerError(Exception):
    """This roster carries someone this game will not host. A 403 with the ids."""

    def __init__(self, banned: Sequence[str]) -> None:
        super().__init__("one or more players are banned from this game")
        self.banned_lobby_user_ids = list(banned)


class ValidationError(Exception):
    """A 400."""


def sides_for_seats(seat_keys: Sequence[str]) -> dict[str, Side]:
    """Seat key to side, positionally. Seat 1 is north, seat 2 is south."""
    return {seat_key: SIDES[index % len(SIDES)] for index, seat_key in enumerate(seat_keys)}


class GameService:
    def __init__(
        self,
        repository: Repository,
        hub: MatchHub,
        *,
        sim_config: SimConfig = DEFAULT_SIM_CONFIG,
        banned_lobby_user_ids: Sequence[str] = (),
        lobby_client_factory: Any = None,
    ) -> None:
        self._repo = repository
        self._hub = hub
        self._sim_config = sim_config
        # A membership set: never iterated, per the hash-ordering rule.
        self._banned = frozenset(banned_lobby_user_ids)
        self._lobby_client_factory = lobby_client_factory or LobbyClient
        self._sessions: dict[str, MatchSession] = {}
        self._clocks: dict[str, SessionClock] = {}

    @property
    def hub(self) -> MatchHub:
        return self._hub

    # ------------------------------------------------------------ provision --

    def banned_in(self, lobby_user_ids: Sequence[str]) -> list[str]:
        """Which of these are banned, in the order they were given.

        Order is the caller's, not the set's: this list goes on the wire in the
        403 body, and a response whose field order changed between two
        interpreters would be the hash-ordering bug in a place nobody would look.
        """
        return [user_id for user_id in lobby_user_ids if user_id in self._banned]

    async def ensure_match_from_assignment(self, provision: LobbyProvision) -> StoredMatch:
        """Create the match if it is new; return it unchanged if it is not.

        Idempotent on `externalMatchId`, which is the whole of what the
        `provision.idempotent_repush` check asks. The banlist is checked before
        anything is written: a 403 must leave no match behind, or Lobby's next
        push finds one it was just refused.
        """
        banned = self.banned_in(provision.lobby_user_ids)
        if banned:
            raise BannedPlayerError(banned)

        mode = mode_or_default(provision.assignment.game_mode)
        assignment = provision.assignment

        existing = await self._repo.get_match(assignment.external_match_id)
        if existing is not None:
            self._ensure_session(existing, mode, provision)
            return existing

        seats = [
            (seat.seat_key, seat.lobby_user_id or None)
            for seat in sorted(assignment.seats, key=lambda seat: seat.seat_key)
        ]
        match = await self._repo.upsert_match(
            external_match_id=assignment.external_match_id,
            game_mode=mode.key,
            # Identifies this run of the demo. A new provision mints a new one,
            # which is what "a fresh run carries nothing over" means concretely.
            run_id=secrets.token_hex(8),
            test_profile=mode.round_policy.test_profile,
            seats=seats,
            lobby_issuer=provision.lobby_id,
            return_url=provision.lobby.return_url,
            graphql_url=provision.lobby.graphql_url,
            service_token=provision.lobby.service_token,
        )
        for seat in assignment.seats:
            if seat.lobby_user_id:
                await self._repo.record_player(seat.lobby_user_id, seat.display_name or "Mage")

        self._ensure_session(match, mode, provision)
        return match

    def _ensure_session(
        self,
        match: StoredMatch,
        mode: GameMode,
        provision: LobbyProvision | None = None,
    ) -> MatchSession:
        session = self._sessions.get(match.external_match_id)
        if session is not None:
            return session

        seat_keys = [seat.seat_key for seat in sorted(match.seats, key=lambda seat: seat.position)]
        if not seat_keys:
            seat_keys = list(seat_keys_for_mode(mode))

        lobby_client: LobbyClient | None = None
        graphql_url = (provision.lobby.graphql_url if provision else None) or match.graphql_url
        if graphql_url:
            service_token = (provision.lobby.service_token if provision else None) or match.service_token
            lobby_client = self._lobby_client_factory(graphql_url, service_token)

        session = MatchSession(
            run_id=match.run_id,
            external_match_id=match.external_match_id,
            mode=mode,
            seats=sides_for_seats(seat_keys),
            map_config=fixtures.map_config(),
            sim_config=self._sim_config,
            lobby_client=lobby_client,
        )
        for stored in match.seats:
            seat = session.seats.get(stored.seat_key)
            if seat is not None:
                seat.lobby_user_id = stored.reserved_for_lobby_user or stored.lobby_user_id
        self._sessions[match.external_match_id] = session
        return session

    async def get_match(self, external_match_id: str) -> StoredMatch | None:
        """The stored match, for callers that want seating without a session."""
        return await self._repo.get_match(external_match_id)

    def session(self, external_match_id: str) -> MatchSession | None:
        return self._sessions.get(external_match_id)

    def require_session(self, external_match_id: str) -> MatchSession:
        session = self._sessions.get(external_match_id)
        if session is None:
            raise NotFoundError("match not found")
        return session

    # ---------------------------------------------------------------- claim --

    async def claim_with_lobby_token(
        self,
        claims: AssignmentClaims,
        *,
        player_name: str | None = None,
    ) -> tuple[ClaimResult, MatchSession, Side]:
        """Seat the holder of a verified token, or refuse them.

        `assertMatchProvisioned` in rpslr is folded in here: a token naming a
        match we were never pushed is a 404, not a 401. The token is genuine; we
        simply have no such match, and saying "invalid token" would send an
        integrator looking at their signing key.
        """
        match = await self._repo.get_match(claims.external_match_id)
        if match is None:
            raise NotFoundError("match not found")

        seat = match.seat(claims.seat_key)
        if seat is None:
            raise NotFoundError("seat not found")

        mode = mode_or_default(match.game_mode)
        session = self._ensure_session(match, mode)

        lobby_client = session.lobby_client
        name = await resolve_display_name(
            from_token=claims.display_name,
            client=lobby_client,
            lobby_user_id=claims.lobby_user_id,
            from_body=player_name,
        )

        result = await self._repo.claim_seat(
            external_match_id=claims.external_match_id,
            seat_key=claims.seat_key,
            lobby_user_id=claims.lobby_user_id,
            display_name=name,
        )

        side = self._seat_side(session, result.seat.seat_key)
        live = session.seats[result.seat.seat_key]
        live.lobby_user_id = claims.lobby_user_id
        live.player_id = result.seat.player_id
        live.display_name = name
        # A re-claim is "resend me the current state", not "join": no reset, no
        # second join event, nothing re-dealt (integration guide §6). Marking
        # the seat departed=False is the whole of what returning does here.
        live.departed = False

        self._hub.publish(session.external_match_id, session)
        return result, session, side

    def _seat_side(self, session: MatchSession, seat_key: str) -> Side:
        side = session.side_for_seat(seat_key)
        if side is None:
            raise NotFoundError("seat not found")
        return side

    async def resume_from_binding(self, binding: SeatBinding) -> tuple[MatchSession, Side] | None:
        """Recovery path 1: this browser's own binding, with no Lobby round trip.

        The binding **names** a seat; the match **decides**. A binding naming a
        finished match, or a seat someone else now holds, resumes nothing — and
        the caller clears the cookie so a browser stops presenting one that can
        never work again.
        """
        match = await self._repo.get_match(binding.external_match_id)
        if match is None:
            return None
        seat = match.seat(binding.seat_key)
        if seat is None or seat.player_id != binding.player_id:
            return None
        if seat.lobby_user_id != binding.lobby_user_id:
            return None

        session = self._sessions.get(binding.external_match_id)
        if session is None or session.over:
            return None

        return session, self._seat_side(session, binding.seat_key)

    # ------------------------------------------------------------ lifecycle --

    def start_clock(self, session: MatchSession) -> None:
        """Begin ticking a match. Idempotent — a second claim does not start two."""
        clock = self._clocks.get(session.external_match_id)
        if clock is not None and clock.running:
            return
        clock = SessionClock(session, self._hub, on_finished=self._on_match_finished)
        self._clocks[session.external_match_id] = clock
        clock.start()

    async def stop_clock(self, external_match_id: str) -> None:
        clock = self._clocks.pop(external_match_id, None)
        if clock is not None:
            await clock.stop()

    async def shutdown(self) -> None:
        for external_match_id in list(self._clocks):
            await self.stop_clock(external_match_id)

    async def _on_match_finished(self, session: MatchSession) -> None:
        """Persist the outcome, then tell the Lobby. In that order, deliberately.

        The Lobby call can fail; the row must not be lost with it. Writing first
        means a match that finished during a Lobby outage is still a row a retry
        sweep can find, which is what `idx_matches_unreported` is indexed for.
        """
        await self.persist_result(session)
        ok = await session.report_to_lobby()
        await self._repo.mark_finished(session.external_match_id, reported=ok)

    async def persist_result(self, session: MatchSession) -> None:
        """One `match_results` row per seated player, keyed by Lobby user id."""
        report = session.result_report()
        if report is None:
            return
        _status, winners, metadata = report
        match = await self._repo.get_match(session.external_match_id)
        if match is None:
            return

        ending = str(metadata.get("ending") or "")
        for side in SIDES:
            seat = session.seat_for_side(side)
            if not seat.lobby_user_id:
                continue
            base_hp = session.snapshot_for(side)["baseHp"][side]["hp"]
            # NULL rather than False on a run with no winner: "did not win"
            # and "nobody won" are different facts, and a history that conflated
            # them would read as a loss for both players.
            decisive = ending in ("baseDestroyed", "roundsWon")
            won: bool | None = seat.lobby_user_id in winners if decisive else None
            await self._repo.record_result(
                StoredResult(
                    match_id=match.id,
                    lobby_user_id=seat.lobby_user_id,
                    seat_key=seat.seat_key,
                    side=side,
                    ending=ending,
                    won=won,
                    rounds_won=session.rounds_won[side],
                    base_hp=float(base_hp),
                    test_profile=session.policy.test_profile,
                )
            )

    async def history_for(self, lobby_user_id: str, limit: int = 20) -> list[StoredResult]:
        return await self._repo.results_for_player(lobby_user_id, limit)

    # ------------------------------------------------------------ standalone --

    async def create_standalone_match(self, *, game_mode: str | None = None) -> StoredMatch:
        """A match with no Lobby in front of it — the v1 mode rpslr shipped with.

        Seats carry no reservation, so any arriving player may take an open one.
        This is what makes the game playable from a checkout with nothing else
        running, which is the first thing anyone reading a reference does.
        """
        mode = mode_or_default(game_mode)
        external_match_id = f"local-{secrets.token_hex(6)}"
        match = await self._repo.upsert_match(
            external_match_id=external_match_id,
            game_mode=mode.key,
            run_id=secrets.token_hex(8),
            test_profile=mode.round_policy.test_profile,
            seats=[(seat_key, None) for seat_key in seat_keys_for_mode(mode)],
            lobby_issuer=None,
            return_url=None,
            graphql_url=None,
            service_token=None,
        )
        self._ensure_session(match, mode)
        return match

    async def claim_open_seat(
        self,
        external_match_id: str,
        *,
        display_name: str,
        seat_key: str | None = None,
    ) -> tuple[ClaimResult, MatchSession, Side]:
        """Standalone claim: take the named seat, or the first open one."""
        match = await self._repo.get_match(external_match_id)
        if match is None:
            raise NotFoundError("match not found")

        if seat_key is None:
            open_seat = next(
                (
                    s
                    for s in sorted(match.seats, key=lambda s: s.position)
                    if s.player_id is None and not s.reserved_for_lobby_user
                ),
                None,
            )
            if open_seat is None:
                raise ConflictError("no open seats")
            seat_key = open_seat.seat_key

        session = self._ensure_session(match, mode_or_default(match.game_mode))
        result = await self._repo.claim_seat(
            external_match_id=external_match_id,
            seat_key=seat_key,
            lobby_user_id=None,
            display_name=display_name,
        )
        side = self._seat_side(session, seat_key)
        live = session.seats[seat_key]
        live.player_id = result.seat.player_id
        live.display_name = display_name
        self._hub.publish(session.external_match_id, session)
        return result, session, side
