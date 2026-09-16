# Reading the Python reference next to the TypeScript one

Go Forth!'s api is JoinQuest's **Python** reference implementation. rpslr and
wordhunt cover TypeScript. The point of having both is that a developer can read
the integration contract in the language they are actually writing — so the two
implementations are meant to be read side by side, and this page is for the
moments when they look different.

**The wire contract is identical.** Every difference below is in the
implementation. If a payload shape here disagrees with rpslr, that is a bug in
this repo, not a language difference.

## Where to find things

| rpslr (TypeScript)        | go-forth (Python)            | what it is                        |
|---------------------------|------------------------------|-----------------------------------|
| `api/src/gameModes.ts`    | `api/app/lobby/manifest.py`  | `/api/v1/status`, `/api/v1/game-modes` |
| `api/src/lobbyIssuer.ts`  | `api/app/lobby/issuer.py`    | issuer normalisation, JWKS + GraphQL URLs |
| `api/src/tokens.ts`       | `api/app/lobby/tokens.py`    | seat JWT verification, JWKS rotation |
| `api/src/provision.ts`    | `api/app/lobby/provision.py` | parsing and authorising Lobby's push |
| `api/src/launchUrls.ts`   | `api/app/lobby/launch_urls.py` | per-player launch URLs            |
| `api/src/lobbyClient.ts`  | `api/app/lobby/client.py`    | `reportMatchResult`, player lookup |
| `api/src/seatBinding.ts`  | `api/app/lobby/seat_binding.py` | recovery path 1 (own-origin cookie) |
| `api/src/app.ts`          | `api/app/routes.py`          | the HTTP routes                    |
| `api/src/ws.ts`           | `api/app/ws.py`              | the realtime transport             |
| `api/src/matchHub.ts`     | `api/app/match/hub.py`       | in-process fan-out                 |
| `api/src/repository.ts`, `memoryRepository.ts`, `pgRepository.ts` | `api/app/repository.py`, `api/app/pg_repository.py` | persistence |

Test files follow the same mapping: `jwksRotation.test.ts` ↔
`tests/lobby/test_jwks_rotation.py`, `ws.test.ts` ↔
`tests/match/test_realtime.py`, and so on. The integration guide's §8 table names
the rpslr file for each row; each Python test module names the same row in its
docstring.

## Genuine language differences

### 1. Errors are raised, not returned

rpslr's parsers return `Input | string` — the parsed value, or a message saying
what was wrong — because TypeScript has no cheap exceptions and no way to make
one part of a union.

Python does. `parse_lobby_provision` raises `ProvisionError`; `parse_plan` raises
`PlanError`. The contract is identical: same checks, same messages, same HTTP
status at the edge. Only the channel differs.

### 2. JWT verification uses PyJWT, not `jose`

`pyjwt[crypto]` is what a Python developer reaching for this already has.

The **JWKS cache is written out by hand** rather than using `PyJWKClient`, which
would do most of it. That is deliberate: key rotation is the part integrators get
wrong, and a reference implementation whose rotation behaviour lives inside a
library dependency teaches nobody what the rule is. `app/lobby/tokens.py` spells
out the refetch-on-unknown-`kid` rule and the rate limit that keeps it from
becoming a denial-of-service against the Lobby.

### 3. Async is explicit

FastAPI routes and the WebSocket handler are `async def`, and so is everything
they reach: the token verifier, the Lobby client, the repository. In rpslr the
same code is `async` too, but `await` on a synchronous value is free there and
here it is a type error. The practical consequence is that `Repository` is an
async protocol even though `MemoryRepository` never awaits anything.

### 4. Migrations are plain SQL, and that is on purpose

Not Alembic. The only difference between the references should be the language,
not the architecture — someone comparing rpslr to go-forth to learn the contract
should not have to learn a migration framework first. `app/migrate.py` is the
whole runner. See `api/CONVENTIONS.md`.

### 5. Determinism has a hazard TypeScript does not

Python randomises string hashing per process, so iterating a `set` gives a
different order in every fresh interpreter. TypeScript's `Set` iterates in
insertion order, so code that was correct there becomes non-deterministic here
with no visible change.

This reaches the contract layer in two places worth naming, because both look
like formatting details:

- **`GameService.banned_in`** returns the banned ids in the *caller's* order, not
  the set's. That list goes on the wire in the 403 body.
- **Spell resolution** (`app/sim/loadout.py`) walks deployed mages in troop order
  and tags in the order the spell reads them, and sorts tag support by tag on the
  way out. The resolved costs, effects and contributors are sent to the client
  and fired by the sim, so a set-ordered version would differ between two servers
  running identical code.

  It is also the one calculation that exists in **both** languages —
  `client/src/plan/spellResolver.ts` is the copy — because the plan screen
  re-prices a spell on every tap and a round trip per tap is not a screen. They
  are held together by `conformance/spell-resolver.json`, generated from the
  Python and asserted from both sides.

The full rules, and why a determinism test must spawn a subprocess, are in
`api/CONVENTIONS.md`.

### 6. Tests are not co-located

`tests/` sits outside the package, which is the Python convention;
rpslr puts `app.test.ts` next to `app.ts`. `pyproject.toml` puts `.` on the path
via `[tool.pytest.ini_options] pythonpath`.

## Things that are *not* language differences

A few things look like divergence and are not:

- **Seat keys are `"1"` and `"2"`** in both, because that is what Lobby's
  template expansion produces. A game that numbered its seats differently would
  reject every token Lobby minted.
- **The seat token's `matchId` and `seatKey` are top-level claims**, not nested.
  `scripts/stub_lobby.py` was nesting them under a `joinquest` object before
  JQ-309 and was corrected, because a stub that verifies against itself while
  teaching the wrong shape is worse than no stub.
- **`launchUrls` bases never carry a JWT.** Lobby appends `token=`.
- **A re-claim answers 200 and a first claim 201.** Both games.

## Two divergences from this repo's own client

`client/src/match/types.ts` was written against JQ-311's fixtures, before JQ-376
replaced the three-zone map with two lanes. The **server is authoritative** and
the client has not caught up yet:

| client (JQ-311 fixture)   | server (authoritative)              |
|---------------------------|-------------------------------------|
| `ZoneId` of `A`, `B`, `C` | zone ids from the map: `"W"`, `"E"` |
| `Order.kind` of `hold`    | `holdZone`                          |

Adopting the server's names on the client is JQ-311's follow-up. Renaming the
sim's lanes to keep a stale fixture happy would be the tail wagging the dog.
