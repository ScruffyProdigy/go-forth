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

Where it is walking *to* is not decided here. The orders phase writes
`unit.destination` each tick from the troop's order; movement only ever reads it,
which is the seam a behaviour layer (JQ-296/328) overrides for a diversion.

A step is then cut short at an enemy barricade (JQ-288). That clamp lives in
`blocking.py` rather than here, and composes with the standoff above it because
both only ever shorten a step along the direction the unit was already going.
"""

from __future__ import annotations

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
    """How far this unit may step this tick without closing inside its standoff.

    A step of length `d` changes the distance to any point by at most `d`, so
    capping the step at the smallest slack is enough on its own: no trigonometry
    and no per-target path test.

    In practice this rarely binds against a unit, because `acquire_target` stops
    the walk at full weapon range — a tenth further out than the standoff. What
    it guarantees is that no single step, however fast the unit, can carry it
    from outside weapon range to standing on top of an enemy.

    The enemy base counts too — a unit stops at the edge of the base plate rather
    than standing on it.
    """
    slack = float("inf")

    for other in world.units:
        if other.side == unit.side or not is_alive(other):
            continue
        slack = min(slack, distance(unit.position, other.position) - engagement_standoff(unit))

    enemy_base = ctx.map_config.bases[opposing(unit.side)]
    slack = min(slack, distance(unit.position, enemy_base.position) - enemy_base.footprint_radius)

    return max(0.0, slack)


class MovementPhase:
    name = "movement"

    def run(self, world: World, ctx: TickContext) -> None:
        for unit in world.units:
            if not is_alive(unit) or unit.speed == 0:
                continue
            # Already in reach of something: hold the gap and let combat work.
            # The unit resumes on the tick nothing is in range any more.
            if acquire_target(world, unit) is not None:
                continue

            step = min(unit.speed * ctx.seconds_per_tick, standoff_slack(world, unit, ctx))
            if step <= 0:
                continue

            target = move_toward(unit.position, unit.destination, step)
            unit.position = clamp_to_blockers(world, unit, target)


movement_phase = MovementPhase()
