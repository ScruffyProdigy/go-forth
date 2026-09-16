"""The HTTP surface: every row of the integration checklist that is not realtime.

    GET  /healthz                                  liveness (in `main.py`)
    GET  /api/v1/status                            manifest.status
    GET  /api/v1/game-modes                        manifest.game_modes
    POST /api/v1/matches                           provision.*
    GET  /api/v1/matches/{ref}                     state, for a link preview
    POST /api/v1/matches/{ref}/claim               jwt.*, reclaim.*
    GET  /api/v1/resume                            recovery path 1
    GET  /api/v1/runs/{runId}                      a finished run's record
    GET  /api/v1/players/{lobbyUserId}/history     player history

Routes are thin on purpose. Everything with a rule in it lives in
`app/lobby/` or `app/service.py`, so the contract is tested without a client and
this file stays a map of which URL reaches which decision.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.config import Config
from app.lobby.launch_urls import build_launch_urls_for_assignment, build_return_url
from app.lobby.manifest import build_game_modes_payload, build_status_payload
from app.lobby.provision import (
    ProvisionError,
    bearer_token,
    parse_lobby_provision,
    verify_provision_auth,
)
from app.lobby.seat_binding import (
    SEAT_BINDING_COOKIE,
    SeatBinding,
    clear_seat_binding_cookie,
    decode_seat_binding,
    seat_binding_cookie,
)
from app.lobby.tokens import SeatTokenVerifier, TokenError
from app.repository import ConflictError, NotFoundError, ReservationError, StoredMatch
from app.service import BannedPlayerError, GameService, ValidationError

log = logging.getLogger(__name__)


def match_json(match: StoredMatch) -> dict[str, Any]:
    """The match as a caller outside the game sees it. No battle state."""
    return {
        "matchId": match.external_match_id,
        "runId": match.run_id,
        "gameMode": match.game_mode,
        "status": match.status,
        "testProfile": match.test_profile,
        "seats": [
            {
                "seatKey": seat.seat_key,
                "reservedForLobbyUser": seat.reserved_for_lobby_user,
                "player": (
                    {"playerId": seat.player_id, "name": seat.player_name} if seat.player_id else None
                ),
            }
            for seat in sorted(match.seats, key=lambda seat: seat.position)
        ],
    }


def create_router(
    service: GameService,
    config: Config,
    verifier: SeatTokenVerifier,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return build_status_payload(app_env=config.app_env, standalone=not config.require_lobby_auth)

    @router.get("/game-modes")
    async def game_modes() -> dict[str, Any]:
        return build_game_modes_payload()

    @router.post("/matches")
    async def create_match(request: Request) -> Response:
        body = await _json_body(request)

        if not isinstance(body, dict) or "assignment" not in body:
            # Standalone: no Lobby, no token, self-serve. The v1 mode that makes
            # a fresh checkout playable.
            if config.require_lobby_auth:
                return JSONResponse({"error": "lobby provision required"}, status_code=401)
            match = await service.create_standalone_match(
                game_mode=body.get("gameMode") if isinstance(body, dict) else None
            )
            return JSONResponse(match_json(match), status_code=201)

        try:
            provision = parse_lobby_provision(body)
        except ProvisionError as err:
            return JSONResponse({"error": str(err)}, status_code=400)

        auth_error = verify_provision_auth(
            request.headers.get("authorization"), provision.lobby.service_token
        )
        if auth_error:
            return JSONResponse({"error": auth_error}, status_code=401)

        try:
            match = await service.ensure_match_from_assignment(provision)
        except BannedPlayerError as err:
            # The exact shape Lobby parses to re-matchmake without these players.
            return JSONResponse(
                {"error": str(err), "bannedLobbyUserIds": err.banned_lobby_user_ids},
                status_code=403,
            )

        launch_urls = build_launch_urls_for_assignment(config.play_url, provision.assignment)
        log.info(
            "provision.launch_urls externalMatchId=%s gameMode=%s seats=%d urls=%d",
            provision.assignment.external_match_id,
            provision.assignment.game_mode,
            len(provision.assignment.seats),
            len(launch_urls),
        )
        return JSONResponse({**match_json(match), "launchUrls": launch_urls}, status_code=201)

    @router.get("/matches/{ref}")
    async def get_match(ref: str) -> Response:
        match = await service.get_match(ref)
        if match is None:
            return JSONResponse({"error": "match not found"}, status_code=404)
        return JSONResponse(match_json(match))

    @router.post("/matches/{ref}/claim")
    async def claim(ref: str, request: Request) -> Response:
        body = await _json_body(request)
        player_name = body.get("playerName") if isinstance(body, dict) else None
        token = bearer_token(request.headers.get("authorization"))

        if token is None:
            if config.require_lobby_auth:
                return JSONResponse({"error": "lobby token required"}, status_code=401)
            try:
                result, session, side = await service.claim_open_seat(
                    ref,
                    display_name=(player_name or "Challenger").strip() or "Challenger",
                    seat_key=body.get("seatKey") if isinstance(body, dict) else None,
                )
            except NotFoundError as err:
                return JSONResponse({"error": str(err)}, status_code=404)
            except ConflictError as err:
                return JSONResponse({"error": str(err)}, status_code=409)
        else:
            try:
                claims = await verifier.verify(token)
            except TokenError as err:
                return JSONResponse({"error": str(err)}, status_code=401)

            # The URL and the token must name the same match. Without this a
            # valid token for match A opens a seat in match B — the checklist's
            # `jwt.unknown_match` row, and the one failure here that is a real
            # security hole rather than an inconvenience.
            if ref != claims.external_match_id:
                return JSONResponse({"error": "match not found"}, status_code=404)

            try:
                result, session, side = await service.claim_with_lobby_token(claims, player_name=player_name)
            except NotFoundError as err:
                return JSONResponse({"error": str(err)}, status_code=404)
            except ReservationError as err:
                return JSONResponse({"error": str(err)}, status_code=403)
            except ConflictError as err:
                # Someone else holds this seat. 409 and not 403: the seat exists
                # and is legitimately reserved for the token's `sub`, it is just
                # occupied — which is the `jwt.reclaim_seat_theft` row.
                return JSONResponse({"error": str(err)}, status_code=409)

        service.start_clock(session)

        payload = {
            **match_json(result.match),
            "you": {
                "playerId": result.seat.player_id,
                "seatKey": result.seat.seat_key,
                "side": side,
                "name": result.seat.player_name,
            },
            "reclaimed": result.reclaimed,
            "returnUrl": (
                build_return_url(result.match.return_url, result.match.external_match_id)
                if result.match.return_url
                else None
            ),
        }

        # 200 for a re-claim, 201 for a first sitting: the player who already
        # holds this seat is reconnecting, and nothing was created for them.
        response = JSONResponse(payload, status_code=200 if result.reclaimed else 201)
        if result.seat.player_id:
            response.headers["Set-Cookie"] = seat_binding_cookie(
                SeatBinding(
                    external_match_id=result.match.external_match_id,
                    seat_key=result.seat.seat_key,
                    lobby_user_id=result.seat.lobby_user_id or "",
                    player_id=result.seat.player_id,
                ),
                secure=config.cookie_secure,
            )
        return response

    @router.get("/resume")
    async def resume(request: Request) -> Response:
        """Recovery path 1: this browser's own binding, no token, no Lobby call."""
        binding = decode_seat_binding(request.cookies.get(SEAT_BINDING_COOKIE))
        if binding is None:
            return JSONResponse({"error": "no seat binding"}, status_code=404)

        resumed = await service.resume_from_binding(binding)
        if resumed is None:
            response = JSONResponse({"error": "no resumable seat"}, status_code=404)
            response.headers["Set-Cookie"] = clear_seat_binding_cookie(secure=config.cookie_secure)
            return response

        session, side = resumed
        match = await service.get_match(session.external_match_id)
        return JSONResponse(
            {
                "matchId": session.external_match_id,
                "runId": session.run_id,
                "you": {
                    "playerId": binding.player_id,
                    "seatKey": binding.seat_key,
                    "side": side,
                },
                "state": session.snapshot_for(side),
                # A match that is already over still resumes (JQ-310), so the
                # answer has to say so rather than leaving a client to infer it
                # from the phase. `returnUrl` rides along because the one thing
                # a player wants on a terminal reconnect is the way back to the
                # Lobby, and a result screen with no exit is where the demo ends
                # for them.
                "over": session.over,
                "returnUrl": (
                    build_return_url(match.return_url, match.external_match_id)
                    if match is not None and match.return_url
                    else None
                ),
            }
        )

    @router.get("/runs/{run_id}")
    async def run_record(run_id: str) -> Response:
        """A finished run's record: what it was played under, and what happened.

        Read-only, and only for runs that are over — `persist_run_record` writes
        nothing until then, so a match in progress is a 404 here rather than a
        way to read the opponent's plan before the reveal.

        Carries no credentials: no `playerId`, no Lobby token, no return URL.
        `app/match/run_record.py` says what is in one and why.

        Unauthenticated, and the run id is what stands in for a secret: it is 64
        bits from `secrets.token_hex`, minted per provision, and never shown to
        anyone outside the match. That is a deliberately modest claim — what a
        guessed id would reveal is two plans and a list of spells from a match
        that is already over, which is what both players watched happen. The
        things worth protecting are the hidden plan *before* the reveal, which
        is why nothing is written until the match is finished, and the seat
        credential, which is not in the document at all.
        """
        stored = await service.run_record(run_id)
        if stored is None:
            return JSONResponse({"error": "run not found"}, status_code=404)
        return JSONResponse(stored)

    @router.get("/players/{lobby_user_id}/history")
    async def history(lobby_user_id: str, limit: int = 20) -> dict[str, Any]:
        """What this person has played, keyed by their Lobby user id.

        Not a leaderboard and deliberately not a rating: the guide asks games not
        to show players a skill number, so nothing here carries one.
        """
        rows = await service.history_for(lobby_user_id, max(1, min(limit, 100)))
        return {
            "lobbyUserId": lobby_user_id,
            "results": [
                {
                    "matchId": row.match_id,
                    "seatKey": row.seat_key,
                    "side": row.side,
                    "ending": row.ending,
                    "won": row.won,
                    "roundsWon": row.rounds_won,
                    "baseHp": row.base_hp,
                    "testProfile": row.test_profile,
                    "at": row.created_at.isoformat(),
                }
                for row in rows
            ],
        }

    return router


async def _json_body(request: Request) -> Any:
    """The parsed body, or `{}`. A malformed body is not a crash.

    Lobby and the dashboard checks both send bodies this server did not write,
    and an unparseable one should reach the route's own validation — which
    answers 400 with a reason — rather than FastAPI's generic handler.
    """
    try:
        return await request.json()
    except Exception:
        return {}


__all__ = ["ValidationError", "create_router", "match_json"]
