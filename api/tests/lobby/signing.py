"""A stand-in Lobby signer, so the claim rows can be tested without one.

Mints RS256 seat tokens and serves a matching JWKS document, which is the whole
of what the game needs to verify a claim. Deliberately the same shape as
`scripts/stub_lobby.py` — that one is a running process a developer points the
game at, this one is an object a test holds — so a failure here and a failure
there mean the same thing.

Two keys, because the rotation row needs two: a JWKS may carry more than one
active key while a signing key is being rotated, and a game that cached the
first one it saw rejects every token minted after the rotation.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass
class SigningKey:
    kid: str
    private: rsa.RSAPrivateKey

    def jwk(self) -> dict[str, Any]:
        numbers = self.private.public_key().public_numbers()
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
            "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
        }

    def pem(self) -> bytes:
        from cryptography.hazmat.primitives import serialization

        return self.private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


def _new_key(kid: str) -> SigningKey:
    # 2048 is what the real Lobby uses. Keys are generated once per module import
    # by `stub_lobby()` below rather than per test: RSA keygen is the slowest
    # thing in this suite by an order of magnitude.
    return SigningKey(kid=kid, private=rsa.generate_private_key(public_exponent=65537, key_size=2048))


@dataclass
class StubLobby:
    """One Lobby's worth of signing keys, and the JWKS it would publish."""

    issuer: str = "https://lobby.test"
    audience: str = "http://localhost:3002"
    keys: list[SigningKey] = field(default_factory=list)
    #: Counts JWKS fetches, so the rate-limit and refetch rules are assertable.
    fetches: int = 0

    def jwks(self) -> dict[str, Any]:
        return {"keys": [key.jwk() for key in self.keys]}

    async def fetch(self, url: str) -> dict[str, Any]:
        """A `JwksFetcher` that never opens a socket."""
        self.fetches += 1
        assert url == f"{self.issuer}/.well-known/jwks.json", url
        return self.jwks()

    def mint(
        self,
        *,
        lobby_user_id: str,
        match_id: str,
        seat_key: str,
        kid: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        expires_in: int = 900,
        display_name: str | None = None,
        omit: tuple[str, ...] = (),
    ) -> str:
        """One seat token. `omit` drops claims, for the schema-rejection rows."""
        key = next((k for k in self.keys if k.kid == kid), None) if kid else self.keys[0]
        assert key is not None, f"no such key: {kid}"

        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": issuer if issuer is not None else self.issuer,
            "aud": audience if audience is not None else self.audience,
            "sub": lobby_user_id,
            "matchId": match_id,
            "seatKey": seat_key,
            "iat": now,
            "nbf": now,
            "exp": now + expires_in,
        }
        if display_name:
            payload["name"] = display_name
        for claim in omit:
            payload.pop(claim, None)

        return jwt.encode(payload, key.pem(), algorithm="RS256", headers={"kid": key.kid})


#: Two keys, generated once. `rotate()` retires the first.
_LOBBY = StubLobby(keys=[_new_key("lobby-key-1"), _new_key("lobby-key-2")])


def stub_lobby(**overrides: Any) -> StubLobby:
    """A fresh stub sharing the module's keys, so no test pays for keygen twice."""
    return StubLobby(keys=list(_LOBBY.keys), **overrides)


def single_key_lobby(kid: str = "lobby-key-1", **overrides: Any) -> StubLobby:
    """A stub publishing one key — the state before and after a rotation."""
    key = next(k for k in _LOBBY.keys if k.kid == kid)
    return StubLobby(keys=[key], **overrides)
