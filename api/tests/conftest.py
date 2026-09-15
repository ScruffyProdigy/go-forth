"""Shared fixtures for the contract and session suites.

Everything here builds an app with **no database and no live Lobby**: an
in-memory repository and a stub signer. That is not a shortcut — `api-tests.yml`
has no Postgres service, so a contract suite needing one would be a contract
suite nobody runs.

The battle is shortened rather than left at its 90-second default. A round that
takes 1800 ticks to reach `timeUp` is 1800 ticks whether a test steps them by
hand or a clock does, and the session rules under test are about transitions
rather than about how long a battle lasts.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.lobby.client import LobbyClient, MatchResultStatus, PlayerFinishReason
from app.lobby.tokens import AssignmentClaims, JwksKeyStore, JwksSeatTokenVerifier, TokenError
from app.main import create_app
from app.match.hub import MatchHub
from app.repository import MemoryRepository
from app.service import GameService
from app.sim.config import SimConfig
from tests.lobby.signing import StubLobby, stub_lobby

#: Six seconds of battle rather than ninety. Long enough for units to leave the
#: deployment strip, short enough that a whole match is 120 ticks.
TEST_SIM_CONFIG = SimConfig(max_battle_seconds=6)

BANNED_LOBBY_USER = "a0000000-0000-4000-8000-000000000099"


class FakeVerifier:
    """Accepts tokens of the form `seat:<user>:<match>:<seatKey>`.

    For tests about what happens *after* a valid claim. Anything about the token
    itself uses the real verifier against `StubLobby`, because a fake that
    accepted a wrongly-signed token would make the rows it is standing in for
    untestable.
    """

    def __init__(self) -> None:
        self.refuse: str | None = None

    async def verify(self, token: str) -> AssignmentClaims:
        if self.refuse is not None:
            raise TokenError(self.refuse)
        parts = token.split(":")
        if len(parts) != 4 or parts[0] != "seat":
            raise TokenError("invalid lobby token")
        _, lobby_user_id, match_id, seat_key = parts
        return AssignmentClaims(
            lobby_issuer="https://lobby.test",
            lobby_user_id=lobby_user_id,
            external_match_id=match_id,
            seat_key=seat_key,
        )


def fake_token(lobby_user_id: str, match_id: str, seat_key: str) -> str:
    return f"seat:{lobby_user_id}:{match_id}:{seat_key}"


class RecordingLobby(LobbyClient):
    """A `LobbyClient` stand-in that records what it was told.

    A real subclass rather than a duck-typed stand-in, so `mypy --strict` checks
    every call site against the interface the production code actually holds. A
    structural fake would let a signature drift here and there independently.
    """

    def __init__(self, graphql_url: str = "https://lobby.test", service_token: str | None = None) -> None:
        super().__init__(graphql_url, service_token, transport=self._unused)
        self.graphql_url = graphql_url
        self.service_token = service_token
        self.results: list[tuple[str, str, list[str], dict[str, Any]]] = []
        self.finished: list[tuple[str, str, str]] = []
        self.display_names: dict[str, str] = {}
        #: Set to fail the next report, for the retry test.
        self.fail_next = False

    @staticmethod
    async def _unused(url: str, headers: Mapping[str, str], payload: Mapping[str, Any]) -> Mapping[str, Any]:
        raise AssertionError("RecordingLobby overrides every call; the transport is never reached")

    async def report_match_result(
        self,
        match_id: str,
        status: MatchResultStatus,
        winner_lobby_user_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        if self.fail_next:
            self.fail_next = False
            return False
        self.results.append((match_id, status, list(winner_lobby_user_ids), dict(metadata or {})))
        return True

    async def report_player_finished(
        self,
        match_id: str,
        lobby_user_id: str,
        reason: PlayerFinishReason,
        placement: int | None = None,
    ) -> bool:
        self.finished.append((match_id, lobby_user_id, reason))
        return True

    async def fetch_display_name(self, lobby_user_id: str) -> str | None:
        return self.display_names.get(lobby_user_id)


@pytest.fixture
def repository() -> MemoryRepository:
    return MemoryRepository()


@pytest.fixture
def hub() -> MatchHub:
    return MatchHub()


@pytest.fixture
def lobby() -> RecordingLobby:
    return RecordingLobby()


@pytest.fixture
def service(repository: MemoryRepository, hub: MatchHub, lobby: RecordingLobby) -> GameService:
    return GameService(
        repository,
        hub,
        sim_config=TEST_SIM_CONFIG,
        banned_lobby_user_ids=(BANNED_LOBBY_USER,),
        # One recording client for every match in a test, so an assertion can
        # reach what was reported without digging it out of the session.
        lobby_client_factory=lambda url, token: lobby,
    )


@pytest.fixture
def verifier() -> FakeVerifier:
    return FakeVerifier()


@pytest.fixture
def config() -> Config:
    return Config.from_env({"GAME_IN_MEMORY": "1", "GAME_PLAY_URL": "https://go-forth.test/play"})


@pytest.fixture
def client(service: GameService, config: Config, verifier: FakeVerifier) -> Iterator[TestClient]:
    app = create_app(config, service=service, verifier=verifier)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signer() -> StubLobby:
    return stub_lobby()


@pytest.fixture
def real_verifier(signer: StubLobby) -> JwksSeatTokenVerifier:
    """The production verifier, pointed at the stub's JWKS instead of the network."""
    return JwksSeatTokenVerifier(
        [signer.audience],
        key_store=JwksKeyStore(signer.fetch),
    )


def provision_body(
    *,
    external_match_id: str = "lobby-match-1",
    game_mode: str = "opening-round",
    seats: Any = None,
    service_token: str | None = None,
    lobby_id: str = "https://lobby.test",
) -> dict[str, Any]:
    """A Lobby push, in the shape Lobby actually sends one."""
    lobby: dict[str, Any] = {
        "returnUrl": "https://joinquest.test/return",
        "graphqlUrl": "https://lobby.test/graphql",
    }
    if service_token:
        lobby["serviceToken"] = service_token
    return {
        "lobbyId": lobby_id,
        "lobby": lobby,
        "assignment": {
            "externalMatchId": external_match_id,
            "gameMode": game_mode,
            "seats": seats
            if seats is not None
            else [
                {"seatKey": "1", "lobbyUserId": "user-north", "player": {"displayName": "North"}},
                {"seatKey": "2", "lobbyUserId": "user-south", "player": {"displayName": "South"}},
            ],
        },
    }
