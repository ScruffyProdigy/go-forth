"""Talking back to the Lobby: player lookup and the match lifecycle callbacks.

Every call here is **best effort**. A match that cannot reach the Lobby still
plays to its end and still tells its players what happened — the Lobby learning
about it is a separate concern from the game working, and wiring them together
would mean a Lobby outage takes two players' match with it.

The two mutations are not interchangeable:

* `reportPlayerFinished` — *one player* is done for themselves: they quit,
  forfeited, or ran out a grace period this game defined. Never a dropped
  socket. Reporting it releases their queue row and closes their way back in,
  and a player who lost wifi is still seated and still expected back.
* `reportMatchResult` — the *match* is over.

## The test profile and `status`

`RoundPolicy.test_profile` decides which `status` a finished demo reports. A
single round is not a completed best-of-five, so the opening demo closes out as
`CANCELLED` — which the guide defines as leaving the match unrated — rather than
`COMPLETED` with a winner the ratings would then move on. The round winner still
travels, in `metadata`, so the run is legible in match history without being
counted as a series somebody won.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal

from app.lobby.issuer import lobby_graphql_url

log = logging.getLogger(__name__)

#: How a player's participation ended. Lobby drops `DISCONNECT` out of the
#: rating inputs entirely, so the reason is not decoration.
PlayerFinishReason = Literal["COMPLETED", "ELIMINATED", "FORFEIT", "DISCONNECT"]

MatchResultStatus = Literal["COMPLETED", "CANCELLED", "ABANDONED"]

_PLAYER_QUERY = """
  query Player($id: ID!) {
    player(id: $id) {
      id
      displayName
      avatarUrl
    }
  }
"""

_REPORT_PLAYER_FINISHED = """
  mutation ReportPlayerFinished(
    $matchId: ID!
    $lobbyUserId: ID!
    $reason: PlayerFinishReason!
    $placement: Int
  ) {
    reportPlayerFinished(
      matchId: $matchId
      lobbyUserId: $lobbyUserId
      reason: $reason
      placement: $placement
    )
  }
"""

_REPORT_MATCH_RESULT = """
  mutation ReportMatchResult(
    $matchId: ID!
    $status: MatchResultStatus!
    $winnerLobbyUserIds: [ID!]
    $metadata: JSON
  ) {
    reportMatchResult(
      matchId: $matchId
      status: $status
      winnerLobbyUserIds: $winnerLobbyUserIds
      metadata: $metadata
    )
  }
"""

#: Posts one GraphQL document and returns the parsed body. Injected so tests
#: assert on what was sent without standing up a Lobby.
GraphqlTransport = Callable[[str, Mapping[str, str], Mapping[str, Any]], Awaitable[Mapping[str, Any]]]


async def _post_over_https(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=dict(headers), json=dict(payload))
        response.raise_for_status()
        body = response.json()
    return body if isinstance(body, dict) else {}


def _auth_header(service_token: str | None) -> dict[str, str]:
    token = (service_token or "").strip()
    if not token:
        return {}
    return {"authorization": token if token.lower().startswith("bearer ") else f"Bearer {token}"}


class LobbyClient:
    """A Lobby's GraphQL endpoint, with the service token that opens it."""

    def __init__(
        self,
        graphql_url: str,
        service_token: str | None = None,
        *,
        transport: GraphqlTransport | None = None,
    ) -> None:
        self._url = lobby_graphql_url(graphql_url)
        self._service_token = service_token
        self._post = transport or _post_over_https

    async def _call(self, name: str, query: str, variables: Mapping[str, Any]) -> Any:
        """Returns the named field, or None on any failure. Never raises."""
        headers = {"content-type": "application/json", **_auth_header(self._service_token)}
        try:
            body = await self._post(self._url, headers, {"query": query, "variables": dict(variables)})
        except Exception as err:
            log.warning("[lobby] %s request failed: %s", name, err)
            return None

        errors = body.get("errors")
        if errors:
            log.warning("[lobby] %s GraphQL errors: %s", name, json.dumps(errors)[:500])
            return None

        data = body.get("data")
        if not isinstance(data, dict):
            log.warning("[lobby] %s returned no data", name)
            return None
        return data.get(name)

    async def fetch_display_name(self, lobby_user_id: str) -> str | None:
        """The player's name as the Lobby knows it, or None if it cannot say."""
        player = await self._call("player", _PLAYER_QUERY, {"id": lobby_user_id})
        if not isinstance(player, dict):
            return None
        name = player.get("displayName")
        return name.strip() if isinstance(name, str) and name.strip() else None

    async def report_player_finished(
        self,
        match_id: str,
        lobby_user_id: str,
        reason: PlayerFinishReason,
        placement: int | None = None,
    ) -> bool:
        result = await self._call(
            "reportPlayerFinished",
            _REPORT_PLAYER_FINISHED,
            {
                "matchId": match_id,
                "lobbyUserId": lobby_user_id,
                "reason": reason,
                "placement": placement,
            },
        )
        return result is True

    async def report_match_result(
        self,
        match_id: str,
        status: MatchResultStatus,
        winner_lobby_user_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        """Close the match out with the Lobby.

        Safe to call more than once: the mutation is keyed by `matchId` on
        Lobby's side, so a retry after a timeout reports the same terminal state
        rather than a second one. `MatchSession` leans on that — it retries
        rather than tracking whether the first attempt got through.
        """
        result = await self._call(
            "reportMatchResult",
            _REPORT_MATCH_RESULT,
            {
                "matchId": match_id,
                "status": status,
                "winnerLobbyUserIds": list(winner_lobby_user_ids),
                "metadata": dict(metadata) if metadata else None,
            },
        )
        return result is True


async def resolve_display_name(
    *,
    from_token: str | None,
    client: LobbyClient | None,
    lobby_user_id: str,
    from_body: str | None = None,
) -> str:
    """A player's name: token claim, then Lobby, then the request, then a default.

    The token first because it is signed, and the Lobby lookup second because it
    costs a round trip on a path a player is waiting on.
    """
    if from_token and from_token.strip():
        return from_token.strip()

    if client is not None:
        name = await client.fetch_display_name(lobby_user_id)
        if name:
            return name

    if from_body and from_body.strip():
        return from_body.strip()

    return "Mage"
