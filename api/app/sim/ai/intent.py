"""What a unit and its troop have committed to, and where those commitments live.

The decision phase does not move or damage anything. It writes an `Intent`, and
the movement and combat phases — the ones that already own stepping a position
and applying damage — carry it out. One mover, one damager; a decision system
that also executed would apply everything twice.

`UnitAi` hangs off `Unit`, and `TroopCoordination` off `Troop`, rather than off a
side table, because the ticket requires commitment state to be authoritative and
reproducible: `run_battle` snapshots the world each tick, so anything not in the
world is not in the replay. A troop's assignments are commitment state in
exactly the sense a unit's intent is, and they outlive a single tick, so they
have to travel in the snapshot with it.

This module is a leaf on purpose. `world.py` imports it, so it must not import
`world.py` back. The vocabulary it is written in lives one level further down
again, in `vocabulary.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.factors import FactorContribution, PersonalityInfluence
from app.sim.ai.profiles import NEUTRAL_BEHAVIOR, ResolvedBehavior
from app.sim.ai.vocabulary import ACTION_KINDS, ActionKind
from app.sim.types import UnitId, Vec2

__all__ = [
    "ACTION_KINDS",
    "ActionKind",
    "Assignment",
    "Intent",
    "TroopCoordination",
    "UnitAi",
]


@dataclass(frozen=True)
class Intent:
    """One tick's committed action. Read by movement and by target acquisition."""

    kind: ActionKind
    #: Set for `attack`. The unit combat should prefer over the nearest enemy.
    target_id: UnitId | None = None
    #: Set for `advance` and `hold`. Where movement should walk toward.
    destination: Vec2 | None = None
    #: Set for `cast`. The ability the abilities phase should spend, via the
    #: `FollowsIntent` policy in `ai/casting.py`.
    ability_id: str | None = None
    #: The winning candidate's total, in `[-1, 1]`.
    score: float = 0.0
    #: Why it won. Diagnostics only; nothing in the sim branches on it.
    contributions: tuple[FactorContribution, ...] = ()
    #: Which personality tags spoke to it, and in which situation. Diagnostics
    #: only, and the layer JQ-331's inspector reads to explain a decision in the
    #: author's own vocabulary rather than in weights.
    influences: tuple[PersonalityInfluence, ...] = ()


@dataclass(frozen=True)
class Assignment:
    """One unit asked to answer one threat, on behalf of one ally.

    The coordinator's whole output. Deliberately a *target* and not a position:
    where to stand while answering it is the assigned unit's own business, read
    off its own capabilities, which is what lets a melee guard and an archer
    take the same assignment and execute it in the only ways each of them can.

    `since_tick` is what makes a commitment a commitment. A still-valid
    assignment is not re-judged until it has been held for the troop's
    commitment window, so a defender that is merely a little further away than
    some newcomer is not swapped out mid-approach.
    """

    unit_id: UnitId
    #: The enemy to answer.
    target_id: UnitId
    #: The troop-mate this is on behalf of. Released when it dies.
    protecting_id: UnitId
    #: The tick this assignment was made, not the tick it was last confirmed.
    since_tick: int


@dataclass
class TroopCoordination:
    """A troop's standing assignments. Rebuilt every tick from live state."""

    #: Sorted by unit id, and at most one per unit.
    assignments: tuple[Assignment, ...] = ()


@dataclass
class UnitAi:
    """A unit's composed behavior, and the intent it is acting on."""

    behavior: ResolvedBehavior = NEUTRAL_BEHAVIOR
    intent: Intent | None = None
