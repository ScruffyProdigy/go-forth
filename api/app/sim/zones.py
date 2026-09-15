"""Who is holding which lane — the occupancy facts everything else reads.

A lane is held when **exactly one side has a living mage standing in its
hotspot**. Two mages in it makes it contested and no mage in it makes it empty,
and neither scores for anyone. Ownership is not sticky, so a lane stops paying
the tick its holder steps off or falls.

Two things follow from putting the test on a mage in a small square rather than
on any unit anywhere in the lane, and both are the point of the rule:

* **A lane cannot be denied by lurking.** A straggler in the corner of a
  369-deep lane is not standing on the hotspot, so it takes the fight to keep
  someone off it. Denial is a combat outcome again.
* **Scoring costs exposure.** The mage is the slowest, most fragile unit in the
  troop and the one whose death dissolves it (§4.6). Holding a lane means
  walking it into the most contested square on the map, behind a screen that has
  to have won that ground first.

Scoring reads this, and so does the renderer's zone state chip (JQ-294), which is
why the shape here is a fact about the world rather than a side effect of the
scoring phase.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.sim.map import MapConfig, ZoneConfig, hotspot_contains, zone_containing
from app.sim.types import SIDES, Side
from app.sim.world import World, is_alive


@dataclass(frozen=True)
class ZoneOccupancy:
    """One lane, and who is standing where in it right now."""

    zone: ZoneConfig
    #: Living mages inside the hotspot, per side. This is what scores.
    counts: Mapping[Side, int]
    #: Every living unit inside the lane, per side — mages, summons and all.
    #: Nothing scores off this; it is what the renderer and the behaviour layer
    #: want when they ask who is contesting a lane.
    lane_counts: Mapping[Side, int]
    #: The side holding it, or None while contested or empty.
    holder: Side | None


def _holder(counts: Mapping[Side, int]) -> Side | None:
    inside = [side for side in SIDES if counts[side] > 0]
    return inside[0] if len(inside) == 1 else None


def zone_occupancy(world: World, config: MapConfig) -> tuple[ZoneOccupancy, ...]:
    """Occupancy for every lane, in map order.

    Returned as an ordered tuple rather than a dict so that a caller can walk it
    without iterating an unordered collection — the rule that keeps this sim
    deterministic across interpreters (see `rng.py`).
    """
    on_hotspot: dict[str, dict[Side, int]] = {zone.id: {"north": 0, "south": 0} for zone in config.zones}
    in_lane: dict[str, dict[Side, int]] = {zone.id: {"north": 0, "south": 0} for zone in config.zones}

    for unit in world.units:
        if not is_alive(unit):
            continue

        zone = zone_containing(config, unit.position)
        if zone is None:
            continue

        in_lane[zone.id][unit.side] += 1
        if unit.kind == "mage" and hotspot_contains(config, zone, unit.position):
            on_hotspot[zone.id][unit.side] += 1

    return tuple(
        ZoneOccupancy(
            zone=zone,
            counts=MappingProxyType(dict(on_hotspot[zone.id])),
            lane_counts=MappingProxyType(dict(in_lane[zone.id])),
            holder=_holder(on_hotspot[zone.id]),
        )
        for zone in config.zones
    )
