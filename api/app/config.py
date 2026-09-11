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


@dataclass(frozen=True, slots=True)
class Config:
    api_port: int
    cors_allowed_origins: tuple[str, ...]
    database_url: str

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

        return cls(
            api_port=_read_port(env),
            cors_allowed_origins=_read_cors_origins(env),
            database_url=_read_database_url(env),
        )
