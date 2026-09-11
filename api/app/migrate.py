"""Forward-only SQL migration runner.

Applies every `*.sql` file in `api/migrations` exactly once, in filename order,
each in its own transaction, recording what it applied in `schema_migrations`.
Re-running is a no-op, which is what lets the same command serve
`scripts/db.sh migrate` locally and the `migrate` initContainer on every
Kubernetes rollout.

`.down.sql` files are ignored: they exist to be applied by hand when a
migration has to be walked back, never automatically.

Deliberately not Alembic. The only difference between JoinQuest's reference
games should be the language, not the architecture — someone comparing rpslr to
go-forth to learn the integration contract should not have to learn a migration
framework on the way. See `api/CONVENTIONS.md`.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

import psycopg

from app.config import Config

#: Migrations sit beside the package in both a checkout and the image.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def select_pending_migrations(filenames: Iterable[str], applied: Iterable[str]) -> list[str]:
    """The pending set, in apply order.

    Split out from the runner so the ordering and filtering rules are testable
    without a database — they are the part that silently corrupts a schema when
    wrong, and the part a `.down.sql` file trips up.
    """
    done = set(applied)
    return sorted(
        name
        for name in filenames
        if name.endswith(".sql") and not name.endswith(".down.sql") and name not in done
    )


def migrate(conn: psycopg.Connection[tuple[str, ...]], migrations_dir: Path = MIGRATIONS_DIR) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                 filename   TEXT PRIMARY KEY,
                 applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
        conn.commit()

        cur.execute("SELECT filename FROM schema_migrations")
        applied = [row[0] for row in cur.fetchall()]

    pending = select_pending_migrations(
        (path.name for path in migrations_dir.iterdir()),
        applied,
    )

    for filename in pending:
        sql = (migrations_dir / filename).read_text(encoding="utf-8")
        print(f"[migrate] applying {filename}")
        # One transaction per file: a migration that fails leaves nothing of
        # itself behind, and is retried whole on the next run.
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (filename,))

    return len(pending)


def main() -> None:
    config = Config.from_env()
    try:
        with psycopg.connect(config.database_url) as conn:
            applied = migrate(conn)
    # Broad on purpose: this is the process entry point, and its job is to
    # turn any failure into a readable line and a non-zero exit rather than a
    # traceback in a Kubernetes init log.
    except Exception as err:
        print(f"[migrate] failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err

    print("[migrate] already up to date" if applied == 0 else f"[migrate] applied {applied} migration(s)")


if __name__ == "__main__":
    main()
