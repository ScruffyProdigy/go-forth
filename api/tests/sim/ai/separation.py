"""Measuring how close opposing units actually get, over a whole battle.

Kept rather than thrown away because the question it answers is open: JQ-380 is
deciding whether opposing units may come to rest on the same point, and whichever
way that goes, the answer has to be checked against a running battle rather than
argued about. It is an acceptance criterion on that ticket.

Both measurements walk every tick. Reading final positions only is what made an
earlier version of this analysis wrong — units separate again by the end, so the
end tells you nothing about what happened in the middle.
"""

from __future__ import annotations

from collections import defaultdict

from app.sim.geometry import distance
from app.sim.run_battle import BattleResult

#: Below this, two units are on the same point for any purpose a reader cares
#: about — sprites are 18-28 px (JQ-243), so a gap under one map unit is contact.
COINCIDENT = 1.0


def closest_opposing_approach(result: BattleResult) -> float:
    """The nearest two units on opposing sides ever got, at any tick."""
    return min(
        distance(a.position, b.position)
        for tick in result.ticks
        for index, a in enumerate(tick.state.units)
        for b in tick.state.units[index + 1 :]
        if a.side != b.side
    )


def overlap_episodes(result: BattleResult, threshold: float = COINCIDENT) -> list[int]:
    """How long each run of opposing-unit overlap lasted, in ticks.

    Episodes rather than a raw count, because "153 pair-ticks" cannot tell a
    brush-past from two units standing inside each other for five seconds — and
    that distinction is the whole of JQ-380.
    """
    episodes: list[int] = []
    running: dict[tuple[str, str], int] = defaultdict(int)

    for tick in result.ticks:
        overlapping = {
            (a.id, b.id) if a.id < b.id else (b.id, a.id)
            for index, a in enumerate(tick.state.units)
            for b in tick.state.units[index + 1 :]
            if a.side != b.side and distance(a.position, b.position) < threshold
        }

        for pair in sorted(overlapping):
            running[pair] += 1
        for pair in sorted(running):
            if pair not in overlapping:
                episodes.append(running.pop(pair))

    episodes.extend(running[pair] for pair in sorted(running))
    return episodes
