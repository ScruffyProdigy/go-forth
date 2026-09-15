# Go Forth! — JoinQuest game

A light **mini-RTS with no click race**: you plan, you deploy, and then you watch
your plan meet theirs. Rounds alternate between a planning phase and an
auto-resolved battle. Armies are troops of mages and summons, the objective is
zone control with base destruction as the punish, and spells draw on one
regenerating energy pool.

Phone-first, portrait, tap-only. Entry is via the [JoinQuest Lobby](https://joinquest.cc),
using the same integration shape as [rpslr](https://github.com/ScruffyProdigy/rpslr).

> **This api is JoinQuest's Python reference implementation.** rpslr and
> [wordhunt](https://github.com/ScruffyProdigy/wordhunt) already cover
> TypeScript, so go-forth exists partly so a Python developer has the
> integration contract in the language they're writing. The wire contract must
> match rpslr exactly — only the implementation differs. See
> [`api/CONVENTIONS.md`](api/CONVENTIONS.md).

> This repo is **fully independent** from the Lobby. It does **not** share the
> Lobby's database, ports, or GraphQL schema. It runs on its own ports
> (5175 / 3002 / 5434).

**v1 goal:** confirm the loop is fun for newcomers — Starter 1v1, the Fire school
as a mirror match, one map. Not balance, not depth.

---

## Architecture

```
┌───────────────────────────┐         ┌──────────────────────────────────────────┐
│      JoinQuest Lobby      │         │       Go Forth! (this repo)              │
│      (separate repo)      │         │                                          │
│                           │         │   ┌─────────────┐     ┌───────────────┐  │
│  React UI    :5173        │  link   │   │  Client     │ →   │  Game API     │  │
│  Go GraphQL  :8080  ──────┼─playUrl─┼─▶ │  Vite/React │HTTP │ FastAPI/Python│  │
│  Postgres    :5432        │  (+JWT) │   │  :5175      │     │  :3002        │  │
│  JWKS /.well-known/...    │         │   └─────────────┘     └───────┬───────┘  │
│                           │         │                               │          │
└───────────────────────────┘         │                       ┌───────▼────────┐ │
                                      │                       │ Game Postgres  │ │
        future: JWT verify  ◀─────────┼───────────────────────│  :5434         │ │
        via Lobby JWKS                │                       │  (docker)      │ │
                                      └──────────────────────────────────────────┘
```

The game owns its client, API, and database. The Lobby owns auth, the game
catalog, and matchmaking. The battle sim is **server-authoritative** — the client
renders server state and never simulates ahead of it.

---

## Port plan (avoids Lobby and rpslr collisions)

| Service  | Go Forth! | rpslr | Lobby | Notes                          |
|----------|-----------|-------|-------|--------------------------------|
| Client   | **5175**  | 5174  | 5173  | Vite dev server                |
| API      | **3002**  | 3001  | 8080  | FastAPI + Python 3.12             |
| Postgres | **5434**  | 5433  | 5432  | game's own DB, via docker compose |

All ports are documented in [`.env.example`](.env.example). The offsets are
deliberate: all three services can run at once on one machine.

---

## Quick start

Requires **Python 3.12** for the api and **Node 20 LTS** for the client. The
two are independent packages, each with its own dependency file, installed
separately.

Also requires **Docker** for Postgres.

```bash
./scripts/setup.sh    # .env, the api's venv, and both packages' deps
./scripts/dev.sh      # Postgres + migrations + API (:3002) + Vite (:5175)
```

`setup.sh` creates `api/.venv` and installs into it, so there is no virtualenv
to activate by hand before `dev.sh`. To run the api directly instead:

```bash
cd api && source .venv/bin/activate && python -m app.server
```

[uv](https://docs.astral.sh/uv/) reads the same `pyproject.toml` and is faster
if you have it, but nothing requires it.

Then open **http://localhost:5175**. That is the opening demo (JQ-311): plan a
round, lock it in, watch the battle resolve, read the result. It still runs on a
**fixture session** rather than the server. JQ-309 built the server side — the
Lobby contract, the wire schema and the authoritative realtime session over
`/api/v1/ws` — and pointing the client at it is JQ-311's follow-up. To drive the
real thing today, use the stub Lobby (below); the Lobby contract has its own
suite in `api/tests/lobby/`.

Because it is a fixture, every state the demo has to make legible is reachable
on purpose. Append `?scenario=` to pick one:

| Scenario | What it runs |
|---|---|
| `zoneControl` (default) | An ordinary round, decided on zone control |
| `baseDestruction` | The enemy commits everything to your base and takes it down |
| `dropout` | The connection dies mid-battle and recovers to wherever the server got to |
| `claimFailure` | The seat claim is refused, then succeeds on retry |

The same four are listed at the bottom of the result screen.

`dev.sh` leaves Postgres running when you Ctrl+C, so the next start is fast;
`./scripts/db.sh down` stops it.

### Database

```bash
./scripts/db.sh up        # start Postgres (docker compose)
./scripts/db.sh migrate   # apply api/migrations/*.sql
./scripts/db.sh reset     # drop the volume, recreate, migrate
./scripts/db.sh psql      # a psql shell
./scripts/db.sh url       # print the DATABASE_URL
```

Migrations are forward-only, applied in filename order, one transaction each,
and recorded in `schema_migrations` — so re-running is a no-op. That is what
lets the same command serve local dev and the `migrate` initContainer that runs
before every Kubernetes rollout.

Add one as `api/migrations/NNNN_name.sql`. **Check the highest existing number
immediately before you pick one** — parallel agents reliably choose the same
next number.

### Running with no Lobby

The game is playable standalone, with a stub in place of JoinQuest:

```bash
./scripts/stub-lobby.sh serve      # JWKS on :4002 + a seat-token minter
./scripts/stub-lobby.sh token alice match-1 a
```

The JWKS half is real — an RS256 keypair, a well-formed
`/.well-known/jwks.json`, and tokens that verify against it. The signing key is
cached in `.stub-lobby/` (gitignored) so tokens keep verifying across restarts.

`provision` pushes a real match assignment and prints a ready-to-open URL per
seat — the game's own launch base with `token=` appended exactly as the Lobby
appends it:

```bash
./scripts/stub-lobby.sh serve       # leave this running: JWKS + token endpoint
./scripts/stub-lobby.sh provision   # prints two launch URLs
```

Open one in each of two browsers and that is the two-phone demo, locally, with
no platform in front of it.

**No database needed either.** `GAME_IN_MEMORY=1` swaps the Postgres repository
for an in-memory one, so a fresh checkout is playable with nothing installed but
Python:

```bash
GAME_IN_MEMORY=1 ./scripts/dev.sh
```

### Run the tests

```bash
./scripts/test.sh    # api + client

# or per package
cd api    && ruff check . && ruff format --check . && mypy app tests && pytest
cd client && npm run lint && npm run typecheck && npm test
```

---

## Repo layout

```
.
├── README.md
├── .env.example              # all ports + config documented here
├── docker-compose.yml        # the game's Postgres, host port 5434
├── api/                      # Python 3.12 game server (FastAPI)
│   ├── pyproject.toml        # deps, ruff, mypy and pytest config in one file
│   ├── CONVENTIONS.md        # determinism + porting rules — read before the sim
│   ├── Dockerfile            # builds from the REPO ROOT as context
│   ├── migrations/           # forward-only *.sql, applied in filename order
│   ├── app/
│   │   ├── main.py           # FastAPI factory (no bind) — what tests exercise
│   │   ├── server.py         # binds the port
│   │   ├── migrate.py        # the migration runner
│   │   ├── config.py
│   │   ├── routes.py         # the HTTP surface
│   │   ├── ws.py             # the realtime transport
│   │   ├── service.py        # what routes and sockets both go through
│   │   ├── repository.py     # + pg_repository.py — identity, seating, results
│   │   ├── lobby/            # the JoinQuest contract — fixed, shared with rpslr
│   │   ├── match/            # this game: wire, plan, round, session, clock
│   │   ├── sim/              # the battle sim — pure, deterministic, headless
│   │   └── scripts/
│   │       └── battle_demo.py  # runs a battle, prints the event stream
│   └── tests/                # outside the package, per Python convention
│       ├── lobby/            # one module per integration-guide §8 row
│       ├── match/            # wire, plan, round, session, clock, realtime
│       └── sim/              # the sim's own suite, mirroring app/sim/
├── client/                   # Vite + React 18 game UI
│   ├── Dockerfile            # static build served by nginx
│   ├── nginx.conf            # SPA routing + the cache policy a deploy needs
│   ├── docker-entrypoint.d/  # writes /env.js from container env at startup
│   ├── public/env.js         # the same config, with local dev defaults
│   └── src/
│       ├── plan/             # the plan phase (JQ-293)
│       └── match/            # the match flow: session seam, battle, result
│           └── fixtures/     # still the client's transport; JQ-311 swaps it
├── k8s/
│   ├── base/                 # namespace, api, client, postgres, ingress
│   ├── env/                  # per-environment ConfigMaps, ingress, TLS certs
│   └── secrets/              # *.example.yaml only; real ones are gitignored
├── docs/
│   └── python-vs-typescript.md  # reading this next to rpslr, module by module
├── scripts/                  # setup, dev, db, test, stub-lobby, build, deploy
└── .github/workflows/        # api-tests, client-tests, environment-config-test
```

---

## Game API

| Method | Path                                    | Description                                    |
|--------|-----------------------------------------|------------------------------------------------|
| GET    | `/healthz`                              | returns `200 ok` — no database, no outbound calls |
| GET    | `/api/v1/status`                        | catalog sync: `launchUrlsOnProvision: true`    |
| GET    | `/api/v1/game-modes`                    | the two modes and their 2-seat templates       |
| POST   | `/api/v1/matches`                       | Lobby provision (or a standalone self-serve)   |
| GET    | `/api/v1/matches/{ref}`                 | seating, for a link preview                    |
| POST   | `/api/v1/matches/{ref}/claim`           | take a seat with a Lobby seat JWT              |
| GET    | `/api/v1/resume`                        | recovery path 1 — this browser's own binding   |
| GET    | `/api/v1/players/{lobbyUserId}/history` | what this person has played                    |
| WS     | `/api/v1/ws`                            | authoritative state out, seat commands in      |

### Two modes, and why the demo is one of them

The production match is **first to three round wins**, with a base destroyed
ending the match on the spot and no base recovery between rounds. That is
`starter`.

The opening demo plays exactly **one round**, and it is its own mode —
`opening-round` — rather than a flag on `starter`. A single round reported
through the production mode would be indistinguishable, in every downstream
rating and standings table, from a best-of-five somebody actually won. So the
demo reports a `testComplete` ending on the wire and `CANCELLED` — unrated — to
the Lobby, with the round winner carried in metadata so the run is still legible.

A destroyed base is the exception: it is a real terminal outcome even in a demo,
and is reported as `baseDestroyed` with the remaining base HP, rather than as
"the test finished".

### The wire contract

[`api/app/match/wire.py`](api/app/match/wire.py) is every byte that crosses
between server and client, and it is deliberately **not** `sim/serialize.py`.
That module renders a finished battle as canonical text so two runs can be
compared byte for byte; it is total (it carries the opponent's energy and
unlocked plan), it is frozen for a different reason, and it describes a whole
battle rather than a tick. `tests/match/test_wire.py` asserts on the import graph
that nothing outside the sim and the headless demo reaches for it.

Reading this next to the TypeScript references: see
[`docs/python-vs-typescript.md`](docs/python-vs-typescript.md), which maps every
module to its rpslr counterpart and names the handful of genuine language
differences.

---

## The battle sim

The battle phase is auto-resolved and server-authoritative, so the sim runs
headless and deterministically at a fixed tick rate (design doc §6). It lives in
[`api/app/sim/`](api/app/sim) and is a **pure module**: no I/O, no wall clock, no
rendering imports, no randomness that is not seeded.

```python
from app.sim import THREE_ZONE_MAP, placeholder_battle, run_battle

result = run_battle(THREE_ZONE_MAP, [], placeholder_battle(), seed)
#   result.ticks          - tick-by-tick state, starting with the opening state
#   result.events         - the event stream, every event carrying the swing it caused
#   result.outcome        - why the battle stopped
#   result.destroyed_base - whose base fell, on a `baseDestroyed` outcome
#   result.base_hp        - what each base has left, to carry into the next round
```

Same inputs and seed, byte-identical state and events — in this process and in a
fresh one. Three tests hold that seam shut, and all three are worth knowing about
before adding to the sim:

| Guard | What it enforces |
|---|---|
| `tests/test_purity.py` | Parses the import graph from `app/sim/__init__.py` with `ast`: nothing that reaches the outside world, nothing under `app.` outside `app.sim`, no `print`/`open`/`eval` |
| `tests/test_determinism.py` | Two runs in one process, plus **five fresh interpreters** that must all agree |

The port also shipped with `tests/sim/test_golden_parity.py`, which replayed two
battles captured from the original TypeScript sim. Those vectors pinned slice A's
movement rule — everybody marches at the enemy base — which slice B (JQ-287)
replaces with orders and derived formations, so they were retired once they had
done their job. The PRNG vectors in `tests/sim/test_rng.py` are a different claim
and still stand.

### Two Python rules this sim lives by

Both are specific to Python and neither existed as a hazard in the TypeScript
this was ported from, where object key order is specified and `Set` iterates in
insertion order.

1. **Never iterate an unordered collection.** Python randomises string hashing per
   process (`PYTHONHASHSEED`), so `set` iteration order differs between
   interpreters. A sim that iterates a set passes every in-process test and
   diverges between two servers running identical code. Sets are used for
   membership only.
2. **Never use module-level `random`.** It is process-global shared state.
   Randomness comes from an explicit `Rng` threaded through the tick context.

`test_determinism.py` is what keeps rule 1 honest, and it only works because it
shells out to real child processes — pytest runs a whole suite in one
interpreter, so an in-process check samples a single hash seed and always agrees.
It also asserts `PYTHONHASHSEED` is unpinned, because pinning it in CI would make
the check pass while disarming it everywhere.

### Orders, not placements

A plan gives each troop exactly one **order** — hold a zone, defend your own base,
push the enemy's — and nothing else. Where its units stand, which rank they are
in and how far the mages sit behind the summon line are all derived from that
order and the map, which is what keeps the plan phase to three taps on a phone
(JQ-190).

```python
from app.sim import THREE_ZONE_MAP, hold, legal_orders, DEFEND_BASE, PUSH_ENEMY_BASE

legal_orders(THREE_ZONE_MAP)   # hold A, hold B, hold C, defend base, push enemy base
TroopSetup(order=hold("B"), mages=[...], summons=[...])
```

`tests/sim/test_orders.py` asserts directly that no placement, stance or facing
input exists anywhere a plan can reach. A field that let one in would break no
other test — everything would still run, and the plan phase would quietly stop
being three taps — so the constraint is checked rather than trusted.

### Lanes and hotspots

Zones are **lanes, divided west to east** — they run alongside the attack axis
rather than across it, so every lane is the same distance from both bases. The
earlier layout stacked them north to south, which handed each side a zone next to
its own deployment strip that the enemy never reached. That was free income
nobody had to fight for, and farming it beat every other line: a mirror ended
1795-1795 on every seed, and a player who committed everything to the contested
middle lost by 1633.

Scoring sits on a **hotspot** at the centre of each lane, and only a **mage**
standing in it holds anything. A lane is a big box and a straggler in the corner
of one would be enough to deny it, so the test is a small square in the middle of
the map — and requiring the mage means the summon screen has to have won that
ground first, with the troop's slowest and most fragile unit now standing in the
open. Denial is a combat outcome rather than an occupancy technicality.

A lane is held when **exactly one** side has a living mage in its hotspot;
contested and empty lanes pay nobody, and ownership is not sticky.

Two lanes rather than three is a decision about the plan, not the map: you open at
three mages, and three troops into two lanes forces you to double up somewhere
and your opponent to guess where.

Only troops under Push enemy base may attack a base, and a base reaching zero
ends the whole match rather than the round. Base HP never recovers:
`result.base_hp` goes straight back into the next round's `BattleSetup.base_hp`.

The per-tick **phase order** is declared in one place,
[`app/sim/phases/__init__.py`](api/app/sim/phases/__init__.py). Adding behaviour
to the battle means adding a phase to that list, not threading logic through the
loop.

Watch a battle resolve:

```bash
cd api && python -m app.scripts.battle_demo --seed 7
```

stdout is the canonical event stream (so two runs can be diffed); the summary on
stderr says who won.

### Behaviour: what a creature wants, and who its mage asks

Every unit runs one shared loop — observe, generate legal candidates, score,
select — and the decision phase commits an intent that the existing movement and
combat phases carry out. Adding a creature that uses existing mechanics costs
data, not code: nothing in [`app/sim/ai/`](api/app/sim/ai) branches on a creature
id.

A unit's weights come from three places, summed and clamped: its stat block's
own **contour** (tough and slow absorbs; quick and frail evades), any authored
**creature profile and traits**, and the **personalities** of its troop's mages.

**Personalities are contextual, not one aggression slider.** A tag is a set of
rules, each naming the situation it speaks to, the actions it is eligible on,
the priorities it moves, how far it looks, and its exceptions:

```python
PersonalityRule(when="ally-threatened", weights={"target_suitability": 1.0, "danger": -0.5})
```

That shape exists because the flat one has a failure it cannot be tuned out of.
`reckless` discounting danger and `protective` pricing it add to zero, so a mage
that is both comes out identical to a mage that is neither — and "willingness to
take risks defending allies" is exactly what the pair is supposed to mean. Rules
fix it twice over: the two tags speak in different moments, and `protective`'s
danger delta is *negative* where an ally is being hurt, because caring about
allies is not the same idea as fearing for yourself. Strength scales what a tag
contributes and nothing else; zero means no opinion, never the opposite one.

**A lightweight troop coordinator** allocates. It looks for enemies hurting its
own, and asks one unit — the nearest eligible, deterministically — to answer
each. That is its whole output: a target, never a position, so a melee guard and
an archer answer the same assignment in the only ways each of them can. It never
writes a destination, never overrides a capability, never commits more than half
a troop, and releases the moment the defender, the target or the ally it was
protecting dies or moves out of eligibility. A troop that has lost its last mage
coordinates nothing, which is JQ-289's dissolve arriving where it should.

```bash
cd api && python -m app.scripts.battle_demo --seed 7   # both sides are led differently
```

**Scope.** Slice A (JQ-286) ships the world model, the tick loop, map config, the
event envelope, and move-and-fight. Orders, formations, and zone scoring are
JQ-287; energy and abilities JQ-288; resummoning and resonance JQ-289.

---

## Containers and deploy

Both images build with the **repo root** as their Docker context, so the root
`.dockerignore` is the single authority on what reaches the daemon — including
keeping sibling agent worktrees under `.claude/` out of it.

```bash
./scripts/build-and-push.sh           # build both images
./scripts/build-and-push.sh --push    # and push (needs a registry login)
```

The build refuses a dirty tree by default: the context is the working tree, so
an uncommitted edit would ship in the image with nothing in git recording it.

The client image is **environment-agnostic**. It serves the static build through
nginx, and `docker-entrypoint.d/40-env-js.sh` rewrites `/env.js` from the
container's environment at startup. The app reads `window.env`, never
`import.meta.env` — a build-time value would pin one image to whichever
environment built it. One image therefore runs in local, staging and production.

```bash
./scripts/deploy-local.sh        # kind / minikube / docker-desktop
./scripts/deploy-staging.sh
./scripts/deploy-production.sh   # prompts for confirmation
```

Each applies, in order: namespace → secrets → ConfigMap overlay → TLS
certificate → base workloads → ingress overlay → digest-pinned images → wait for
rollout → check `/healthz`. Images are pinned by digest because a mutable tag
alone lets a cluster reuse a cached layer from an earlier push of the same name.

Before a first deploy, fill in the secrets:

```bash
cp k8s/secrets/pg-dsn.example.yaml     k8s/secrets/pg-dsn.yaml
cp k8s/secrets/joinquest.example.yaml  k8s/secrets/joinquest.yaml
```

Both are gitignored, and `environment-config-test.yml` fails the build if a
non-example secret is ever committed.

> **Hostnames are placeholders.** `go-forth.staging.joinquest.cc` and
> `go-forth.example` are not registered and do not resolve. Pick real names,
> point A records at the ingress controller, and change each in three files
> together — `k8s/env/<env>.yaml`, `<env>-ingress.yaml`, and
> `<env>-certificate.yaml` — or cert-manager will issue for a name nothing
> routes to. CI checks the last two agree.

---

## Still out of scope

**The client still talks to its own fixture.** JQ-309 built the server side of
the transport — the contract endpoints, the wire schema and the authoritative
session over WebSocket — and `client/src/match/session.ts` has not been pointed
at it yet. That swap is JQ-311's, and it carries two renames with it: the client
was written against a three-zone map (`A`/`B`/`C`) before JQ-376 made it two
lanes (`W`/`E`), and it spells the hold order `hold` where the sim spells it
`holdZone`. The server's names are authoritative.

Reclaim, command deduplication and reproducible diagnostics are **JQ-310**; live
state is held in memory and is not restored from a row if the process restarts.
Green dashboard checks and the integrated two-phone smoke test are **JQ-313**.

Battle-map readability at density — occupancy chips, mage energy rings,
tap-to-inspect, the twenty-a-side case — is **JQ-312**. The demo's renderer
draws the authoritative state plainly and holds that seam open; it does not
pre-empt that design.
