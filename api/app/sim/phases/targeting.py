"""Target acquisition, shared by the phases that need it.

Ties break on unit id rather than on list position: two enemies exactly the same
distance away must resolve the same way in every replay, and list order shifts as
units are removed.

A unit whose decision phase (JQ-328) picked a specific target gets that target,
provided it is still alive and still in reach. Without that, nearest-enemy would
quietly overrule every choice the evaluator made — a unit that decided to finish
a wounded mage would swing at whichever hound wandered closest instead. The
fallback is unchanged, so a battle with no behavior data acquires exactly the
targets it always did.

**An intent may also decline a target outright (JQ-329),** which the fallback
above made impossible. `acquire_target` used to hand back the nearest enemy in
range for every intent that was not an `attack`, so advance, hold and cast all
swung anyway — and a unit that had decided to run would have gone on shooting the
thing it was running from. That is the difference between the two ways of giving
ground: `withdraw` keeps firing and therefore keeps acquiring, `retreat` does not
fire and therefore acquires nothing. The refusal has to live here rather than in
the candidate set, because it is the *fallback* that needed overruling.
"""

from __future__ import annotations

from app.sim.ai.intent import ATTACK_SUPPRESSING_ACTIONS
from app.sim.geometry import distance
from app.sim.world import Unit, World, is_alive

__all__ = ["acquire_target", "declines_target", "is_alive"]


def declines_target(unit: Unit) -> bool:
    """Whether this unit's committed intent refuses to swing at anything.

    Only `retreat` does. A unit with no behaviour data, or none that has decided
    anything yet, declines nothing — a battle that ships no behaviour library
    acquires targets exactly as it did before any of this existed.
    """
    ai = unit.ai
    intent = ai.intent if ai is not None else None
    return intent is not None and intent.kind in ATTACK_SUPPRESSING_ACTIONS


def _intended_target(world: World, unit: Unit, limit: float) -> Unit | None:
    """The target this unit committed to, if it is still a legal one.

    `limit` rather than the unit's weapon range, so an ability searching with its
    own reach still honours the choice: a unit that decided to finish a wounded
    mage should dash at that mage, not at whichever hound drifted nearest.
    """
    ai = unit.ai
    intent = ai.intent if ai is not None else None
    if intent is None or intent.kind != "attack" or intent.target_id is None:
        return None

    for candidate in world.units:
        if candidate.id != intent.target_id:
            continue
        if candidate.side == unit.side or not is_alive(candidate):
            return None
        return candidate if distance(unit.position, candidate.position) <= limit else None

    return None


def acquire_target(world: World, unit: Unit, reach: float | None = None) -> Unit | None:
    """The unit's chosen target if it still holds, else the nearest within reach.

    Reach defaults to the unit's weapon range. An ability passes its own, so a
    card can reach further than it swings without a second search written for it.

    A retreating unit acquires nothing, whatever is standing next to it and
    whatever reach is asked for. See `declines_target`.
    """
    if declines_target(unit):
        return None

    limit = unit.range if reach is None else reach

    intended = _intended_target(world, unit, limit)
    if intended is not None:
        return intended

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
