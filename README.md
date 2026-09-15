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
round, lock it in, watch the battle resolve, read the result. It runs on a
**fixture session**, not the server — the Lobby contract and the authoritative
realtime session are JQ-309, and until they land `client/src/match/fixtures/`
stands in for both.

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
`stub-lobby.sh provision` pushes a match assignment at `POST /api/v1/matches`,
which JQ-188 builds — until then it reports the 404 and prints the payload it
would have sent.

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
│   │   ├── sim/              # the battle sim — pure, deterministic, headless
│   │   └── scripts/
│   │       └── battle_demo.py  # runs a battle, prints the event stream
│   └── tests/                # outside the package, per Python convention
│       └── sim/              # the sim's own suite, mirroring app/sim/
├── client/                   # Vite + React 18 game UI
│   ├── Dockerfile            # static build served by nginx
│   ├── nginx.conf            # SPA routing + the cache policy a deploy needs
│   ├── docker-entrypoint.d/  # writes /env.js from container env at startup
│   ├── public/env.js         # the same config, with local dev defaults
│   └── src/
│       ├── plan/             # the plan phase (JQ-293)
│       └── match/            # the match flow: session seam, battle, result
│           └── fixtures/     # stands in for the server until JQ-309
├── k8s/
│   ├── base/                 # namespace, api, client, postgres, ingress
│   ├── env/                  # per-environment ConfigMaps, ingress, TLS certs
│   └── secrets/              # *.example.yaml only; real ones are gitignored
├── scripts/                  # setup, dev, db, test, stub-lobby, build, deploy
└── .github/workflows/        # api-tests, client-tests, environment-config-test
```

---

## Game API

| Method | Path       | Description        |
|--------|------------|--------------------|
| GET    | `/healthz` | returns `200 ok`   |

That is the whole surface for now, on purpose. Session and integration endpoints
are JQ-188.

---

## The battle sim

The battle phase is auto-resolved and server-authoritative, so the sim runs
headless and deterministically at a fixed tick rate (design doc §6). It lives in
[`api/app/sim/`](api/app/sim) and is a **pure module**: no I/O, no wall clock, no
rendering imports, no randomness that is not seeded.

```python
from app.sim import THREE_ZONE_MAP, placeholder_battle, run_battle

result = run_battle(THREE_ZONE_MAP, [], placeholder_battle(), seed)
#   result.ticks    - tick-by-tick state, starting with the opening state
#   result.events   - the event stream, every event carrying the swing it caused
#   result.outcome  - why the battle stopped
```

Same inputs and seed, byte-identical state and events — in this process and in a
fresh one. Three tests hold that seam shut, and all three are worth knowing about
before adding to the sim:

| Guard | What it enforces |
|---|---|
| `tests/test_purity.py` | Parses the import graph from `app/sim/__init__.py` with `ast`: nothing that reaches the outside world, nothing under `app.` outside `app.sim`, no `print`/`open`/`eval` |
| `tests/test_determinism.py` | Two runs in one process, plus **five fresh interpreters** that must all agree |
| `tests/test_golden_parity.py` | Replays two battles captured from the original TypeScript sim and checks every defeat, tick, position and survivor |

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

No game logic beyond `/healthz`: the client's opening demo talks to a fixture,
not to this api. The session layer and JoinQuest integration endpoints are
JQ-188 and JQ-309, and the battle the client renders will come from the sim's
slices (JQ-287 onwards) rather than from `client/src/match/fixtures/`.

Battle-map readability at density — occupancy chips, mage energy rings,
tap-to-inspect, the twenty-a-side case — is **JQ-312**. The demo's renderer
draws the authoritative state plainly and holds that seam open; it does not
pre-empt that design.
