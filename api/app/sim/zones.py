"""Who is standing in which zone — the occupancy facts everything else reads.

A zone is **held when exactly one side has units inside it**. Two sides inside
makes it contested and nobody inside makes it empty, and neither scores for
anyone: a zone is won by clearing it, not by arriving first. Ownership is not
sticky, so a zone stops paying the tick its last defender falls.

Scoring reads this, and so does the renderer's zone state chip (JQ-294), which is
why the shape here is a fact about the world rather than a side effect of the
scoring phase.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.sim.map import MapConfig, ZoneConfig, zone_containing
from app.sim.types import SIDES, Side
from app.sim.world import World, is_alive


@dataclass(frozen=True)
class ZoneOccupancy:
    """One zone, and who is standing in it right now."""

    zone: ZoneConfig
    #: Living units inside the zone, per side.
    counts: Mapping[Side, int]
    #: The side holding it, or None while contested or empty.
    holder: Side | None


def _holder(counts: Mapping[Side, int]) -> Side | None:
    inside = [side for side in SIDES if counts[side] > 0]
    return inside[0] if len(inside) == 1 else None


def zone_occupancy(world: World, config: MapConfig) -> tuple[ZoneOccupancy, ...]:
    """Occupancy for every zone, in map order.

    Returned as an ordered tuple rather than a dict so that a caller can walk it
    without iterating an unordered collection — the rule that keeps this sim
    deterministic across interpreters (see `rng.py`).
    """
    tally: dict[str, dict[Side, int]] = {zone.id: {"north": 0, "south": 0} for zone in config.zones}

    for unit in world.units:
        if not is_alive(unit):
            continue
        zone = zone_containing(config, unit.position)
        if zone is not None:
            tally[zone.id][unit.side] += 1

    return tuple(
        ZoneOccupancy(
            zone=zone,
            counts=MappingProxyType(dict(tally[zone.id])),
            holder=_holder(tally[zone.id]),
        )
        for zone in config.zones
    )
