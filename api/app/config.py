"""Process configuration, read from the environment.

Everything here has a working default, so a clean checkout runs without a
`.env`. `.env.example` documents the same names and is the file to keep in
step when one is added.

`Config.from_env` takes the environment as an argument rather than reaching for
`os.environ` itself, which is what lets the tests state the contract directly
instead of monkeypatching global state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

from dotenv import load_dotenv

#: Offset from rpslr's 3001 and the Lobby's 8080 so all three can run at once.
DEFAULT_API_PORT = 3002

#: Where a player's browser reaches this game's client. Launch URLs are built
#: on it, so it is the game's *public* address rather than the API's.
DEFAULT_PLAY_URL = "http://localhost:5175"

#: The Lobby's dev origin (5173) and this game's own client (5175).
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
)

_DEFAULT_POSTGRES = {
    "POSTGRES_USER": "goforth",
    "POSTGRES_PASSWORD": "goforth_dev_password",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5434",
    "POSTGRES_DB": "go_forth",
}


def _read_port(env: Mapping[str, str]) -> int:
    raw = env.get("API_PORT")
    if not raw:
        return DEFAULT_API_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f'API_PORT must be a port number between 1 and 65535, got "{raw}"') from None
    if not 1 <= port <= 65535:
        raise ValueError(f'API_PORT must be a port number between 1 and 65535, got "{raw}"')
    return port


def _read_cors_origins(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = env.get("CORS_ALLOWED_ORIGINS")
    if not raw:
        return DEFAULT_CORS_ORIGINS
    origins = tuple(part.strip() for part in raw.split(",") if part.strip())
    # A value of " , , " parses to nothing. Zero allowed origins would block
    # every browser request, so the defaults are the safer reading.
    return origins or DEFAULT_CORS_ORIGINS


def _flag(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _read_database_url(env: Mapping[str, str]) -> str:
    """The DSN, either given whole or assembled from the `POSTGRES_*` parts.

    `DATABASE_URL` wins when set, because that is the only form Kubernetes
    passes — the deployment mounts one secret key, not five. Locally the parts
    are what `.env` and `docker-compose.yml` share, so assembling them keeps
    `POSTGRES_PORT` the single place the port is written down.
    """
    explicit = env.get("DATABASE_URL", "").strip()
    if explicit:
        return explicit

    def part(name: str) -> str:
        return env.get(name) or _DEFAULT_POSTGRES[name]

    # The credentials are percent-encoded; a password containing '@' or '/'
    # would otherwise produce a DSN quietly pointing at a different host.
    user = quote(part("POSTGRES_USER"), safe="")
    password = quote(part("POSTGRES_PASSWORD"), safe="")
    host = part("POSTGRES_HOST")
    port = part("POSTGRES_PORT")
    database = part("POSTGRES_DB")
    return f"postgres://{user}:{password}@{host}:{port}/{database}"


def _read_play_url(env: Mapping[str, str]) -> str:
    return (env.get("GAME_PLAY_URL") or "").strip() or DEFAULT_PLAY_URL


def _read_token_audiences(env: Mapping[str, str]) -> tuple[str, ...]:
    """What a seat token's `aud` must be: this API's own origin(s).

    Empty means "do not check the audience", which is the local-dev default —
    the stub Lobby mints `aud` from whatever port it was told about, and a
    developer who has not set this should not be debugging an audience mismatch
    before the game has ever run. Every deployed environment sets it.
    """
    raw = env.get("GAME_API_AUDIENCE", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _read_banned(env: Mapping[str, str]) -> tuple[str, ...]:
    """Lobby user ids this game refuses to host.

    Read from the environment rather than a table because it is also how the
    integration checklist is exercised: `provision.banlist` wants a 403 for a
    specific test user, and an env var is a thing a dashboard run can set and
    unset without a migration.
    """
    raw = env.get("GAME_BANNED_LOBBY_USER_IDS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Config:
    api_port: int
    cors_allowed_origins: tuple[str, ...]
    database_url: str
    #: Base for the per-player launch URLs returned from provision.
    play_url: str = DEFAULT_PLAY_URL
    app_env: str = "local"
    #: Accepted `aud` values on a seat token. Empty disables the check.
    token_audiences: tuple[str, ...] = ()
    banned_lobby_user_ids: tuple[str, ...] = ()
    #: Whether a seat token is required to claim. False is standalone mode: the
    #: game is playable with no platform in front of it, which is the first
    #: thing anyone reading a reference implementation tries.
    require_lobby_auth: bool = False
    #: `Secure` on the seat-binding cookie. Off over plain-HTTP localhost, or
    #: the browser discards the cookie and recovery path 1 silently never works.
    cookie_secure: bool = False
    #: Run without a database. The session layer holds live state in memory
    #: anyway; this drops the persistence half so a checkout runs with nothing
    #: installed but Python.
    in_memory: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """Build a config from `env`, defaulting to the process environment.

        When no mapping is given the local `.env` is loaded first, mirroring
        what `import 'dotenv/config'` did in the TypeScript. Passing a mapping
        explicitly skips that, so a caller — a test, above all — gets exactly
        the environment it asked for.
        """
        if env is None:
            load_dotenv()
            import os

            env = os.environ

        app_env = (env.get("GAME_APP_ENV") or "local").strip() or "local"
        return cls(
            api_port=_read_port(env),
            cors_allowed_origins=_read_cors_origins(env),
            database_url=_read_database_url(env),
            play_url=_read_play_url(env),
            app_env=app_env,
            token_audiences=_read_token_audiences(env),
            banned_lobby_user_ids=_read_banned(env),
            require_lobby_auth=_flag(env, "GAME_REQUIRE_LOBBY_AUTH", default=False),
            # Defaults on anywhere but local: every deployed environment is
            # HTTPS, and the failure mode of getting this wrong in production is
            # a cookie sent in the clear.
            cookie_secure=_flag(env, "GAME_COOKIE_SECURE", default=app_env != "local"),
            in_memory=_flag(env, "GAME_IN_MEMORY", default=False),
        )
