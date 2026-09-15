"""Plays one assembled single-round match and prints it.

The match-layer counterpart to `battle_demo`: that one runs a battle from a
fixture, this one runs a *match* — plans locked, spells cast against a live
energy pool, and a terminal outcome — which is the thing JQ-308 actually built.

    python -m app.scripts.match_demo
    python -m app.scripts.match_demo --seed 7
    python -m app.scripts.match_demo --miss-plan south
    python -m app.scripts.match_demo --digest

`--miss-plan` has that side never submit anything, so the run exercises the
missed-plan policy: the backstop expires and the server locks the suggested
legal default on their behalf.

stdout is the canonical serialisation and nothing else, so two runs can be
compared byte for byte — `tests/match/test_determinism.py` does exactly that
across fresh interpreters. The human-readable summary goes to stderr.

The casts below are scheduled by tick rather than chosen by judgement. A demo
that cast when it felt like it would be a different match on every change to the
sim, and the determinism check rests on this file being boring.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Sequence

from app.match import (
    OPENING_CATALOG,
    SINGLE_ROUND_TEST_PROFILE,
    MatchController,
    RoundOutcome,
    new_match,
)
from app.sim import SIDES, TWO_LANE_MAP, Side, Vec2, digest_battle, serialize_battle

DEFAULT_SEED = 20260915

#: Scripted casts: `(tick, side, spell, where)`. Both sides, so the demo shows
#: two pools being spent independently, and spread out so the later ones are
#: affordable rather than silently refused.
SCRIPT: tuple[tuple[int, Side, str, Vec2], ...] = (
    (240, "north", "meteor", Vec2(187.5, 300)),
    (420, "south", "ember-surge", Vec2(187.5, 250)),
    (700, "north", "ember-surge", Vec2(120.0, 320)),
    (900, "south", "meteor", Vec2(250.0, 240)),
    (1200, "north", "meteor", Vec2(187.5, 120)),
)


def play(seed: int, miss_plan: Side | None, seconds: float | None) -> tuple[MatchController, RoundOutcome]:
    profile = SINGLE_ROUND_TEST_PROFILE
    if seconds is not None:
        profile = dataclasses.replace(
            profile, sim=dataclasses.replace(profile.sim, max_battle_seconds=seconds)
        )

    match = new_match(
        profile=profile,
        catalog=OPENING_CATALOG,
        map_config=TWO_LANE_MAP,
        seed=seed,
    )

    for side in SIDES:
        if side != miss_plan:
            match.submit_plan(side, match.suggested(side))

    if match.phase == "planning":
        # Nobody else is coming. Let the backstop do what it is for.
        match.advance_planning(profile.plan_backstop_seconds)

    scheduled: dict[int, tuple[Side, str, Vec2]] = {
        tick: (side, spell_id, where) for tick, side, spell_id, where in SCRIPT
    }
    while match.phase == "battle":
        due = scheduled.get(match.tick)
        if due is not None:
            match.try_cast(*due)
        match.advance()

    assert match.outcome is not None
    return match, match.outcome


def summarise(match: MatchController, outcome: RoundOutcome) -> str:
    lines = [
        f"profile      {outcome.profile_label}",
        f"ended        {outcome.reason} on tick {outcome.tick}",
        f"winner       {outcome.winner or 'draw'} (decided by {outcome.decided_by})",
        f"zone score   north {outcome.zone_score['north']:g} / south {outcome.zone_score['south']:g}",
        f"base hp      north {outcome.base_hp['north']:g} / south {outcome.base_hp['south']:g}",
        f"ends match   {outcome.ends_match}",
    ]
    for side in SIDES:
        pool = match.energy(side)
        source = match.lock_source(side)
        if pool is not None:
            lines.append(
                f"{side:<12} plan {source}, spell energy spent {pool.spent:g}, left {pool.current:g}"
            )
    rejected = [event for event in match.events if event.type == "spellRejected"]
    if rejected:
        lines.append(
            f"rejected     {len(rejected)} cast(s): "
            + ", ".join(f"{event.data['spell_id']}/{event.data['reason']}" for event in rejected)
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="shorten the battle's backstop length; the determinism tests use it",
    )
    parser.add_argument(
        "--miss-plan",
        choices=list(SIDES),
        default=None,
        help="have this side never plan, so the backstop locks its default",
    )
    parser.add_argument("--digest", action="store_true", help="print a one-line digest instead")
    args = parser.parse_args(argv)

    match, outcome = play(args.seed, args.miss_plan, args.seconds)
    assert match.runner is not None
    result = match.runner.result()

    body = digest_battle(result) if args.digest else serialize_battle(result)
    print(body)
    # The outcome is the match layer's own output and is not in the battle's
    # serialisation, so it goes on stdout too — a determinism check that
    # compared only the battle would not notice the round being scored wrong.
    print(f"outcome {outcome.reason} {outcome.winner or 'draw'} {outcome.decided_by} {outcome.tick}")
    print(summarise(match, outcome), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
