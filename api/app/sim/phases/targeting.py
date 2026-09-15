"""Target acquisition, shared by the phases that need it.

Ties break on unit id rather than on list position: two enemies exactly the same
distance away must resolve the same way in every replay, and list order shifts as
units are removed.
"""

from __future__ import annotations

from app.sim.geometry import distance
from app.sim.world import Unit, World, is_alive

__all__ = ["acquire_target", "is_alive"]


def acquire_target(world: World, unit: Unit) -> Unit | None:
    """The nearest living enemy within the unit's weapon range, or None."""
    best: Unit | None = None
    best_gap = float("inf")

    for candidate in world.units:
        if candidate.side == unit.side or not is_alive(candidate):
            continue

        gap = distance(unit.position, candidate.position)
        if gap > unit.range:
            continue

        if gap < best_gap or (gap == best_gap and best is not None and candidate.id < best.id):
            best = candidate
            best_gap = gap

    return best
