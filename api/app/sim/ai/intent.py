"""What a unit has committed to this tick, and where that commitment lives.

The decision phase does not move or damage anything. It writes an `Intent`, and
the movement and combat phases — the ones that already own stepping a position
and applying damage — carry it out. One mover, one damager; a decision system
that also executed would apply everything twice.

`UnitAi` hangs off `Unit` rather than off a side table because the ticket
requires commitment state to be authoritative and reproducible: `run_battle`
snapshots the world each tick, so anything not in the world is not in the replay.
That now covers a `Commitment` as well as an `Intent` — a chase has to outlive
the tick that started it or its bounds mean nothing.

This module is a leaf on purpose. `world.py` imports it, so it must not import
`world.py` back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from app.sim.ai.factors import FactorContribution
from app.sim.ai.profiles import NEUTRAL_BEHAVIOR, ResolvedBehavior
from app.sim.types import UnitId, Vec2

ActionKind = Literal["advance", "attack", "cast", "withdraw", "retreat", "hold"]

#: Declared order, which is also the order candidates are generated in and the
#: order ties break in. `hold` sits last because it is the fallback, and `cast`
#: sits after `attack` so an exact tie conserves the gauge — a ready ability that
#: is merely *as good as* swinging is worth keeping for a moment that is better.
#: Preferring the ability when it is actually better is scoring's job, not the
#: tie-break's.
#:
#: The two ways of giving ground sit below both, so that fighting wins an exact
#: tie against backing off. A unit that is genuinely indifferent between swinging
#: and leaving should swing: leaving concedes ground, and conceding ground on a
#: coin-flip is how a line dissolves without anything having decided to break it.
ACTION_KINDS: tuple[ActionKind, ...] = get_args(ActionKind)

#: The actions that ask the movement phase for a step. Everything else means
#: stand still, which is why `attack` and `cast` are absent rather than scaled
#: to zero — not moving is a different thing from moving at no speed.
MOVING_ACTIONS: tuple[ActionKind, ...] = ("advance", "withdraw", "retreat")

#: How fast `withdraw` walks, as a fraction of the unit's speed.
#:
#: Backing away from something while still facing it is slower than running from
#: it, and that difference is the whole reason giving ground is two verbs rather
#: than one with a flag. Half is the starting point the ticket fixed on
#: 2026-09-15, to be tuned after playtesting; it is deliberately a single named
#: number so that tuning it is a one-line change rather than an audit.
WITHDRAW_SPEED_SCALE = 0.5

#: Actions during which this unit does not swing at anything.
#:
#: Only `retreat`. `withdraw` keeps fighting by design — that is what
#: distinguishes the two — and the rest either are an attack or stand still
#: while one happens. See `phases/targeting.py` for how a suppressed intent
#: declines its target.
ATTACK_SUPPRESSING_ACTIONS: tuple[ActionKind, ...] = ("retreat",)


def movement_scale(kind: ActionKind) -> float:
    """What fraction of its speed a unit walking under this intent covers.

    Read by the movement phase to take the step and by `scoring.py` to work out
    where a candidate would leave the unit standing. Both must agree: the danger
    a unit weighs has to be the danger it actually walks into, and a withdraw
    scored at full speed and walked at half would be neither.
    """
    if kind == "withdraw":
        return WITHDRAW_SPEED_SCALE
    return 1.0 if kind in MOVING_ACTIONS else 0.0


# --- why a unit did what it did ---------------------------------------------
#
# Stable strings, emitted on every intent and read back by JQ-331's inspector.
# They are diagnostics: nothing in the sim branches on a reason, and nothing
# outside the sim should either. They exist so that "why did it stop chasing"
# has an answer that does not require re-running the battle with a debugger.

#: Chose to fight what is in front of it.
ENGAGING = "engaging"
#: Advancing on the station its order gave it.
PRESSING_OBJECTIVE = "pressing_objective"
#: At its post, with nothing better to do.
HOLDING_STATION = "holding_station"
#: Stepping to restore useful firing distance.
MAINTAINING_RANGE = "maintaining_range"
#: Interposing between a threat and what it threatens.
SCREENING = "screening"
#: Closing on a threat it was nominated to answer.
INTERCEPTING = "intercepting"
#: Committed to chasing a specific target this tick.
PURSUIT_STARTED = "pursuit_started"
#: Continuing a chase committed to on an earlier tick.
PURSUING = "pursuing"
#: The chase ran past its distance bound from the station.
PURSUIT_ABANDONED_LEASH = "pursuit_abandoned_leash"
#: The chase ran past its tick bound.
PURSUIT_ABANDONED_TIMEOUT = "pursuit_abandoned_timeout"
#: The target cannot be caught — it is at least as fast and already out of reach.
PURSUIT_ABANDONED_UNREACHABLE = "pursuit_abandoned_unreachable"
#: The target died, left, or stopped being a legal one.
PURSUIT_ABANDONED_INVALID = "pursuit_abandoned_invalid"
#: Swapped targets because the new one was a meaningful improvement.
TARGET_SWITCHED = "target_switched"
#: Giving ground while still fighting.
WITHDRAWING = "withdrawing"
#: Disengaging to survive; attacks suppressed.
RETREATING = "retreating"
#: A commitment was released and the assigned task resumed.
RETURNED_TO_STATION = "returned_to_station"

#: Every reason, in declared order. Exported as a tuple so a reader — or JQ-331 —
#: can enumerate them without keeping a second copy of the list in sync.
REASONS: tuple[str, ...] = (
    ENGAGING,
    PRESSING_OBJECTIVE,
    HOLDING_STATION,
    MAINTAINING_RANGE,
    SCREENING,
    INTERCEPTING,
    PURSUIT_STARTED,
    PURSUING,
    PURSUIT_ABANDONED_LEASH,
    PURSUIT_ABANDONED_TIMEOUT,
    PURSUIT_ABANDONED_UNREACHABLE,
    PURSUIT_ABANDONED_INVALID,
    TARGET_SWITCHED,
    WITHDRAWING,
    RETREATING,
    RETURNED_TO_STATION,
)

#: The reasons that end a chase. A reader wanting "did this pursuit stop, and
#: why" matches this rather than string-prefixing on `pursuit_abandoned_`.
PURSUIT_ENDED_REASONS: tuple[str, ...] = (
    PURSUIT_ABANDONED_LEASH,
    PURSUIT_ABANDONED_TIMEOUT,
    PURSUIT_ABANDONED_UNREACHABLE,
    PURSUIT_ABANDONED_INVALID,
)


@dataclass(frozen=True)
class Intent:
    """One tick's committed action. Read by movement and by target acquisition."""

    kind: ActionKind
    #: Set for `attack`. The unit combat should prefer over the nearest enemy.
    target_id: UnitId | None = None
    #: Set for `advance`, `withdraw`, `retreat` and `hold`. Where movement should
    #: walk toward — or, for `hold`, stand on.
    destination: Vec2 | None = None
    #: Set for `cast`. The ability the abilities phase should spend, via the
    #: `FollowsIntent` policy in `ai/casting.py`.
    ability_id: str | None = None
    #: The winning candidate's total, in `[-1, 1]`.
    score: float = 0.0
    #: Why it won. Diagnostics only; nothing in the sim branches on it.
    contributions: tuple[FactorContribution, ...] = ()
    #: One of `REASONS`, or "" for an intent built before reasons existed.
    #: Diagnostics only, same as `contributions`.
    reason: str = ""


@dataclass(frozen=True)
class Commitment:
    """A chase this unit is running, and the bounds it runs under.

    Frozen, and replaced rather than mutated, so that a per-tick snapshot of the
    world holds the commitment as it stood on that tick. A mutable one would let
    a replay read a chase's *current* state at every tick of its history, which
    is the sort of thing that makes a trace look like it changed the past.

    The leash is anchored to `origin` — the station as it stood when the chase
    began — rather than to the station as it stands now. The orders phase
    rewrites `unit.destination` every tick, and a troop whose station is itself
    advancing would otherwise drag the leash along with it and bound nothing.
    """

    target_id: UnitId
    #: `world.tick` when this chase was committed to.
    started_tick: int
    #: The station this chase departed from. The leash is measured from here.
    origin: Vec2


@dataclass
class UnitAi:
    """A unit's composed behavior, and the intent it is acting on."""

    behavior: ResolvedBehavior = NEUTRAL_BEHAVIOR
    intent: Intent | None = None
    #: The chase in progress, if any. Outlives the tick that started it; that is
    #: the point of it. Cleared by `ai/pursuit.py` when a bound is exceeded.
    commitment: Commitment | None = None
