# Go Forth! — JoinQuest game

A light **mini-RTS with no click race**: you plan, you deploy, and then you watch
your plan meet theirs. Rounds alternate between a planning phase and an
auto-resolved battle. Armies are troops of mages and summons, the objective is
zone control with base destruction as the punish, and spells draw on one
regenerating energy pool.

Phone-first, portrait, tap-only. Entry is via the [JoinQuest Lobby](https://joinquest.cc),
using the same integration shape as [rpslr](https://github.com/ScruffyProdigy/rpslr).

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
│  Go GraphQL  :8080  ──────┼─playUrl─┼─▶ │  Vite/React │HTTP │  Express/TS   │  │
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
| API      | **3002**  | 3001  | 8080  | Express + TypeScript           |
| Postgres | **5434**  | 5433  | 5432  | game's own DB — arrives JQ-285 |

All ports are documented in [`.env.example`](.env.example). The offsets are
deliberate: all three services can run at once on one machine.

---

## Quick start

Requires **Node 20 LTS** and **npm**. `api/` and `client/` are independent
packages with their own `package.json` and lockfile — there is no npm workspace,
so install each one separately (this matches rpslr).

```bash
cp .env.example .env

cd api && npm install && npm run dev      # API on :3002
cd client && npm install && npm run dev   # Client on :5175
```

Then open **http://localhost:5175**. Today that is a placeholder screen — the
real client lands with JQ-190.

### Run the tests

```bash
cd api    && npm run lint && npm run typecheck && npm test
cd client && npm run lint && npm run typecheck && npm test
```

---

## Repo layout

```
.
├── README.md
├── .env.example              # all ports + config documented here
├── api/                      # Node 20 + TypeScript game server (Express)
│   ├── src/
│   │   ├── app.ts            # express app (no listen) — what tests exercise
│   │   ├── server.ts         # binds the port
│   │   └── app.test.ts
│   ├── tsconfig.json         # build config: src only, emits to dist/
│   └── tsconfig.typecheck.json  # noEmit, and covers the tests too
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
