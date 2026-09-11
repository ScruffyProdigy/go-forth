"""The FastAPI application.

Built by a factory rather than as a module-level singleton so tests can drive
it with a config of their choosing, and so `server.py` stays a short entry
point. This mirrors how `app.ts` split from `server.ts` in the TypeScript.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.config import Config


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.from_env()

    app = FastAPI(
        title="Go Forth! API",
        description="A JoinQuest game API — the Python reference implementation.",
        version="0.1.0",
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

    return app
