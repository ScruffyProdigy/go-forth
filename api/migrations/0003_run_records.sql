-- Go Forth! — reproducible run records (JQ-310).
--
-- One row per finished run: everything that run's battles were a function of,
-- as written by `app/match/run_record.py`. `replay_run` re-runs it headlessly,
-- which is how "my spell didn't land" gets an answer after both phones have
-- gone home.
--
-- Stored as JSONB and not as columns, deliberately. The document is versioned
-- by its own `recordVersion`, `rulesVersion` and `contentVersion`, and those
-- move while the milestone is being built — a normalised schema would mean a
-- migration per rules change and, worse, records rewritten to fit the new
-- shape. A record that was edited to keep loading is no longer evidence of
-- what happened. So: the document is opaque here, and the five things we
-- actually query on are lifted out beside it.
--
-- What is *not* in a record, and must never be added: `players.id` (the
-- gameplay credential a socket subscribes with), Lobby service tokens, seat
-- JWTs, return URLs. A run record is read by someone investigating a match
-- rather than playing in one. `app/match/diagnostics.py` refuses the same
-- field names for the same reason.

CREATE TABLE IF NOT EXISTS match_runs (
  -- The run id, which is minted per provision. A fresh demo run carries
  -- nothing over from the last one, so this — not the match id — is the key a
  -- replay is asked for.
  run_id            TEXT PRIMARY KEY,
  -- Kept as text rather than a foreign key to `matches(id)`: a record should
  -- survive its match row being cleaned up, since the record is the part with
  -- evidentiary value. Indexed below so "what ran for this match" is still one
  -- query.
  external_match_id TEXT NOT NULL,
  record_version    INTEGER NOT NULL,
  rules_version     INTEGER NOT NULL,
  content_version   INTEGER NOT NULL,
  -- How the run stopped, in the wire's vocabulary: baseDestroyed | abandoned |
  -- zoneControl | annihilation | timeUp. Lifted out of the document because
  -- "find me the runs that ended on a destroyed base" is the first question
  -- anyone asks of these (Ryan, 2026-09-13).
  terminal_reason   TEXT,
  record            JSONB NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_match_runs_match ON match_runs(external_match_id);
CREATE INDEX IF NOT EXISTS idx_match_runs_terminal ON match_runs(terminal_reason, created_at DESC);
