"""Per-player launch URLs, minted by the game and returned from provision.

`launchUrlsOnProvision: true` on `/api/v1/status` is the promise that this
exists. Lobby takes each base returned here and appends `token=<jwt>` when it
links a player, which is why **a base must never carry a JWT of its own**
(integration guide §7, checklist row `provision.launch_url_no_jwt`): a token in
the base would be minted at provision time, shared by whoever saw the URL, and
still valid long after the player it was for had gone.

Shape matches rpslr exactly — `{playUrl}?match={externalMatchId}&seat={seatKey}`
— because the client reads `?match=` and `?seat=` in both games.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.lobby.provision import Assignment

#: Query parameters a launch URL must not already carry. `token` is Lobby's to
#: add; the other two are ours to set, and a base that set them itself would
#: silently win over the seat we are building the URL for.
_RESERVED_QUERY_KEYS = frozenset({"token", "match", "seat"})


def build_launch_url(play_url: str, external_match_id: str, seat_key: str) -> str:
    """One seat's launch URL base."""
    origin = play_url.strip().rstrip("/")
    if "://" not in origin:
        origin = f"https://{origin}"

    scheme, netloc, path, query, _fragment = urlsplit(origin)
    # Existing query parameters are kept — a play URL may legitimately carry an
    # environment hint — except the three that are not the base's to set.
    kept = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if key not in _RESERVED_QUERY_KEYS
    ]
    kept.append(("match", external_match_id))
    kept.append(("seat", seat_key))

    # The fragment is dropped rather than preserved: Lobby appends `token=` to
    # the query, and a URL with a fragment already on it would put the token
    # after the hash, where the server never sees it.
    return urlunsplit((scheme, netloc, path, urlencode(kept), ""))


def build_launch_urls_for_assignment(play_url: str, assignment: Assignment) -> dict[str, str]:
    """Launch URLs keyed by Lobby user id, one per seated player.

    Every seated player needs an entry or the `provision.launch_urls` check
    fails, so a seat missing either half of its identity is skipped loudly by
    its absence rather than papered over with a URL nobody can use.
    """
    urls: dict[str, str] = {}
    for seat in assignment.seats:
        if not seat.lobby_user_id or not seat.seat_key:
            continue
        urls[seat.lobby_user_id] = build_launch_url(play_url, assignment.external_match_id, seat.seat_key)
    return urls


def build_return_url(return_url: str, external_match_id: str) -> str:
    """Where a finished player is sent back to in the Lobby.

    A **navigation** target, never something to POST or `fetch`. Lobby's session
    cookie is `SameSite=Lax`: it rides a top-level navigation and is not sent on
    a cross-site POST, so a game that hands off by fetching gets an anonymous
    request and a player who looks logged out (integration guide §6).
    """
    base = return_url.strip().rstrip("/")
    scheme, netloc, path, query, fragment = urlsplit(base)
    kept = [(key, value) for key, value in parse_qsl(query, keep_blank_values=True) if key != "match"]
    kept.append(("match", external_match_id))
    return urlunsplit((scheme, netloc, path, urlencode(kept), fragment))
