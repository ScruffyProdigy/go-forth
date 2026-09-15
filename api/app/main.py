"""The FastAPI application.

Built by a factory rather than as a module-level singleton so tests can drive
it with a config of their choosing, and so `server.py` stays a short entry
point. This mirrors how `app.ts` split from `server.ts` in the TypeScript.

The factory also takes its `service` and `verifier` as arguments (JQ-309). That
is what lets the whole contract suite run with an in-memory repository and a
fake token signer — no Postgres, no live Lobby JWKS — which is what CI actually
has. Passing nothing gives the real thing.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.config import Config
from app.lobby.manifest import GAME_VERSION
from app.lobby.tokens import SeatTokenVerifier, create_seat_token_verifier
from app.match.hub import MatchHub
from app.repository import MemoryRepository, Repository
from app.routes import create_router
from app.service import GameService
from app.ws import WS_PATH, websocket_endpoint

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

log = logging.getLogger(__name__)


def build_repository(config: Config) -> Repository:
    """Postgres, unless the config asks to run without one.

    `GAME_IN_MEMORY=1` is the switch that makes a fresh checkout playable with
    nothing installed but Python — the first thing anyone reading a reference
    implementation tries, and the thing they give up at if it needs a database.
    """
    if config.in_memory:
        return MemoryRepository()
    from app.pg_repository import PgRepository

    return PgRepository(config.database_url)


def create_app(
    config: Config | None = None,
    *,
    service: GameService | None = None,
    verifier: SeatTokenVerifier | None = None,
) -> FastAPI:
    config = config or Config.from_env()

    hub = MatchHub()
    game = service or GameService(
        build_repository(config),
        hub,
        banned_lobby_user_ids=config.banned_lobby_user_ids,
    )
    seat_verifier = verifier or create_seat_token_verifier(config.token_audiences)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # Every live match has a tick loop behind it. Cancelling them on the way
        # down is what stops a reload leaving orphaned tasks stepping sims that
        # nothing is listening to any more.
        await game.shutdown()

    app = FastAPI(
        title="Go Forth! API",
        description="A JoinQuest game API — the Python reference implementation.",
        version=GAME_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
    async def healthz() -> str:
        """Liveness.

        Kubernetes probes and the JoinQuest integration checks both read this,
        so it must stay dependency-free — no database, no outbound calls. A
        health check that touches the database reports the database's health,
        which is a different question and takes the API down with it.
        """
        return "ok"

    app.include_router(create_router(game, config, seat_verifier))

    @app.websocket(WS_PATH)
    async def ws(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket, game, config)

    # Reachable from the app so tests can drive the session without importing
    # the factory's internals, and so `server.py` could add a retry sweep later.
    app.state.service = game
    app.state.hub = hub
    app.state.config = config
    return app


def app_state(app: FastAPI) -> dict[str, Any]:  # pragma: no cover - convenience
    return {"service": app.state.service, "hub": app.state.hub, "config": app.state.config}
