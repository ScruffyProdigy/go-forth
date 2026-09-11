"""Migration selection rules.

The database round trip is exercised by `scripts/db.sh migrate` against a real
Postgres; what is worth pinning here is the ordering and filtering, because
that is the part that silently corrupts a schema when it is wrong.
"""

from app.migrate import select_pending_migrations


def test_orders_by_filename_not_by_directory_order() -> None:
    files = ["0010_later.sql", "0002_second.sql", "0001_init.sql"]
    assert select_pending_migrations(files, []) == [
        "0001_init.sql",
        "0002_second.sql",
        "0010_later.sql",
    ]


def test_skips_what_is_already_recorded() -> None:
    files = ["0001_init.sql", "0002_second.sql"]
    assert select_pending_migrations(files, ["0001_init.sql"]) == ["0002_second.sql"]


def test_is_a_no_op_once_everything_is_applied() -> None:
    files = ["0001_init.sql", "0002_second.sql"]
    assert select_pending_migrations(files, files) == []


def test_never_applies_a_down_migration() -> None:
    # A `.down.sql` applied automatically would drop the table its `.up.sql`
    # sibling had just created, and the filename sort puts it immediately after.
    files = ["0002_thing.up.sql", "0002_thing.down.sql"]
    assert select_pending_migrations(files, []) == ["0002_thing.up.sql"]


def test_ignores_non_sql_files() -> None:
    files = ["0001_init.sql", "README.md", ".DS_Store"]
    assert select_pending_migrations(files, []) == ["0001_init.sql"]


def test_the_real_migrations_directory_is_selectable() -> None:
    # Guards the packaging: the SQL is read at runtime rather than compiled, so
    # an image that fails to ship api/migrations builds fine and then fails
    # every rollout at the init step.
    from app.migrate import MIGRATIONS_DIR

    names = [path.name for path in MIGRATIONS_DIR.iterdir()]
    assert select_pending_migrations(names, []) == ["0001_init.sql"]
