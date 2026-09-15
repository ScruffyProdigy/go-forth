"""The game's own record of which browser holds which seat.

This is recovery path 1 from the integration guide's *Reconnecting a player*:
on a successful claim the game writes a cookie **on its own origin** naming the
seat this browser took, and a later request arriving with no `?token=` — a
refresh, the back button, a tab that crashed — resumes from it. No Lobby round
trip, so it keeps working when the Lobby is slow, unreachable, or the player's
Lobby session is gone.

Path 2, the Rejoin button, is the Lobby's half. The two fail independently on
purpose: a player who cannot get back in ruins the match for everyone still in
it, so neither path is allowed to be the only one.

## Why the cookie needs no signature

It carries `player_id`, which is already this game's gameplay credential: the
WebSocket subscribes with it and casts name it. A forged binding therefore needs
a `player_id` the forger could only have by already being able to play that
seat, so the cookie grants nothing the client did not hold. It names
`lobby_user_id` and `seat_key` alongside it because the resume path checks all
three against the live match before it resumes anything — **the binding names a
seat; the match decides**.

`HttpOnly` because only the server reads it. `SameSite=Lax` because this game's
client and API are the same site in every environment.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass

SEAT_BINDING_COOKIE = "go_forth_seat"

#: Twelve hours: longer than any Go Forth! match, shorter than a browser session
#: that has plainly moved on. The binding is re-checked against the match on
#: every use anyway, so this only bounds how long a dead one lingers.
MAX_AGE_SECONDS = 12 * 60 * 60


@dataclass(frozen=True, slots=True)
class SeatBinding:
    #: Lobby's id for the match — the join key on both sides of the protocol.
    external_match_id: str
    seat_key: str
    #: The verified `sub` of the seat token that claimed it.
    lobby_user_id: str
    #: This game's own player row, and the credential the client plays with.
    player_id: str


def encode_seat_binding(binding: SeatBinding) -> str:
    """Short keys: this rides on every request to the game's own origin."""
    wire = {
        "m": binding.external_match_id,
        "s": binding.seat_key,
        "u": binding.lobby_user_id,
        "p": binding.player_id,
    }
    raw = json.dumps(wire, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_seat_binding(raw: str | None) -> SeatBinding | None:
    """None for anything that is not a binding we wrote — never a raise.

    A browser can present any cookie value at all, including one left over from
    a different deploy, so an unreadable binding is an ordinary outcome of this
    function rather than an error condition.
    """
    if not raw:
        return None

    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        parsed = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None

    if not isinstance(parsed, dict):
        return None

    values = [parsed.get(key) for key in ("m", "s", "u", "p")]
    if not all(isinstance(value, str) and value for value in values):
        return None

    external_match_id, seat_key, lobby_user_id, player_id = values
    return SeatBinding(
        external_match_id=str(external_match_id),
        seat_key=str(seat_key),
        lobby_user_id=str(lobby_user_id),
        player_id=str(player_id),
    )


def seat_binding_cookie(binding: SeatBinding, *, secure: bool) -> str:
    """The `Set-Cookie` value that writes the binding."""
    parts = [
        f"{SEAT_BINDING_COOKIE}={encode_seat_binding(binding)}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={MAX_AGE_SECONDS}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_seat_binding_cookie(*, secure: bool) -> str:
    """Clears it.

    Sent when a binding names a seat the match will not resume — a finished
    match, or a seat someone else now holds — so a browser stops presenting a
    binding that can never work again.
    """
    parts = [f"{SEAT_BINDING_COOKIE}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
