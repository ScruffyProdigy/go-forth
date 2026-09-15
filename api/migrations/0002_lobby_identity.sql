-- Go Forth! — Lobby identity and match history (JQ-309).
--
-- 0001 gave us the seating model every JoinQuest game needs: a match, its
-- seats, and the players who claim them. This adds the two things the session
-- layer needs on top of it, both keyed by **Lobby user id** rather than by our
-- own player row.
--
-- Why that key: our `players.id` is minted per match, so a player who has
-- played six matches is six rows with nothing linking them. The Lobby user id
-- is the only identifier that is the same person across matches, which makes it
-- the only key a history can hang off. It is also the `sub` of every seat
-- token, so the join from an incoming claim is direct.
--
--   lobby_players  one row per person we have ever seated
--   match_results  one row per finished match, per person
--
-- `matches` gains the columns the session layer decides with. They are added
-- rather than replacing `config`, because the ones below are queried — a run
-- id you cannot filter on is not much use for finding a demo run again.

ALTER TABLE matches
  ADD COLUMN IF NOT EXISTS run_id        TEXT,
  ADD COLUMN IF NOT EXISTS lobby_issuer  TEXT,
  ADD COLUMN IF NOT EXISTS return_url    TEXT,
  ADD COLUMN IF NOT EXISTS graphql_url   TEXT,
  -- Whether this match ran under a test profile. Persisted rather than derived
  -- from `game_mode` at read time: the mode's policy may be retuned, and a run
  -- recorded months ago must keep saying what it actually was.
  ADD COLUMN IF NOT EXISTS test_profile  BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS finished_at   TIMESTAMPTZ,
  -- Set once the Lobby has acknowledged `reportMatchResult`. A match that
  -- finished while the Lobby was unreachable is exactly the row a retry sweep
  -- needs to find, so "finished" and "reported" are two columns, not one.
  ADD COLUMN IF NOT EXISTS reported_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_matches_run ON matches(run_id);
-- Partial: the sweep only ever asks for finished-and-unreported, and a full
-- index on two nullable timestamps would be mostly rows it never reads.
CREATE INDEX IF NOT EXISTS idx_matches_unreported
  ON matches(finished_at)
  WHERE finished_at IS NOT NULL AND reported_at IS NULL;

-- One row per person the Lobby has ever sent us.
CREATE TABLE IF NOT EXISTS lobby_players (
  lobby_user_id  TEXT PRIMARY KEY,
  -- Last name we resolved for them. Not authoritative and not unique: the Lobby
  -- owns display names, and this is a cache so a history row can be read
  -- without a round trip to a Lobby that may be gone.
  display_name   TEXT NOT NULL,
  first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  matches_played INTEGER NOT NULL DEFAULT 0
);

-- What became of one person in one match.
CREATE TABLE IF NOT EXISTS match_results (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  match_id       UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  lobby_user_id  TEXT NOT NULL REFERENCES lobby_players(lobby_user_id) ON DELETE CASCADE,
  seat_key       TEXT NOT NULL,
  side           TEXT NOT NULL CHECK (side IN ('north', 'south')),
  -- How the *match* ended, in the wire contract's own vocabulary:
  -- baseDestroyed | roundsWon | testComplete | abandoned. Stored as the wire
  -- spells it so a history row and a result screen cannot drift apart.
  ending         TEXT NOT NULL,
  won            BOOLEAN,               -- NULL on a draw or an unfinished match
  rounds_won     INTEGER NOT NULL DEFAULT 0,
  base_hp        DOUBLE PRECISION,      -- what this side's base had left
  test_profile   BOOLEAN NOT NULL DEFAULT FALSE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- One result per person per match. A re-report updates rather than stacking,
  -- which is what makes the lifecycle retry idempotent in our own store as well
  -- as in the Lobby's.
  UNIQUE (match_id, lobby_user_id)
);

CREATE INDEX IF NOT EXISTS idx_match_results_player ON match_results(lobby_user_id, created_at DESC);
