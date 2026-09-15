"""Parsing and authorising Lobby's `POST /api/v1/matches` push.

Lobby runs matchmaking and then pushes the finished seat map at the game. The
game does not choose who plays; it decides whether it will host them.

Everything here is a pure function over a parsed body. Nothing touches a
database, so the shape of the contract is testable without one — which is the
half of this contract that actually breaks, and the half CI can afford to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ProvisionError(Exception):
    """A malformed push. Always a 400: Lobby sent something we cannot read."""


@dataclass(frozen=True, slots=True)
class LobbySkill:
    """Lobby's per-mode skill estimate for a seated player (§15).

    Read and carried so the session can size a match, never rendered: the guide
    asks games not to show a player their own rating, and the surest way to
    honour that is for the client wire schema not to carry the field at all.
    """

    rating: float
    uncertainty: float


@dataclass(frozen=True, slots=True)
class AssignmentSeat:
    seat_key: str
    lobby_user_id: str
    team: str | None = None
    role: str | None = None
    display_name: str | None = None
    skill: LobbySkill | None = None


@dataclass(frozen=True, slots=True)
class LobbyEndpoints:
    """Where to reach the Lobby that sent this push. Never hardcoded per env."""

    return_url: str
    graphql_url: str
    #: Per-match Bearer from the dashboard. Absent in local dev, which is what
    #: makes the stub Lobby usable without minting one.
    service_token: str | None = None


@dataclass(frozen=True, slots=True)
class Assignment:
    external_match_id: str
    game_mode: str
    seats: tuple[AssignmentSeat, ...]
    best_of: int | None = None


@dataclass(frozen=True, slots=True)
class LobbyProvision:
    lobby_id: str
    lobby: LobbyEndpoints
    assignment: Assignment
    #: Every seated player, in seat order. Convenience for the banlist check.
    lobby_user_ids: tuple[str, ...] = field(default=())


def _text(raw: Any) -> str:
    return raw.strip() if isinstance(raw, str) else ""


def _parse_skill(raw: Any) -> LobbySkill | None:
    if not isinstance(raw, dict):
        return None
    rating = raw.get("rating")
    uncertainty = raw.get("uncertainty")
    if not isinstance(rating, int | float) or not isinstance(uncertainty, int | float):
        return None
    if isinstance(rating, bool) or isinstance(uncertainty, bool):
        return None
    return LobbySkill(rating=float(rating), uncertainty=float(uncertainty))


def _parse_endpoints(raw: Any) -> LobbyEndpoints:
    if not isinstance(raw, dict):
        raise ProvisionError("lobby is required")
    return_url = _text(raw.get("returnUrl"))
    graphql_url = _text(raw.get("graphqlUrl"))
    if not return_url:
        raise ProvisionError("lobby.returnUrl is required")
    if not graphql_url:
        raise ProvisionError("lobby.graphqlUrl is required")
    return LobbyEndpoints(
        return_url=return_url,
        graphql_url=graphql_url,
        service_token=_text(raw.get("serviceToken")) or None,
    )


def _parse_seat(raw: Any) -> AssignmentSeat:
    if not isinstance(raw, dict):
        raise ProvisionError("each assignment.seats entry must be an object")
    seat_key = _text(raw.get("seatKey"))
    lobby_user_id = _text(raw.get("lobbyUserId"))
    if not seat_key:
        raise ProvisionError("each seat requires seatKey")
    if not lobby_user_id:
        raise ProvisionError("each seat requires lobbyUserId")

    player = raw.get("player")
    display_name = _text(player.get("displayName")) if isinstance(player, dict) else ""

    return AssignmentSeat(
        seat_key=seat_key,
        lobby_user_id=lobby_user_id,
        team=_text(raw.get("team")) or None,
        role=_text(raw.get("role")) or None,
        display_name=display_name or None,
        skill=_parse_skill(raw.get("skill")),
    )


def parse_lobby_provision(body: Any) -> LobbyProvision:
    """Read a Lobby push, or raise `ProvisionError` naming the first thing wrong.

    Raising rather than returning a union is the one place this deliberately
    reads unlike rpslr, which returns `Input | string` because TypeScript has no
    cheap exceptions. The contract is identical; only the error channel differs.
    See `docs/python-vs-typescript.md`.
    """
    if not isinstance(body, dict):
        raise ProvisionError("request body is required")

    lobby_id = _text(body.get("lobbyId"))
    if not lobby_id:
        raise ProvisionError("lobbyId is required")

    lobby = _parse_endpoints(body.get("lobby"))

    assignment = body.get("assignment")
    if not isinstance(assignment, dict):
        raise ProvisionError("assignment is required")

    external_match_id = _text(assignment.get("externalMatchId"))
    game_mode = _text(assignment.get("gameMode"))
    if not external_match_id:
        raise ProvisionError("assignment.externalMatchId is required")
    if not game_mode:
        raise ProvisionError("assignment.gameMode is required")

    raw_seats = assignment.get("seats")
    if not isinstance(raw_seats, list) or not raw_seats:
        raise ProvisionError("assignment.seats must be a non-empty array")
    seats = tuple(_parse_seat(row) for row in raw_seats)

    seen: set[str] = set()
    for seat in seats:
        if seat.seat_key in seen:
            raise ProvisionError(f"assignment.seats repeats seatKey {seat.seat_key}")
        seen.add(seat.seat_key)

    best_of: int | None = None
    raw_best_of = assignment.get("bestOf")
    if raw_best_of is not None:
        if isinstance(raw_best_of, bool) or not isinstance(raw_best_of, int | float):
            raise ProvisionError("assignment.bestOf must be a number")
        best_of = int(raw_best_of)

    return LobbyProvision(
        lobby_id=lobby_id,
        lobby=lobby,
        assignment=Assignment(
            external_match_id=external_match_id,
            game_mode=game_mode,
            seats=seats,
            best_of=best_of,
        ),
        lobby_user_ids=tuple(seat.lobby_user_id for seat in seats),
    )


def bearer_token(authorization: str | None) -> str | None:
    """The token out of an `Authorization: Bearer ...` header, if there is one."""
    header = (authorization or "").strip()
    if len(header) < 7 or header[:7].lower() != "bearer ":
        return None
    return header[7:].strip() or None


def verify_provision_auth(authorization: str | None, service_token: str | None) -> str | None:
    """The reason to refuse this push, or None to accept it.

    When provision carries no `serviceToken` — the local-dev and stub-Lobby
    case — no auth is required. When it carries one, the header must match it
    exactly. That is rpslr's rule, and the checklist's `provision.auth` and
    `provision.missing_auth` rows are the two halves of it.
    """
    expected = (service_token or "").strip()
    if not expected:
        return None
    got = bearer_token(authorization)
    if not got or got != expected:
        return "provision requires Authorization: Bearer matching lobby.serviceToken"
    return None
