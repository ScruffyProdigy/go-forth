-- Go Forth! — initial schema.
--
-- This lives in the GAME's own database (host port 5434), never the Lobby's
-- (5432) and never rpslr's (5433).
--
-- Scope note: the session layer proper — game modes, provisioning, launch
-- URLs, ranked results — is JQ-188, and the battle sim's own persistence is
-- JQ-286's to specify. What is here is only the seating model every JoinQuest
-- game needs regardless of how those land: a match, the seats that make it up,
-- and the players who claim them. It is deliberately generic so a later
-- migration extends it rather than rewrites it.
--
--   match -> seats (optional team + role, optionally reserved for a specific
--   Lobby user) -> a player claims a seat.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS matches (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code               TEXT NOT NULL UNIQUE,          -- short self-serve join code
  external_match_id  TEXT UNIQUE,                   -- Lobby's matchId (NULL in standalone)
  name               TEXT NOT NULL,
  game_mode          TEXT NOT NULL DEFAULT 'skirmish',
  status             TEXT NOT NULL DEFAULT 'waiting'
                       CHECK (status IN ('waiting', 'playing', 'finished')),
  -- Free-form so JQ-188 can add mode settings without a migration per knob.
  config             JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seats are the slot template for a match. A seat may be reserved for a
-- specific Lobby user (set by a Lobby-pushed assignment); in standalone mode
-- the reservation is NULL and any arriving player may claim an open seat.
CREATE TABLE IF NOT EXISTS seats (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id                 UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  seat_key                 TEXT NOT NULL,           -- 'a', 'b', 'fire', ...
  team_key                 TEXT,                    -- nullable team grouping
  role                     TEXT,                    -- nullable human role/label
  position                 INTEGER NOT NULL,        -- stable ordering
  reserved_for_lobby_user  TEXT,                    -- nullable Lobby user id
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (match_id, seat_key)
);

-- A player occupies exactly one seat (UNIQUE seat_id). lobby_user_id is set
-- when the player arrived through the Lobby; NULL in standalone mode.
CREATE TABLE IF NOT EXISTS players (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id       UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  seat_id        UUID NOT NULL UNIQUE REFERENCES seats(id) ON DELETE CASCADE,
  name           TEXT NOT NULL,
  lobby_user_id  TEXT,
  joined_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (match_id, lobby_user_id)
);

CREATE INDEX IF NOT EXISTS idx_seats_match ON seats(match_id);
CREATE INDEX IF NOT EXISTS idx_players_match ON players(match_id);
