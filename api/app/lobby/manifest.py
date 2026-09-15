"""What this game tells the Lobby catalog about itself.

`GET /api/v1/status` and `GET /api/v1/game-modes` are read by the catalog sync,
and between them they are the whole of what Lobby knows before a match exists.

## Two modes, and why the demo is one of them

The production shape of Go Forth! is **first to three round wins**, with a base
destroyed ending the match on the spot and no base recovery between rounds
(Ryan, 2026-09-13). That is `starter`.

The opening demo plays exactly **one round**. It could have been a flag on
`starter`, and that is the version worth arguing against: a single round
reported through the production mode is indistinguishable, in every downstream
rating and standings table, from a best-of-five somebody actually won. So it is
its own mode with its own key, `opening-round`, and `RoundPolicy.test_profile`
says so in one place that the session, the wire snapshot and the Lobby result
all read. A test profile can be labelled on screen, kept out of ratings, and
recognised months later in a row of match history; a flag buried in a config
cannot.

Both are `1v1` with a two-seat template, because both are the same game.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Reported on `/api/v1/status` and used as the catalog's key for this game.
GAME_NAME = "go-forth"

#: Bumped when the wire contract changes, not when the game does. `app/match/
#: wire.py` is the thing this version is about.
GAME_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class RoundPolicy:
    """How many rounds decide a match, and whether the result counts."""

    #: Round wins needed to take the match. One is the demo; three is Starter.
    rounds_to_win: int
    #: A test profile reports a terminal outcome that never claims a completed
    #: series. Carried into the snapshot so the label on screen is the server's
    #: claim rather than a build-time guess, and into `reportMatchResult` so the
    #: Lobby is not told a ladder match happened.
    test_profile: bool


@dataclass(frozen=True, slots=True)
class GameMode:
    key: str
    display_name: str
    min_players: int
    max_players: int
    seat_count: int
    social_mode: str
    typical_minutes: int
    round_policy: RoundPolicy

    def to_manifest(self) -> dict[str, Any]:
        """The JSON Lobby's catalog fetcher reads.

        `seatTemplate` is a `count` node, never a flat `seats[]` array — Lobby
        rejects the latter outright (integration guide §4). `roundPolicy` is
        deliberately absent: match length is not catalog data, and a field Lobby
        does not read is a field that will drift.
        """
        return {
            "key": self.key,
            "displayName": self.display_name,
            "minPlayers": self.min_players,
            "maxPlayers": self.max_players,
            "socialMode": self.social_mode,
            "typicalMinutes": self.typical_minutes,
            "seatTemplate": {"count": self.seat_count},
        }


#: The production match: first to three round wins.
STARTER = GameMode(
    key="starter",
    display_name="Starter Duel",
    min_players=2,
    max_players=2,
    seat_count=2,
    social_mode="1v1",
    typical_minutes=12,
    round_policy=RoundPolicy(rounds_to_win=3, test_profile=False),
)

#: The opening demo: one round, reported as a test rather than as a series.
OPENING_ROUND = GameMode(
    key="opening-round",
    display_name="Opening Round",
    min_players=2,
    max_players=2,
    seat_count=2,
    social_mode="1v1",
    # One plan phase and one 90-second battle, plus the reading either side of it.
    typical_minutes=3,
    round_policy=RoundPolicy(rounds_to_win=1, test_profile=True),
)

GAME_MODES: tuple[GameMode, ...] = (STARTER, OPENING_ROUND)

#: What a provision with no recognisable mode falls back to. The demo rather
#: than Starter: a mode we did not recognise is not one we should report a
#: rated best-of-five for.
DEFAULT_GAME_MODE = OPENING_ROUND.key


def get_game_mode(key: str) -> GameMode | None:
    """Walks the tuple rather than a dict — see the iteration rule in `rng.py`."""
    for mode in GAME_MODES:
        if mode.key == key:
            return mode
    return None


def mode_or_default(key: str | None) -> GameMode:
    """The mode a provision named, or the demo when it named nothing we know."""
    found = get_game_mode(key) if key else None
    if found is not None:
        return found
    fallback = get_game_mode(DEFAULT_GAME_MODE)
    assert fallback is not None  # DEFAULT_GAME_MODE is one of GAME_MODES
    return fallback


def seat_keys_for_mode(mode: GameMode) -> tuple[str, ...]:
    """The seat keys Lobby's template expansion produces: "1", "2", ...

    Must stay aligned with Lobby's `seattemplate` expansion and with rpslr,
    which numbers from one. A game that invented its own seat keys would reject
    every token Lobby minted.
    """
    return tuple(str(index + 1) for index in range(max(0, mode.seat_count)))


def build_status_payload(*, app_env: str, standalone: bool) -> dict[str, Any]:
    """`GET /api/v1/status`.

    `launchUrlsOnProvision` is the capability flag Lobby branches on: it says
    this game mints its own per-player launch URLs and returns them from
    provision, rather than having Lobby build them from a template.
    """
    return {
        "game": GAME_NAME,
        "version": GAME_VERSION,
        "appEnv": app_env,
        "standalone": standalone,
        "launchUrlsOnProvision": True,
    }


def build_game_modes_payload() -> dict[str, Any]:
    """`GET /api/v1/game-modes`."""
    return {"game": GAME_NAME, "modes": [mode.to_manifest() for mode in GAME_MODES]}
