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
        via Lobby JWKS                │                       │  (JQ-285)      │ │
                                      └──────────────────────────────────────────┘
```

The game owns its client, API, and (soon) database. The Lobby owns auth, the game
catalog, and matchmaking. The battle sim is **server-authoritative** — the client
renders server state and never simulates ahead of it.

---

## Port plan (avoids Lobby and rpslr collisions)

| Service  | Go Forth! | rpslr | Lobby | Notes                          |
|----------|-----------|-------|-------|--------------------------------|
| Client   | **5175**  | 5174  | 5173  | Vite dev server                |
| API      | **3002**  | 3001  | 8080  | FastAPI + Python 3.12          |
| Postgres | **5434**  | 5433  | 5432  | game's own DB — arrives JQ-285 |

All ports are documented in [`.env.example`](.env.example). The offsets are
deliberate: all three services can run at once on one machine.

---

## Quick start

Requires **Python 3.12** for the api and **Node 20 LTS** for the client. The
two are independent packages, each with its own dependency file, installed
separately.

```bash
cp .env.example .env

cd api
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m app.server                      # API on :3002

cd client && npm install && npm run dev   # Client on :5175
```

[uv](https://docs.astral.sh/uv/) reads the same `pyproject.toml` and is faster
if you have it, but nothing requires it.

Then open **http://localhost:5175**. Today that is a placeholder screen — the
real client lands with JQ-190.

### Run the tests

```bash
cd api    && ruff check . && ruff format --check . && mypy app tests && pytest
cd client && npm run lint && npm run typecheck && npm test
```

---

## Repo layout

```
.
├── README.md
├── .env.example              # all ports + config documented here
├── api/                      # Python 3.12 game server (FastAPI)
│   ├── pyproject.toml        # deps, ruff, mypy and pytest config in one file
│   ├── CONVENTIONS.md        # determinism + porting rules — read before the sim
│   ├── app/
│   │   ├── main.py           # FastAPI factory (no bind) — what tests exercise
│   │   ├── server.py         # binds the port
│   │   └── config.py
│   └── tests/                # outside the package, per Python convention
├── client/                   # Vite + React 18 game UI
│   └── src/
│       ├── App.tsx
│       ├── App.test.tsx
│       └── test/setup.ts
└── .github/workflows/        # api-tests, client-tests (each path-filtered)
```

---

## Game API

| Method | Path       | Description        |
|--------|------------|--------------------|
| GET    | `/healthz` | returns `200 ok`   |

That is the whole surface for now, on purpose. Session and integration endpoints
are JQ-188; the sim is JQ-186.

---

## Out of scope for this scaffold

Postgres, migrations, docker-compose, Dockerfiles, k8s, and deploy scripts all
belong to the runtime and deploy ticket (JQ-285). There is no game logic here
beyond `/healthz`.
