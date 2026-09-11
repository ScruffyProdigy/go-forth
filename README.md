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
│   │   ├── app.test.ts
│   │   ├── sim/              # the battle sim — pure, deterministic, headless
│   │   └── scripts/
│   │       └── battleDemo.ts # runs a battle, prints the event stream
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
are JQ-188.

---

## The battle sim

The battle phase is auto-resolved and server-authoritative, so the sim runs
headless and deterministically at a fixed tick rate (design doc §6). It lives in
[`api/src/sim/`](api/src/sim) and is a **pure module**: no I/O, no wall clock, no
rendering imports, no `Math.random`.

```ts
import { THREE_ZONE_MAP, placeholderBattle, runBattle } from './sim/index.js';

const result = runBattle(THREE_ZONE_MAP, [], placeholderBattle(), seed);
//    result.ticks    — tick-by-tick state, starting with the opening state
//    result.events   — the event stream, every event carrying the swing it caused
//    result.outcome  — why the battle stopped
```

Same inputs and seed, byte-identical state and events — in this process and in a
fresh one. Two tests hold that seam shut, and both are worth knowing about before
adding to the sim:

| Guard | What it enforces |
|---|---|
| `sim/purity.test.ts` | Walks the import graph from `sim/index.ts`: nothing from `node:`, nothing outside `sim/`, no clock, no `console`, no `Math.random` |
| `sim/determinism.test.ts` | Two runs in one process and one in a fresh process all serialise identically |

The per-tick **phase order** is declared in one place, [`sim/phases.ts`](api/src/sim/phases.ts).
Adding behaviour to the battle means adding a phase to that list, not threading
logic through the loop.

Watch a battle resolve:

```bash
cd api && npm run sim:demo -- --seed 7
```

stdout is the canonical event stream (so two runs can be diffed); the summary on
stderr says who won.

**Scope.** Slice A (JQ-286) ships the world model, the tick loop, map config, the
event envelope, and move-and-fight. Orders, formations, and zone scoring are
JQ-287; energy and abilities JQ-288; resummoning and resonance JQ-289.

---

## Out of scope for this scaffold

Postgres, migrations, docker-compose, Dockerfiles, k8s, and deploy scripts all
belong to the runtime and deploy ticket (JQ-285).
