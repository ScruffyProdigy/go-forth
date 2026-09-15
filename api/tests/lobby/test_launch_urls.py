"""Integration guide §8, the **Launch URLs** row, and §11's `provision.launch_url_no_jwt`.

    Per-player URLs; no `token=` in bases

rpslr covers the same ground in `launchUrls.test.ts`.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app.lobby.launch_urls import build_launch_url, build_launch_urls_for_assignment, build_return_url
from app.lobby.provision import Assignment, AssignmentSeat
from tests.conftest import provision_body

PLAY_URL = "https://go-forth.test/play"


def _assignment(seats: list[tuple[str, str]]) -> Assignment:
    return Assignment(
        external_match_id="m-1",
        game_mode="opening-round",
        seats=tuple(AssignmentSeat(seat_key=key, lobby_user_id=user) for key, user in seats),
    )


def test_one_url_per_seated_player_keyed_by_lobby_user_id() -> None:
    urls = build_launch_urls_for_assignment(PLAY_URL, _assignment([("1", "north"), ("2", "south")]))
    assert set(urls) == {"north", "south"}

    query = parse_qs(urlsplit(urls["north"]).query)
    assert query["match"] == ["m-1"]
    assert query["seat"] == ["1"]


def test_a_base_never_carries_a_jwt() -> None:
    urls = build_launch_urls_for_assignment(PLAY_URL, _assignment([("1", "north")]))
    # Lobby appends `token=` when it links a player. A token minted at provision
    # time would be shared by whoever saw the URL and still valid long after the
    # player it was for had gone.
    assert "token" not in parse_qs(urlsplit(urls["north"]).query)


def test_a_play_url_that_already_names_the_reserved_keys_does_not_win() -> None:
    url = build_launch_url("https://go-forth.test/play?match=other&seat=9&token=stolen&env=beta", "m-1", "1")
    query = parse_qs(urlsplit(url).query)
    assert query["match"] == ["m-1"]
    assert query["seat"] == ["1"]
    assert "token" not in query
    # An unrelated parameter is a legitimate environment hint and survives.
    assert query["env"] == ["beta"]


def test_a_fragment_is_dropped() -> None:
    url = build_launch_url("https://go-forth.test/play#/lobby", "m-1", "1")
    # Lobby appends `token=` to the query. With a fragment already on the URL
    # the token would land after the hash, where the server never sees it.
    assert urlsplit(url).fragment == ""


def test_a_scheme_less_play_url_is_assumed_https() -> None:
    assert build_launch_url("go-forth.test/play", "m-1", "1").startswith("https://go-forth.test/play")


def test_a_seat_missing_half_its_identity_gets_no_url() -> None:
    urls = build_launch_urls_for_assignment(PLAY_URL, _assignment([("1", ""), ("2", "south")]))
    # Absent rather than present-and-useless: `provision.launch_urls` checks
    # that every seated player has one, and a URL nobody can use would pass it.
    assert set(urls) == {"south"}


def test_the_return_url_names_the_match() -> None:
    url = build_return_url("https://joinquest.test/return", "m-1")
    assert parse_qs(urlsplit(url).query)["match"] == ["m-1"]


def test_the_return_url_replaces_an_existing_match_parameter() -> None:
    url = build_return_url("https://joinquest.test/return?match=stale&ref=x", "m-1")
    query = parse_qs(urlsplit(url).query)
    assert query["match"] == ["m-1"]
    assert query["ref"] == ["x"]


def test_provision_returns_urls_built_on_the_configured_play_url(client: TestClient) -> None:
    body = client.post("/api/v1/matches", json=provision_body()).json()
    for url in body["launchUrls"].values():
        assert url.startswith(PLAY_URL)
        assert "token=" not in url
