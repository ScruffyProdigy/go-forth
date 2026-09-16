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
have to travel in the snapshot with it. A unit's `Commitment` — the chase it is
running (JQ-329) — is the third of the same kind: a bound on a chase means
nothing if the chase is rebuilt from scratch every tick.

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
    "Commitment",
    "Intent",
    "TroopCoordination",
    "UnitAi",
]

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
#: Interposing between a threat and an ally a coordinator named.
SCREENING = "screening"
#: Interposing between a threat and the ally this unit judged most exposed,
#: because nobody named one — or named one that has since died. The same action;
#: the distinction is that only the first is doing what somebody asked. Worth
#: telling apart in a trace: a guess covering the wrong ally is the shape of
#: thing a playtester writes up as broken AI, and after the fact the only way to
#: know which happened is to have recorded it.
SCREENING_INFERRED = "screening_inferred"
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
    SCREENING_INFERRED,
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
    #: On a screen, the ally being covered — None when it is this unit's own
    #: post. Diagnostics only; the geometry is already in `destination`.
    protecting_id: UnitId | None = None
    #: Which personality tags spoke to it, and in which situation. Diagnostics
    #: only, and the layer JQ-331's inspector reads to explain a decision in the
    #: author's own vocabulary rather than in weights.
    influences: tuple[PersonalityInfluence, ...] = ()


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
    #: Where the unit stood when it committed. The leash measures how far the
    #: unit has roamed from here — not how far off the quarry is.
    origin: Vec2
    #: The distance to the quarry at that moment. A chase that has not shut a
    #: fraction of this after a second is not working, whatever the reason, and
    #: is abandoned. It is the one number that makes "cannot catch it" a
    #: measurement rather than a comparison of stat blocks.
    opening_gap: float = 0.0


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
    #: The chase in progress, if any. Outlives the tick that started it; that is
    #: the point of it. Cleared by `ai/pursuit.py` when a bound is exceeded.
    commitment: Commitment | None = None
    #: Ticks left before a new chase may be committed to. Set when one ends on a
    #: bound, counted down by the decision phase. Without it a chase that ends on
    #: its timeout is simply re-committed on the next tick, which is the same
    #: endless chase — and is exactly what repeated bait does.
    recovery_remaining: int = 0
