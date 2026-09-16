"""Plays one authoritative round headlessly and prints it.

The match-layer counterpart to `battle_demo`: that one runs a battle straight
out of the sim, this one runs a **round** — a plan fielded, seat energy
accruing, casts taken mid-battle, and a stopping rule that distinguishes a round
from a match.

    python -m app.scripts.match_demo
    python -m app.scripts.match_demo --seed 7
    python -m app.scripts.match_demo --seconds 12
    python -m app.scripts.match_demo --digest

Deliberately drives `AuthoritativeRound` rather than `MatchSession`: the session
needs a Lobby client and a mode manifest to exist, and none of that changes the
battle. What is under the microscope here is the round.

stdout is the canonical serialisation and nothing else, so two runs can be
compared byte for byte — `tests/match/test_determinism.py` does exactly that
across fresh interpreters. The human-readable summary goes to stderr.

The casts below are scheduled by tick rather than chosen by judgement. A demo
that cast when it felt like it would be a different round on every change to the
sim, and the determinism check rests on this file being boring.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.match import fixtures
from app.match.plan import default_plan, resolve_snapshot
from app.match.round import AuthoritativeRound
from app.match.wire import CastCommand
from app.sim.config import SimConfig
from app.sim.serialize import digest_battle, serialize_battle
from app.sim.types import SIDES, Side, Vec2

DEFAULT_SEED = 20260915

#: Scripted casts: `(tick, side, where)`. Both seats, so the demo shows two
#: pools spent independently, and spread out so the later ones are affordable
#: rather than silently refused.
SCRIPT: tuple[tuple[int, Side, Vec2], ...] = (
    (40, "north", Vec2(187.5, 300.0)),
    (80, "south", Vec2(187.5, 250.0)),
    (140, "north", Vec2(120.0, 320.0)),
    (200, "south", Vec2(250.0, 240.0)),
)


def play(seed: int, seconds: float | None) -> AuthoritativeRound:
    map_config = fixtures.map_config()
    plan = default_plan(map_config)
    snapshots = {side: resolve_snapshot(plan, side) for side in SIDES}

    sim_config = SimConfig() if seconds is None else SimConfig(max_battle_seconds=seconds)
    rnd = AuthoritativeRound(
        round_number=1,
        map_config=map_config,
        plans={side: plan for side in SIDES},
        snapshots=snapshots,
        base_hp={side: map_config.bases[side].max_hp for side in SIDES},
        seed=seed,
        sim_config=sim_config,
    )

    scheduled = {tick: (side, at) for tick, side, at in SCRIPT}
    while not rnd.over:
        due = scheduled.get(rnd.world.tick)
        if due is not None:
            side, at = due
            spells = rnd.loadout_for(side)
            if spells:
                rnd.cast(
                    side,
                    CastCommand(
                        command_id=f"c{rnd.world.tick}",
                        spell_id=spells[0].spell_id,
                        at=at,
                        tick=rnd.world.tick,
                    ),
                )
        rnd.step()
    return rnd


def summarise(rnd: AuthoritativeRound) -> str:
    ending = rnd.ending
    assert ending is not None
    lines = [
        f"ended        {ending.kind}"
        + (f" / {ending.reason}" if ending.reason else "")
        + f" on tick {rnd.world.tick}",
        f"winner       {ending.winner or 'draw'}",
        f"zone score   north {rnd.world.zone_score['north']:g} / south {rnd.world.zone_score['south']:g}",
        f"base hp      north {rnd.base_hp()['north']:g} / south {rnd.base_hp()['south']:g}",
    ]
    for side in SIDES:
        lines.append(f"{side:<12} energy left {rnd.energy_for(side):g}")
    lines.append(f"casts        {len(rnd.casts())} accepted")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="shorten the round's backstop length; the determinism tests use it",
    )
    parser.add_argument("--digest", action="store_true", help="print a one-line digest instead")
    args = parser.parse_args(argv)

    rnd = play(args.seed, args.seconds)
    result = rnd.result()
    ending = rnd.ending
    assert ending is not None

    print(digest_battle(result) if args.digest else serialize_battle(result))
    # The ending is the match layer's own output and is not in the battle's
    # serialisation, so it goes on stdout too — a determinism check that
    # compared only the battle would not notice a round being scored wrong.
    print(f"ending {ending.kind} {ending.reason or '-'} {ending.winner or 'draw'} {rnd.world.tick}")
    print(summarise(rnd), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
