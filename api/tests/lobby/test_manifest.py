"""Integration guide §8, the **Manifest** row.

    launchUrlsOnProvision: true; valid seatTemplate; expanded seatKey list

rpslr covers the same ground in `app.test.ts` and `gameModes.test.ts`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.lobby.manifest import (
    GAME_MODES,
    OPENING_ROUND,
    STARTER,
    get_game_mode,
    mode_or_default,
    seat_keys_for_mode,
)


def test_healthz_is_dependency_free(client: TestClient) -> None:
    # No database in this app at all, so a 200 here is evidence rather than
    # coincidence: a health check that touched one could not pass.
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_status_declares_launch_urls_on_provision(client: TestClient) -> None:
    body = client.get("/api/v1/status").json()
    assert body["launchUrlsOnProvision"] is True
    assert body["game"] == "go-forth"
    assert body["version"]


def test_game_modes_use_a_count_seat_template(client: TestClient) -> None:
    modes = client.get("/api/v1/game-modes").json()["modes"]
    assert modes, "the catalog sync reads this; an empty list is an unjoinable game"
    for mode in modes:
        # Flat `seats[]` arrays are rejected by Lobby outright (§4).
        assert mode["seatTemplate"] == {"count": 2}
        assert mode["minPlayers"] == 2
        assert mode["maxPlayers"] == 2
        assert mode["socialMode"] == "1v1"
        assert 1 <= mode["typicalMinutes"] <= 1440


def test_both_modes_are_published() -> None:
    keys = [mode.key for mode in GAME_MODES]
    assert keys == ["starter", "opening-round"]


def test_the_demo_is_a_test_profile_and_starter_is_not() -> None:
    assert OPENING_ROUND.round_policy.test_profile is True
    assert OPENING_ROUND.round_policy.rounds_to_win == 1
    # The production rule: first to three round wins (Ryan, 2026-09-13).
    assert STARTER.round_policy.test_profile is False
    assert STARTER.round_policy.rounds_to_win == 3


def test_seat_keys_match_lobbys_expansion() -> None:
    # Lobby numbers expanded seats from one, and so does rpslr. A game that
    # invented its own keys would reject every token Lobby minted.
    assert seat_keys_for_mode(OPENING_ROUND) == ("1", "2")


def test_an_unknown_mode_falls_back_to_the_demo() -> None:
    assert get_game_mode("no-such-mode") is None
    # Not Starter: a mode we did not recognise is not one to report a rated
    # best-of-five for.
    assert mode_or_default("no-such-mode").key == "opening-round"
    assert mode_or_default(None).key == "opening-round"
    assert mode_or_default("starter").key == "starter"
