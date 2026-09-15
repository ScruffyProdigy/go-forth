"""Target acquisition, shared by the phases that need it.

Ties break on unit id rather than on list position: two enemies exactly the same
distance away must resolve the same way in every replay, and list order shifts as
units are removed.
"""

from __future__ import annotations

from app.sim.geometry import distance
from app.sim.world import Unit, World, is_alive

__all__ = ["acquire_target", "is_alive"]


def acquire_target(world: World, unit: Unit, reach: float | None = None) -> Unit | None:
    """The nearest living enemy within reach, or None.

    Reach defaults to the unit's weapon range. An ability passes its own, so a
    card can reach further than it swings without a second search written for it.
    """
    limit = unit.range if reach is None else reach
    best: Unit | None = None
    best_gap = float("inf")

    for candidate in world.units:
        if candidate.side == unit.side or not is_alive(candidate):
            continue

        gap = distance(unit.position, candidate.position)
        if gap > limit:
            continue

        if gap < best_gap or (gap == best_gap and best is not None and candidate.id < best.id):
            best = candidate
            best_gap = gap

    return best
