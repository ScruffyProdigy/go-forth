"""The realtime transport: authoritative state out, seat commands in.

    GET /api/v1/ws   (WebSocket upgrade)

## Client → server

    {"type": "subscribe", "matchId": "...", "playerId": "..."}
        Take a seat on this socket and start receiving state. `playerId` is the
        credential a claim handed back; a socket without one may watch and may
        not act.
    {"type": "lockIn", "plan": { ... }}
        Submit this seat's plan for the round. Answered with `planRejected` and
        a reason, or by the next state push.
    {"type": "cast", "cast": {"commandId", "spellId", "at": {"x","y"}, "tick"}}
        Ask for a cast. Answered with exactly one `castOutcome`.
    {"type": "ping"}

## Server → client

    {"type": "state", "state": { ...MatchSnapshot }}   on subscribe and on change
    {"type": "castOutcome", "outcome": "accepted"|"rejected", "commandId", "reason"}
    {"type": "planRejected", "reason": "..."}
    {"type": "claimFailed", "reason": "...", "retryable": bool}
    {"type": "error", "error": "..."}
    {"type": "pong"}

## Two rules this file exists to hold

**A socket acts only for the seat it holds.** Nothing a client sends names a
side. `side` comes from `playerId` → seat → side, resolved once on subscribe,
because a client that could name its own side could cast as its opponent.

**A dropped socket is not a player who left.** The battle runs on, the seat is
held, and the player is expected back (integration guide §6). Closing a socket
therefore clears presence and nothing else — it never forfeits, never fills the
seat, and never reports the player finished to the Lobby.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import Config
from app.match import wire
from app.match.plan import PlanError
from app.match.session import MatchSession
from app.match.wire import CommandError, parse_cast_command
from app.service import GameService
from app.sim.types import Side

log = logging.getLogger(__name__)

WS_PATH = "/api/v1/ws"


class SeatConnection:
    """One socket, and the seat it is acting for."""

    def __init__(self, websocket: WebSocket, service: GameService) -> None:
        self._ws = websocket
        self._service = service
        self._session: MatchSession | None = None
        self._side: Side | None = None
        self._unsubscribe: Callable[[], None] | None = None
        #: The in-flight state push. Held only so the event loop does not
        #: garbage-collect a running task; see `_on_publish`.
        self._pending: asyncio.Task[None] | None = None

    async def send(self, message: dict[str, Any]) -> None:
        if self._ws.client_state is not WebSocketState.CONNECTED:
            return
        try:
            await self._ws.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            # The socket went away between the check and the send. Ordinary, and
            # not this connection's job to report anywhere.
            return

    async def push_state(self) -> None:
        if self._session is None or self._side is None:
            return
        await self.send(wire.state_message(self._session.snapshot_for(self._side)))

    async def subscribe(self, message: dict[str, Any]) -> None:
        match_id = message.get("matchId")
        player_id = message.get("playerId")
        if not isinstance(match_id, str) or not match_id.strip():
            await self.send(wire.error_message("matchId is required"))
            return

        session = self._service.session(match_id.strip())
        if session is None:
            # Retryable: a socket can legitimately arrive before provision has
            # been processed, and telling the client to give up would strand a
            # player whose only fault was being quick.
            await self.send(wire.claim_failed_message("match not found", retryable=True))
            return

        if not isinstance(player_id, str) or not player_id.strip():
            await self.send(wire.claim_failed_message("claim a seat before subscribing", retryable=False))
            return

        seat = session.seat_for_player(player_id.strip())
        if seat is None:
            # Not retryable: this credential does not hold a seat in this match,
            # and no amount of retrying will change that.
            await self.send(wire.claim_failed_message("that seat is not yours", retryable=False))
            return

        self._release()
        self._session = session
        self._side = seat.side
        seat.connected = True

        self._unsubscribe = self._service.hub.subscribe(match_id.strip(), self._on_publish)
        await self.push_state()

    def _on_publish(self, session: MatchSession) -> None:
        """Hub callbacks are synchronous; the send is not.

        Scheduled rather than awaited, so a slow socket cannot hold up the tick
        loop that published to it. The task is fire-and-forget by design: what
        it would report is that one client is behind, which the next push
        corrects anyway.
        """
        if self._session is None or session is not self._session:
            return
        self._pending = asyncio.create_task(self.push_state())
        self._pending.add_done_callback(self._forget_pending)

    async def handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")

        if kind == "subscribe":
            await self.subscribe(message)
            return

        if kind == "ping":
            await self.send({"type": "pong"})
            return

        if self._session is None or self._side is None:
            await self.send(wire.error_message("subscribe before acting"))
            return

        if kind == "lockIn":
            try:
                self._session.lock_in(self._side, message.get("plan"))
            except PlanError as err:
                await self.send({"type": "planRejected", "reason": str(err)})
                return
            self._service.start_clock(self._session)
            self._service.hub.publish(self._session.external_match_id, self._session)
            return

        if kind == "cast":
            try:
                command = parse_cast_command(message.get("cast"))
            except CommandError as err:
                await self.send(wire.error_message(str(err)))
                return
            outcome = self._session.cast(self._side, command)
            await self.send(outcome)
            if outcome.get("outcome") == "accepted":
                # Only an accepted cast changes shared state, so only an accepted
                # one is worth waking the other seat for.
                self._service.hub.publish(self._session.external_match_id, self._session)
            return

        await self.send(wire.error_message(f"unknown message type: {kind!r}"))

    def _forget_pending(self, task: asyncio.Task[None]) -> None:
        if self._pending is task:
            self._pending = None

    def _release(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def close(self) -> None:
        """Clear presence. **Does not** end the match or free the seat."""
        self._release()
        if self._session is not None and self._side is not None:
            self._session.seat_for_side(self._side).connected = False
        self._session = None
        self._side = None


async def websocket_endpoint(websocket: WebSocket, service: GameService, config: Config) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in config.cors_allowed_origins:
        # Same origin policy as the REST CORS. Browsers send `Origin`; tools and
        # the test client may not, and a missing header is not a cross-origin
        # request.
        await websocket.close(code=1008)
        return

    await websocket.accept()
    connection = SeatConnection(websocket, service)
    try:
        while True:
            try:
                message = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError:
                await connection.send(wire.error_message("invalid JSON"))
                continue

            if not isinstance(message, dict):
                await connection.send(wire.error_message("a message must be an object"))
                continue

            try:
                await connection.handle(message)
            except Exception:
                # One bad message must not take the socket down with it: the
                # player is mid-battle, and a dropped connection costs them the
                # round in a way a refused command does not.
                log.exception("[ws] failed to handle %r", message.get("type"))
                await connection.send(wire.error_message("that command could not be handled"))
    finally:
        connection.close()
