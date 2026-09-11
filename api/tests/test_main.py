"""The only endpoint this scaffold serves.

Provisioning, JWT claim, game-modes and ranked results are JQ-188.
"""

from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


def test_healthz_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_healthz_touches_nothing() -> None:
    # Kubernetes probes and the JoinQuest integration checks both read this, so
    # it must stay dependency-free. Pointing the config at a database that
    # cannot exist proves the handler never reaches for one: if it did, this
    # would raise rather than return 200.
    config = Config.from_env({"DATABASE_URL": "postgres://nobody@127.0.0.1:1/nothing"})
    client = TestClient(create_app(config))
    assert client.get("/healthz").status_code == 200


def test_cors_headers_follow_the_config() -> None:
    config = Config.from_env({"CORS_ALLOWED_ORIGINS": "https://allowed.test"})
    client = TestClient(create_app(config))

    allowed = client.get("/healthz", headers={"Origin": "https://allowed.test"})
    assert allowed.headers["access-control-allow-origin"] == "https://allowed.test"

    denied = client.get("/healthz", headers={"Origin": "https://denied.test"})
    assert "access-control-allow-origin" not in denied.headers
