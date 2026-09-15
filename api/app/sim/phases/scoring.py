"""Zone control: who holds what, and what that is worth this tick.

Runs after combat and before removal, so a unit brought to zero this tick has
already stopped holding ground — a zone taken by killing its last defender flips
on the tick the defender falls, not the tick after.

Score accrues per tick to the holder, so a zone held for twice as long is worth
twice as much; contested and empty zones pay nobody. `zoneFlip` is emitted only
when the holder actually changes, which keeps the stream readable: three zones
over a ninety-second battle produce a handful of events rather than five
thousand.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.events import zone_flip
from app.sim.map import zone_centre
from app.sim.world import World
from app.sim.zones import zone_occupancy


class ScoringPhase:
    name = "scoring"

    def run(self, world: World, ctx: TickContext) -> None:
        for occupancy in zone_occupancy(world, ctx.map_config):
            zone = occupancy.zone
            holder = occupancy.holder

            if holder is not None:
                world.zone_score[holder] += zone.points_per_tick

            previous = world.zone_holders[zone.id]
            if holder == previous:
                continue

            world.zone_holders[zone.id] = holder
            ctx.emitter.emit(
                **zone_flip(
                    tick=world.tick,
                    position=zone_centre(zone),
                    zone_id=zone.id,
                    holder=holder,
                    previous=previous,
                    points_per_tick=zone.points_per_tick,
                )
            )


scoring_phase = ScoringPhase()
