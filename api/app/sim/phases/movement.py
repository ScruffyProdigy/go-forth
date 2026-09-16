"""Movement.

Units walk to the station their order gave them and stop at weapon range rather
than into the enemy. Two ranks in contact sit about 20 px apart and read as one
blob, so the engagement gap is what hands the front line back to the player
(JQ-243).

Two rules do it, and the gap between them is deliberate. A unit **stops walking
the moment anything is within its weapon range**, which is what holds the line;
and a step is shortened so that it can never close nearer than its *engagement
standoff*, a tenth inside that range, which is what stops a fast unit vaulting
from out of range to on top of someone in a single tick. The standoff sits inside
the range rather than on it so that stopping and being able to shoot are the same
state — see `ENGAGEMENT_STANDOFF`.

**An intent outranks the first rule.** A unit carrying a decision (JQ-328) does
what it decided: attacking or holding means stand still, advancing means walk,
even with an enemy in reach. The hold-on-contact rule was the only sensible
behaviour while nothing could decide otherwise, and it was never meant to
overrule a decision — left unconditional it made "press the objective past a
weak enemy" unreachable however the weights were set. It remains the default for
every unit with no behaviour data, which is all of them until profiles ship.

The standoff is a property of *walking*, so it clamps both paths: a unit that
decided to advance past someone still stops at weapon range rather than through
them.

Where it is walking *to* is not decided here. The orders phase writes
`unit.destination` each tick from the troop's order; movement only ever reads it,
which is the seam a behaviour layer (JQ-296/328) overrides for a diversion.

A step is then cut short at an enemy barricade (JQ-288). That clamp lives in
`blocking.py` rather than here, and composes with the standoff above it because
both only ever shorten a step along the direction the unit was already going.
"""

from __future__ import annotations

from app.sim.ai.intent import MOVING_ACTIONS, movement_scale
from app.sim.blocking import clamp_to_blockers
from app.sim.context import TickContext
from app.sim.geometry import distance, move_toward
from app.sim.phases.targeting import acquire_target
from app.sim.types import opposing
from app.sim.world import Unit, World, is_alive

#: How close a unit will walk to an enemy, as a fraction of its own weapon range.
#:
#: Strictly **inside** the range rather than exactly on it, and that margin is
#: load-bearing. A step of length `d` closes the distance to an off-axis enemy by
#: *less* than `d`, so a unit whose step is capped at "distance minus range"
#: approaches the range boundary from outside and converges on it without ever
#: arriving. It is then stuck: a hair out of range so it cannot shoot, and out of
#: slack so it cannot walk on. Measured before this margin existed, a hound ended
#: frozen at 20.000000000000018 against a range of 20, alive and out of the
#: battle for good.
#:
#: Stopping inside the range makes "close enough to stop" and "close enough to
#: fire" the same state, rather than two states that meet at a single point
#: floating-point arithmetic cannot land on.
ENGAGEMENT_STANDOFF = 0.9


def engagement_standoff(unit: Unit) -> float:
    """How near this unit is willing to walk to something it could shoot."""
    return unit.range * ENGAGEMENT_STANDOFF


def standoff_slack(world: World, unit: Unit, ctx: TickContext) -> float:
    """How far this unit may step before it would **cross into** an enemy's standoff.

    Only enemies the unit is currently *outside* of are counted. That exception is
    the whole of the rule, and it is easy to leave out: the cap is on step
    *length*, which has no direction, so counting an enemy the unit is already
    inside of caps every direction alike and pins the unit where it stands. An
    Ember Adept — range 90, standoff 81 — could not move at all with anything
    within 81 of it, in an eighty-one unit bubble it could neither leave, cross,
    nor walk around.

    That is not what the standoff is for. Holding the line is the engage-en-route
    rule in `run` below: a unit with nothing to say for itself stops the moment
    anything is within its weapon range, which is further out than the standoff,
    so an ordinary battle never reaches this clamp at all. What this guarantees
    is narrower and only about a single tick: **no unit, however fast, gets from
    outside an enemy's reach to standing on top of it in one step.** A unit that
    is already close — because an enemy closed on it, or because a behaviour
    layer decided to press on (JQ-328) or to leave (JQ-329) — is not held there.

    A step of length `d` changes the distance to any point by at most `d`, so
    capping at the smallest slack is enough on its own: no trigonometry, no
    per-target path test.

    The enemy base gets the same treatment — a unit stops at the edge of the base
    plate rather than standing on it, but one already inside the plate can leave.
    """
    slack = float("inf")
    standoff = engagement_standoff(unit)

    for other in world.units:
        if other.side == unit.side or not is_alive(other):
            continue
        gap = distance(unit.position, other.position)
        if gap <= standoff:
            # At or inside this one. It does not get a vote on the step.
            #
            # `<=` rather than `<` on purpose. A unit clamped on the way in lands
            # *exactly* on the standoff, so a strict test would count it the very
            # next tick, hand back a slack of zero, and pin it there for good —
            # the same boundary trap that froze off-axis walkers on their own
            # weapon range, one rule further in.
            continue
        slack = min(slack, gap - standoff)

    enemy_base = ctx.map_config.bases[opposing(unit.side)]
    base_gap = distance(unit.position, enemy_base.position)
    if base_gap > enemy_base.footprint_radius:
        slack = min(slack, base_gap - enemy_base.footprint_radius)

    return max(0.0, slack)


class MovementPhase:
    name = "movement"

    def run(self, world: World, ctx: TickContext) -> None:
        for unit in world.units:
            if not is_alive(unit) or unit.speed == 0:
                continue

            intent = unit.ai.intent if unit.ai is not None else None
            scale = 1.0
            if intent is not None:
                # The decision phase already weighed standing still against
                # moving, danger included. Attacking, casting and holding mean
                # stay put; the three moving verbs mean go, even with an enemy in
                # reach. `withdraw` goes at half pace — backing away from
                # something while still facing it is slower than running from it,
                # and that cost is the reason giving ground is two verbs.
                if intent.kind not in MOVING_ACTIONS:
                    continue
                scale = movement_scale(intent.kind)
            elif acquire_target(world, unit) is not None:
                # No decision loop: hold the gap and let combat work. The unit
                # resumes on the tick nothing is in range any more.
                continue

            step = min(unit.speed * ctx.seconds_per_tick * scale, standoff_slack(world, unit, ctx))
            if step <= 0:
                continue

            target = move_toward(unit.position, unit.destination, step)
            unit.position = clamp_to_blockers(world, unit, target)


movement_phase = MovementPhase()
