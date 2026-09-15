"""What a unit has committed to this tick, and where that commitment lives.

The decision phase does not move or damage anything. It writes an `Intent`, and
the movement and combat phases — the ones that already own stepping a position
and applying damage — carry it out. One mover, one damager; a decision system
that also executed would apply everything twice.

`UnitAi` hangs off `Unit` rather than off a side table because the ticket
requires commitment state to be authoritative and reproducible: `run_battle`
snapshots the world each tick, so anything not in the world is not in the replay.

This module is a leaf on purpose. `world.py` imports it, so it must not import
`world.py` back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from app.sim.ai.factors import FactorContribution
from app.sim.ai.profiles import NEUTRAL_BEHAVIOR, ResolvedBehavior
from app.sim.types import UnitId, Vec2

ActionKind = Literal["advance", "attack", "cast", "hold"]

#: Declared order, which is also the order candidates are generated in and the
#: order ties break in. `hold` sits last because it is the fallback, and `cast`
#: sits after `attack` so an exact tie conserves the gauge — a ready ability that
#: is merely *as good as* swinging is worth keeping for a moment that is better.
#: Preferring the ability when it is actually better is scoring's job, not the
#: tie-break's.
ACTION_KINDS: tuple[ActionKind, ...] = get_args(ActionKind)


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


@dataclass
class UnitAi:
    """A unit's composed behavior, and the intent it is acting on."""

    behavior: ResolvedBehavior = NEUTRAL_BEHAVIOR
    intent: Intent | None = None
