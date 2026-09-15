"""The Postgres repository.

psycopg 3, plain SQL, no ORM — the same reasoning as the plain-SQL migrations
(`api/CONVENTIONS.md`): someone reading this to learn the JoinQuest contract
should not have to learn a data-mapper first.

Connections come from a pool rather than one per request, because the WebSocket
path holds a request open for the length of a match and would otherwise hold a
connection with it.

Every method here has a `MemoryRepository` twin, and the twin is what CI runs.
That is a real gap: a query that is wrong only against real Postgres — a
constraint violation, a column that does not exist — will not fail the suite CI
has. The `.pg.` naming convention in `tests/` is for tests that need a database
and skip without one, and `scripts/db.sh` is how you get one locally.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.repository import (
    ClaimResult,
    ConflictError,
    NotFoundError,
    ReservationError,
    StoredMatch,
    StoredResult,
    StoredSeat,
)


def _short_code() -> str:
    """A short, human-sayable join code. Collides rarely; the unique index decides."""
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
    return "GF-" + "".join(secrets.choice(alphabet) for _ in range(4))


class PgRepository:
    """Matches, seats, players and results in Postgres."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row)

    async def upsert_match(
        self,
        *,
        external_match_id: str,
        game_mode: str,
        run_id: str,
        test_profile: bool,
        seats: Sequence[tuple[str, str | None]],
        lobby_issuer: str | None,
        return_url: str | None,
        graphql_url: str | None,
        service_token: str | None,
    ) -> StoredMatch:
        async with await self._connect() as conn, conn.cursor() as cur:
            # `ON CONFLICT DO UPDATE` rather than a SELECT-then-INSERT: two
            # concurrent pushes of the same match is exactly what Lobby's retry
            # produces, and the read-then-write version loses that race.
            await cur.execute(
                """
                INSERT INTO matches
                  (code, external_match_id, name, game_mode, status, config,
                   run_id, lobby_issuer, return_url, graphql_url, test_profile)
                VALUES (%s, %s, %s, %s, 'waiting', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (external_match_id) DO UPDATE SET
                  return_url  = COALESCE(EXCLUDED.return_url,  matches.return_url),
                  graphql_url = COALESCE(EXCLUDED.graphql_url, matches.graphql_url)
                RETURNING id, external_match_id, game_mode, run_id, test_profile,
                          lobby_issuer, return_url, graphql_url, status,
                          finished_at, reported_at, (xmax = 0) AS inserted
                """,
                (
                    _short_code(),
                    external_match_id,
                    f"Go Forth! {external_match_id}",
                    game_mode,
                    json.dumps({}),
                    run_id,
                    lobby_issuer,
                    return_url,
                    graphql_url,
                    test_profile,
                ),
            )
            row = await cur.fetchone()
            assert row is not None
            match_id = str(row["id"])

            if row["inserted"]:
                for position, (seat_key, reserved) in enumerate(seats):
                    await cur.execute(
                        """
                        INSERT INTO seats (match_id, seat_key, position, reserved_for_lobby_user)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (match_id, seat_key) DO NOTHING
                        """,
                        (match_id, seat_key, position, reserved),
                    )
            await conn.commit()

        found = await self.get_match(external_match_id)
        assert found is not None  # just written
        return found

    async def get_match(self, external_match_id: str) -> StoredMatch | None:
        async with await self._connect() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, external_match_id, game_mode, run_id, test_profile, lobby_issuer,
                       return_url, graphql_url, status, finished_at, reported_at
                  FROM matches WHERE external_match_id = %s
                """,
                (external_match_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return None

            await cur.execute(
                """
                SELECT s.seat_key, s.position, s.reserved_for_lobby_user,
                       p.id AS player_id, p.name AS player_name, p.lobby_user_id
                  FROM seats s
             LEFT JOIN players p ON p.seat_id = s.id
                 WHERE s.match_id = %s
              ORDER BY s.position
                """,
                (row["id"],),
            )
            seat_rows = await cur.fetchall()

        return StoredMatch(
            id=str(row["id"]),
            external_match_id=row["external_match_id"],
            game_mode=row["game_mode"],
            run_id=row["run_id"] or "",
            test_profile=bool(row["test_profile"]),
            lobby_issuer=row["lobby_issuer"],
            return_url=row["return_url"],
            graphql_url=row["graphql_url"],
            status=row["status"],
            finished_at=row["finished_at"],
            reported_at=row["reported_at"],
            seats=[
                StoredSeat(
                    seat_key=seat["seat_key"],
                    position=seat["position"],
                    reserved_for_lobby_user=seat["reserved_for_lobby_user"],
                    player_id=str(seat["player_id"]) if seat["player_id"] else None,
                    player_name=seat["player_name"],
                    lobby_user_id=seat["lobby_user_id"],
                )
                for seat in seat_rows
            ],
        )

    async def claim_seat(
        self,
        *,
        external_match_id: str,
        seat_key: str,
        lobby_user_id: str | None,
        display_name: str,
    ) -> ClaimResult:
        async with await self._connect() as conn, conn.cursor() as cur:
            await cur.execute("SELECT id FROM matches WHERE external_match_id = %s", (external_match_id,))
            match_row = await cur.fetchone()
            if match_row is None:
                raise NotFoundError("match not found")
            match_id = str(match_row["id"])

            # `FOR UPDATE` on the seat: two tabs racing for one seat is the
            # ordinary case, not the exotic one, and without the lock both read
            # it empty and both insert.
            await cur.execute(
                """
                SELECT s.id, s.reserved_for_lobby_user,
                       p.id AS player_id, p.lobby_user_id
                  FROM seats s
             LEFT JOIN players p ON p.seat_id = s.id
                 WHERE s.match_id = %s AND s.seat_key = %s
                   FOR UPDATE OF s
                """,
                (match_id, seat_key),
            )
            seat_row = await cur.fetchone()
            if seat_row is None:
                raise NotFoundError("seat not found")

            reserved = seat_row["reserved_for_lobby_user"]
            if reserved and lobby_user_id and reserved != lobby_user_id:
                raise ReservationError("that seat is reserved for another player")

            if seat_row["player_id"] is not None:
                if lobby_user_id and seat_row["lobby_user_id"] == lobby_user_id:
                    await cur.execute(
                        "UPDATE players SET name = %s WHERE id = %s",
                        (display_name, seat_row["player_id"]),
                    )
                    await self._touch_player(cur, lobby_user_id, display_name)
                    await conn.commit()
                    found = await self.get_match(external_match_id)
                    assert found is not None
                    seat = found.seat(seat_key)
                    assert seat is not None
                    return ClaimResult(match=found, seat=seat, reclaimed=True)
                raise ConflictError("that seat is already taken")

            await cur.execute(
                """
                INSERT INTO players (match_id, seat_id, name, lobby_user_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (match_id, seat_row["id"], display_name, lobby_user_id),
            )
            if lobby_user_id:
                await self._touch_player(cur, lobby_user_id, display_name)
            await conn.commit()

        found = await self.get_match(external_match_id)
        assert found is not None
        seat = found.seat(seat_key)
        assert seat is not None
        return ClaimResult(match=found, seat=seat, reclaimed=False)

    async def _touch_player(self, cur: Any, lobby_user_id: str, display_name: str) -> None:
        await cur.execute(
            """
            INSERT INTO lobby_players (lobby_user_id, display_name)
            VALUES (%s, %s)
            ON CONFLICT (lobby_user_id) DO UPDATE SET
              display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), lobby_players.display_name),
              last_seen_at = now()
            """,
            (lobby_user_id, display_name),
        )

    async def record_player(self, lobby_user_id: str, display_name: str) -> None:
        async with await self._connect() as conn, conn.cursor() as cur:
            await self._touch_player(cur, lobby_user_id, display_name)
            await conn.commit()

    async def record_result(self, result: StoredResult) -> None:
        async with await self._connect() as conn, conn.cursor() as cur:
            await self._touch_player(cur, result.lobby_user_id, "")
            # `DO UPDATE` and not `DO NOTHING`: the lifecycle report is retried,
            # and a retry carrying a corrected outcome should land rather than
            # be dropped as a duplicate. `matches_played` is bumped only on the
            # insert, which is what `xmax = 0` distinguishes.
            await cur.execute(
                """
                INSERT INTO match_results
                  (match_id, lobby_user_id, seat_key, side, ending, won,
                   rounds_won, base_hp, test_profile)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (match_id, lobby_user_id) DO UPDATE SET
                  ending     = EXCLUDED.ending,
                  won        = EXCLUDED.won,
                  rounds_won = EXCLUDED.rounds_won,
                  base_hp    = EXCLUDED.base_hp
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    result.match_id,
                    result.lobby_user_id,
                    result.seat_key,
                    result.side,
                    result.ending,
                    result.won,
                    result.rounds_won,
                    result.base_hp,
                    result.test_profile,
                ),
            )
            row = await cur.fetchone()
            if row is not None and row["inserted"]:
                await cur.execute(
                    "UPDATE lobby_players SET matches_played = matches_played + 1 WHERE lobby_user_id = %s",
                    (result.lobby_user_id,),
                )
            await conn.commit()

    async def results_for_player(self, lobby_user_id: str, limit: int = 20) -> list[StoredResult]:
        async with await self._connect() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT match_id, lobby_user_id, seat_key, side, ending, won,
                       rounds_won, base_hp, test_profile, created_at
                  FROM match_results
                 WHERE lobby_user_id = %s
              ORDER BY created_at DESC
                 LIMIT %s
                """,
                (lobby_user_id, limit),
            )
            rows = await cur.fetchall()
        return [
            StoredResult(
                match_id=str(row["match_id"]),
                lobby_user_id=row["lobby_user_id"],
                seat_key=row["seat_key"],
                side=row["side"],
                ending=row["ending"],
                won=row["won"],
                rounds_won=row["rounds_won"],
                base_hp=row["base_hp"],
                test_profile=bool(row["test_profile"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def mark_finished(self, external_match_id: str, *, reported: bool) -> None:
        async with await self._connect() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE matches
                   SET status      = 'finished',
                       finished_at = COALESCE(finished_at, now()),
                       reported_at = CASE WHEN %s THEN COALESCE(reported_at, now()) ELSE reported_at END
                 WHERE external_match_id = %s
                """,
                (reported, external_match_id),
            )
            await conn.commit()
