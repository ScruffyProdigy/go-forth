"""The blocking primitive — what a barricade actually does to a walker.

JQ-288 asks for "a barricade / blocking primitive, sufficient that an Artifice
roster needs no new code". This is it, and it is deliberately not
pathfinding: a blocker is a disc an enemy may not walk into, and a step that
would end inside one is cut short at the edge. Units pile up against a wall
rather than flowing around it, which is what a wall is for.

Three properties make it safe at this level:

* **It only ever shortens a step, never turns it.** Every blocker contributes
  a cap of `start_gap - radius` on how far the unit may travel *along the
  direction it was already going*, and the tightest cap wins. By the triangle
  inequality the unit then ends at least `radius` from every blocker that
  capped it — so two overlapping barricades cannot bounce a unit into each
  other, which is what deflecting per blocker in turn would do.
* **It never traps anything.** A unit that somehow starts inside a disc is left
  alone, so it can walk out rather than freezing there forever.
* **It cannot be tunnelled through** at any speed this game reaches. A step
  would have to cross a whole disc in one tick to skip the destination test —
  at 20 ticks a second and a 26-unit barricade, that is a speed above 1000,
  against a roster whose fastest card does 62.

A blocker blocks the other side only. Walling your own troops in is not a
mechanic anyone asked for.
"""

from __future__ import annotations

from app.sim.geometry import distance, move_toward
from app.sim.types import Vec2
from app.sim.world import Unit, World


def blockers_against(world: World, unit: Unit) -> list[Unit]:
    """The living enemy barricades this unit has to respect, in world order."""
    return [
        other
        for other in world.units
        if other.blocks_movement and other.side != unit.side and other.hp > 0 and other.id != unit.id
    ]


def clamp_to_blockers(world: World, unit: Unit, destination: Vec2) -> Vec2:
    """Cuts a step short at the nearest barricade it would walk into."""
    step = distance(unit.position, destination)
    if step == 0:
        return destination

    allowed = step
    for blocker in blockers_against(world, unit):
        if distance(destination, blocker.position) >= blocker.block_radius:
            continue

        start_gap = distance(unit.position, blocker.position)
        if start_gap < blocker.block_radius:
            # Already inside it: let the unit walk out instead of pinning it.
            continue

        allowed = min(allowed, start_gap - blocker.block_radius)

    if allowed >= step:
        return destination

    return move_toward(unit.position, destination, allowed)
