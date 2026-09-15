"""Chasing something, and every reason to stop.

A chase is the one decision in this package that outlives the tick that made it,
and that is precisely why it needs bounds written down rather than left to the
weights. A scoring function re-run every tick has no memory of having already
spent four seconds on this, so "do not chase for ever" is not something a weight
can express. Hence a `Commitment` on `UnitAi`, and hence this module.

**Four bounds, and each one answers a different failure.**

============  ==============================================================
Bound         The failure it prevents
============  ==============================================================
leash         being walked off the map one step at a time. Bounds **how far
              the unit roams**, measured from where the chase started — not
              how far away the quarry is, which would stop a unit taking one
              step toward something it could then shoot. And not measured
              from the station, so that a troop under Push, whose station is
              most of a map away, is bounded by the same rule as one holding
              a lane.
progress      chasing something that is not getting closer. After a second
              of it, a chase that has not shut the gap is abandoned — which
              covers the quarry that is faster, the one that is circling,
              and the one being led away, with one measurable fact instead
              of three guesses. This is where the speed differential shows
              up, and it shows up **measured** rather than compared: a unit
              does not need to know it is slower, it needs to notice it is
              not gaining.
timeout       a chase that shuts the gap slowly enough to keep passing the
              progress test for ever.
recovery      the one that is easy to leave out: without it a chase ends on
              a bound and is re-committed on the very next tick, which is
              the same endless chase with extra bookkeeping. Repeated bait
              is exactly this, and it is what `recovery` exists to answer.
============  ==============================================================

**There is deliberately no "am I faster than it" test up front.** The obvious
one — refuse to chase anything that is not slower than you — reads well and is
wrong, because two units of identical speed walking *at each other* close
perfectly well. Applied at eligibility it stopped a cinder-hound from ever
advancing on another cinder-hound, which is most of a mirror match. What matters
is whether the gap is actually shutting, and the only honest way to know that is
to try it briefly and look.

**Returning costs nothing.** While a unit is in recovery it gets no pursuit
candidates, so the best thing left is usually advancing on its station — and the
orders phase rewrites that station every tick anyway. The unit resumes its
assigned task by running out of better ideas, which is the mechanism JQ-287 and
JQ-328 both leaned on and this ticket does not need to replace.
"""

from __future__ import annotations

from app.sim.ai.capabilities import Capabilities
from app.sim.ai.intent import (
    PURSUIT_ABANDONED_INVALID,
    PURSUIT_ABANDONED_LEASH,
    PURSUIT_ABANDONED_TIMEOUT,
    PURSUIT_ABANDONED_UNREACHABLE,
    Commitment,
)
from app.sim.ai.observe import Observation
from app.sim.ai.positioning import standoff_position, useful_range
from app.sim.geometry import distance
from app.sim.types import UnitId, Vec2
from app.sim.world import Unit

#: How far from where it started a chase may travel, in map units.
#:
#: Provisional. The two-lane map is 375 across and an ember-adept reaches 90, so
#: this is about one long weapon's reach of rope — enough to run something down
#: that broke off mid-fight, not enough to cross a lane after it.
PURSUIT_LEASH = 96.0

#: How long a single chase may last, in seconds. Sixty ticks at the default rate.
PURSUIT_TIMEOUT_SECONDS = 3.0

#: How long a chase gets before it has to show it is working, in seconds.
PURSUIT_PATIENCE_SECONDS = 1.0

#: And how much of the gap it must have shut by then, as a fraction. Small: this
#: is meant to catch a chase making *no* headway, not to demand a brisk one.
PURSUIT_PROGRESS_FRACTION = 0.1

#: How long after a chase ends before this unit may start another, in seconds.
#: The bait defence: long enough that a unit which has just been drawn off gets
#: back to doing its job before it can be drawn off again.
PURSUIT_RECOVERY_SECONDS = 2.0

#: How much better a different target must score before a committed unit will
#: switch to it. Hysteresis against dithering between two nearly equal options,
#: not a refusal to notice a better one — and the difference between those two
#: is the whole of why this number is where it is.
#:
#: Measured, on a hound committed to one ash-ram with a second in view. Two
#: healthy rams a single map unit apart score *identically* — the approach is
#: taken to each one's own useful range, so the position differs and the verdict
#: does not — and a ram wounded by a hair separates them by 0.0002. A ram that
#: has closed sixteen units and is one swing from death separates them by 0.0499.
#: Those are the two cases this has to tell apart, and the first draft of 0.05
#: sat directly on top of the second: a quarry both nearer and nearly dead was
#: refused, which is not hysteresis, it is stubbornness. Placed between the two
#: measurements rather than at either end.
TARGET_SWITCH_MARGIN = 0.02


def can_engage(capabilities: Capabilities, gap: float) -> bool:
    """Whether something at this distance is already inside the weapon."""
    return gap <= capabilities.reach


def anchor(observation: Observation) -> Vec2:
    """Where the leash is tied: the chase's origin, or here if none has begun."""
    commitment = observation.commitment
    return commitment.origin if commitment is not None else observation.unit.position


def approach_to(observation: Observation, target: Unit) -> Vec2:
    """Where this unit would stand to fight `target` — its own useful range off."""
    return standoff_position(
        observation.unit.position, target.position, useful_range(observation.capabilities)
    )


def worth_chasing(observation: Observation, target: Unit) -> bool:
    """Eligibility: already in reach, or reachable without roaming past the leash.

    Something already in reach is always eligible — a unit does not need to
    outrun what it can hit from where it stands, and a rooted fixture must still
    be able to fight whatever walks up to it.

    The leash is applied to the **position this unit would move to**, not to
    where the quarry is standing. Those differ by the unit's whole reach, and
    getting it the wrong way round forbids an ember-adept from taking one step
    toward something a hundred units off that it could then shoot from where it
    landed — a refusal to engage dressed up as a bound on pursuit.
    """
    capabilities = observation.capabilities
    if can_engage(capabilities, distance(observation.unit.position, target.position)):
        return True

    if not capabilities.can_move:
        return False

    return distance(anchor(observation), approach_to(observation, target)) <= PURSUIT_LEASH


def eligible_targets(observation: Observation) -> tuple[UnitId, ...]:
    """Every enemy this unit may chase, in `enemies` order — so, sorted by id.

    Recovery suppresses the ones it would have to travel to, and only those.
    A unit that has just been baited off its post still defends itself against
    whatever is standing in front of it; what it declines is being drawn off
    again, which is the only thing recovery is for.
    """
    reachable_only = observation.recovery_remaining > 0
    return tuple(
        enemy.id
        for enemy in observation.enemies
        if worth_chasing(observation, enemy)
        and not (
            reachable_only
            and not can_engage(observation.capabilities, distance(observation.unit.position, enemy.position))
        )
    )


def release_reason(observation: Observation) -> str | None:
    """Why the chase in progress must end, or None if it may continue.

    Checked in the order a reader would ask the questions: is the quarry still
    there, can it still be caught, has the chase gone too far, has it taken too
    long. The first answer wins, so a chase that breaks three bounds at once
    reports the most basic of them rather than whichever happened to be tested
    last — which matters, because the reason is what JQ-331's inspector prints.
    """
    commitment = observation.commitment
    if commitment is None:
        return None

    target = _find(observation, commitment.target_id)
    if target is None:
        return PURSUIT_ABANDONED_INVALID

    gap = distance(observation.unit.position, target.position)
    elapsed = (observation.tick - commitment.started_tick) * observation.seconds_per_tick

    if not can_engage(observation.capabilities, gap):
        if distance(commitment.origin, observation.unit.position) > PURSUIT_LEASH:
            return PURSUIT_ABANDONED_LEASH
        closed = commitment.opening_gap - gap
        if (
            elapsed >= PURSUIT_PATIENCE_SECONDS
            and closed < commitment.opening_gap * PURSUIT_PROGRESS_FRACTION
        ):
            return PURSUIT_ABANDONED_UNREACHABLE

    if elapsed >= PURSUIT_TIMEOUT_SECONDS:
        return PURSUIT_ABANDONED_TIMEOUT

    return None


def begin(observation: Observation, target_id: UnitId) -> Commitment:
    """Commits to a chase, recording what it has to beat to count as working."""
    target = _find(observation, target_id)
    return Commitment(
        target_id=target_id,
        started_tick=observation.tick,
        origin=observation.unit.position,
        opening_gap=(distance(observation.unit.position, target.position) if target is not None else 0.0),
    )


def _find(observation: Observation, unit_id: UnitId) -> Unit | None:
    for enemy in observation.enemies:
        if enemy.id == unit_id:
            return enemy
    return None
