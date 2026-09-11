"""A stand-in for the JoinQuest Lobby, so Go Forth! runs standalone.

Two halves, matching what the real Lobby gives a game:

1. A JWKS endpoint and a matching signer, so seat JWTs can be minted and
   verified locally. This half is real — an RS256 keypair, a well-formed
   ``/.well-known/jwks.json``, and tokens that verify against it with any
   standard library. It works today.
2. A provisioning stub that POSTs a match assignment at the game API, the way
   the Lobby pushes one. The endpoint it calls (``POST /api/v1/matches``) is
   JQ-188's to build; until then ``provision`` reports the 404 plainly rather
   than pretending, and ``serve`` and ``token`` are the useful halves.

Python rather than Node, even though the client's toolchain is Node: what this
demonstrates — RS256 signing, a JWKS document, seat-token minting — is the JWT
claim and JWKS rotation rows of the integration guide's §8, and a developer
reading the Python reference should not have to read JavaScript to follow the
auth stub.

Standard library only, so it runs before anything is installed.
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = REPO_ROOT / ".stub-lobby" / "signing-key.json"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class Settings:
    port: int
    api_port: int
    issuer: str
    audience: str
    api_base_url: str

    @classmethod
    def from_env(cls) -> Settings:
        import os

        port = int(os.environ.get("STUB_LOBBY_PORT", "4002"))
        api_port = int(os.environ.get("API_PORT", "3002"))
        return cls(
            port=port,
            api_port=api_port,
            issuer=os.environ.get("STUB_LOBBY_ISSUER", f"http://localhost:{port}"),
            # Seat JWT `aud` is the game API's own origin, as the real Lobby sets it.
            audience=os.environ.get("GAME_API_AUDIENCE", f"http://localhost:{api_port}"),
            api_base_url=os.environ.get("GAME_API_BASE_URL", f"http://localhost:{api_port}"),
        )


class Signer:
    """RS256 signing over a keypair cached on disk.

    The key is cached because the JWKS has to keep matching tokens minted
    before the last restart — regenerating per run makes every token issued a
    minute ago fail verification for reasons that look like a bug in the game.
    """

    def __init__(self, key_file: Path = KEY_FILE) -> None:
        self._key_file = key_file
        self._key = self._load_or_create()

    def _load_or_create(self) -> dict[str, Any]:
        try:
            loaded: dict[str, Any] = json.loads(self._key_file.read_text())
            return loaded
        except (OSError, json.JSONDecodeError):
            pass

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ModuleNotFoundError:
            raise SystemExit(
                "stub-lobby needs the `cryptography` package to mint keys.\n"
                "  Run ./scripts/setup.sh, then ./scripts/stub-lobby.sh serve\n"
                "  (it is pulled in by the api's dev dependencies)."
            ) from None

        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key = {
            "kid": f"stub-lobby-{uuid.uuid4().hex[:8]}",
            "private_pem": private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode(),
            "public_numbers": {
                "n": _b64url(
                    private.public_key()
                    .public_numbers()
                    .n.to_bytes((private.public_key().public_numbers().n.bit_length() + 7) // 8, "big")
                ),
                "e": _b64url(
                    private.public_key()
                    .public_numbers()
                    .e.to_bytes((private.public_key().public_numbers().e.bit_length() + 7) // 8, "big")
                ),
            },
        }
        self._key_file.parent.mkdir(parents=True, exist_ok=True)
        self._key_file.write_text(json.dumps(key, indent=2))
        self._key_file.chmod(0o600)
        print(f"[stub-lobby] generated a new signing key ({key['kid']}) in .stub-lobby/", file=sys.stderr)
        return key

    @property
    def kid(self) -> str:
        return str(self._key["kid"])

    def jwks(self) -> dict[str, Any]:
        numbers = self._key["public_numbers"]
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "n": numbers["n"],
                    "e": numbers["e"],
                    "kid": self.kid,
                    "use": "sig",
                    "alg": "RS256",
                }
            ]
        }

    def sign(self, signing_input: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        private = serialization.load_pem_private_key(self._key["private_pem"].encode(), password=None)
        assert isinstance(private, rsa.RSAPrivateKey)
        return private.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())


def mint_seat_token(
    signer: Signer,
    settings: Settings,
    *,
    user_id: str,
    match_id: str,
    seat_key: str,
    ttl_seconds: int = 3600,
) -> str:
    """An RS256 seat JWT shaped like the one the Lobby hands a player."""
    now = int(time())
    header = {"alg": "RS256", "typ": "JWT", "kid": signer.kid}
    payload = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": user_id,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": str(uuid.uuid4()),
        # The seat claim the game checks before letting this user take the seat.
        "joinquest": {"matchId": match_id, "seatKey": seat_key, "userId": user_id},
    }
    def encode(part: dict[str, Any]) -> str:
        return _b64url(json.dumps(part, separators=(",", ":")).encode())

    signing_input = f"{encode(header)}.{encode(payload)}".encode()
    return f"{signing_input.decode()}.{_b64url(signer.sign(signing_input))}"


def provision_payload(settings: Settings, external_match_id: str) -> dict[str, Any]:
    """A Lobby-shaped provision payload for a two-seat match."""
    import os

    return {
        "assignment": {
            "externalMatchId": external_match_id,
            "gameMode": "skirmish",
            "seats": [
                {"seatKey": "a", "position": 0, "lobbyUserId": "stub-user-a", "displayName": "Player A"},
                {"seatKey": "b", "position": 1, "lobbyUserId": "stub-user-b", "displayName": "Player B"},
            ],
        },
        "lobby": {
            "issuer": settings.issuer,
            "jwksUri": f"{settings.issuer}/.well-known/jwks.json",
            "serviceToken": os.environ.get("LOBBY_SERVICE_TOKEN", "stub-service-token"),
        },
    }


def serve(signer: Signer, settings: Settings) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, indent=2).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's contract
            from urllib.parse import parse_qs, urlparse

            url = urlparse(self.path)
            query = parse_qs(url.query)

            if url.path == "/.well-known/jwks.json":
                return self._send(200, signer.jwks())
            if url.path == "/token":
                return self._send(
                    200,
                    {
                        "token": mint_seat_token(
                            signer,
                            settings,
                            user_id=query.get("user", ["stub-user-a"])[0],
                            match_id=query.get("match", ["stub-match"])[0],
                            seat_key=query.get("seat", ["a"])[0],
                        )
                    },
                )
            if url.path == "/healthz":
                return self._send(200, {"ok": True, "issuer": settings.issuer})
            return self._send(
                404,
                {"error": "not found", "routes": ["/.well-known/jwks.json", "/token", "/healthz"]},
            )

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[stub-lobby] {fmt % args}", file=sys.stderr)

    issuer = settings.issuer
    print(f"[stub-lobby] listening on {issuer}", file=sys.stderr)
    print(f"[stub-lobby]   JWKS   {issuer}/.well-known/jwks.json", file=sys.stderr)
    print(f"[stub-lobby]   token  {issuer}/token?user=stub-user-a&match=m1&seat=a", file=sys.stderr)
    print(f"[stub-lobby] seat JWTs are issued for aud={settings.audience}", file=sys.stderr)
    print("[stub-lobby] point the API at this with LOBBY_JWKS_URI (JQ-188).", file=sys.stderr)
    HTTPServer(("127.0.0.1", settings.port), Handler).serve_forever()


def provision(signer: Signer, settings: Settings) -> None:
    external_match_id = f"stub-{int(time() * 1000)}"
    body = provision_payload(settings, external_match_id)
    request = urllib.request.Request(
        f"{settings.api_base_url}/api/v1/matches",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            status, text = response.status, response.read().decode()
    except urllib.error.HTTPError as err:
        status, text = err.code, err.read().decode()
    except urllib.error.URLError as err:
        raise SystemExit(
            f"[stub-lobby] no game API on {settings.api_base_url} — "
            f"start it with ./scripts/dev.sh ({err.reason})"
        ) from err

    if status == 404:
        print(f"[stub-lobby] {settings.api_base_url}/api/v1/matches returned 404.", file=sys.stderr)
        print(
            "[stub-lobby] Provisioning is JQ-188 and is not built yet — this is expected today.",
            file=sys.stderr,
        )
        print("[stub-lobby] The payload that would have been pushed:", file=sys.stderr)
        print(json.dumps(body, indent=2), file=sys.stderr)
        raise SystemExit(2)

    print(f"[stub-lobby] POST /api/v1/matches -> {status}", file=sys.stderr)
    print(text)
    if status >= 400:
        raise SystemExit(1)

    # Hand back tokens for the seats just provisioned, so a browser can take
    # one without a second command.
    for seat in body["assignment"]["seats"]:
        token = mint_seat_token(
            signer,
            settings,
            user_id=seat["lobbyUserId"],
            match_id=external_match_id,
            seat_key=seat["seatKey"],
        )
        print(f"[stub-lobby] seat {seat['seatKey']} ({seat['lobbyUserId']}): {token}", file=sys.stderr)


def main(argv: list[str]) -> None:
    settings = Settings.from_env()
    signer = Signer()
    command = argv[0] if argv else ""

    if command == "serve":
        serve(signer, settings)
    elif command == "jwks":
        print(json.dumps(signer.jwks(), indent=2))
    elif command == "token":
        user_id = argv[1] if len(argv) > 1 else "stub-user-a"
        match_id = argv[2] if len(argv) > 2 else "stub-match"
        seat_key = argv[3] if len(argv) > 3 else "a"
        print(mint_seat_token(signer, settings, user_id=user_id, match_id=match_id, seat_key=seat_key))
    elif command == "provision":
        provision(signer, settings)
    else:
        raise SystemExit(f"Unknown command: {command or '(none)'}")


if __name__ == "__main__":
    main(sys.argv[1:])
