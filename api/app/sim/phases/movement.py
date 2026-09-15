"""Movement.

Units walk to the station their order gave them and stop at weapon range rather
than into the enemy. Two ranks in contact sit about 20 px apart and read as one
blob, so the engagement gap is what hands the front line back to the player
(JQ-243). It falls out of one rule rather than a special case: **no unit ends a
tick inside its own weapon range of anything it could be shooting**, so a step is
shortened to the slack available and a unit walking at a target it can already
hit does not move at all.

Where it is walking *to* is not decided here. The orders phase writes
`unit.destination` each tick from the troop's order; movement only ever reads it,
which is the seam a behaviour layer (JQ-296/328) overrides for a diversion.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.geometry import distance, move_toward
from app.sim.phases.targeting import acquire_target
from app.sim.types import opposing
from app.sim.world import Unit, World, is_alive


def standoff_slack(world: World, unit: Unit, ctx: TickContext) -> float:
    """How far this unit may step this tick without closing inside its own reach.

    A step of length `d` changes the distance to any point by at most `d`, so
    capping the step at the smallest slack is enough on its own: no trigonometry,
    no per-target path test, and the unit lands exactly at weapon range when it
    was walking straight at something.

    The enemy base counts too — a unit stops at the edge of the base plate rather
    than standing on it.
    """
    slack = float("inf")

    for other in world.units:
        if other.side == unit.side or not is_alive(other):
            continue
        slack = min(slack, distance(unit.position, other.position) - unit.range)

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

            unit.position = move_toward(unit.position, unit.destination, step)


movement_phase = MovementPhase()
