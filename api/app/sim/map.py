"""The map as data.

Zone count, each zone's depth, its horizontal extent, and its point value are all
map data rather than constants in the sim (design doc §4.12: "maps vary by data,
not by code"). A zone narrower than the map is the one variation that adds a new
verb — it opens a bypass lane — so `extent` is separate from the map width even
though v1's single map uses the full width.

Scoring the zones is slice B (JQ-287). What lives here is the geometry and the
occupancy test everything else reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.sim.types import SIDES, Side, Span, Vec2


@dataclass
class ZoneConfig:
    #: Short label, as the design doc's A–B–C. Data, not an enum.
    id: str
    #: The zone's band down the lane, north edge to south edge.
    lane: Span
    #: Horizontal extent. Narrower than the map leaves a bypass lane either side.
    extent: Span
    #: Zone score awarded per tick to whoever holds it.
    points_per_tick: float


@dataclass
class BaseConfig:
    position: Vec2
    max_hp: float


@dataclass
class DeploymentStrip:
    """Where a side's troops are auto-placed at the start of a battle."""

    lane: Span
    extent: Span


@dataclass
class MapConfig:
    id: str
    size_width: float
    size_height: float
    #: Ordered north to south.
    zones: list[ZoneConfig]
    bases: dict[Side, BaseConfig] = field(default_factory=dict)
    deployment: dict[Side, DeploymentStrip] = field(default_factory=dict)


#: v1 ships one map. Dimensions follow the JQ-243 readability plates: a 375 px
#: portrait width, three 123 px zones — the measured ceiling, since four zones
#: need ~150 px each and do not fit.
THREE_ZONE_MAP = MapConfig(
    id="three-zone-lane",
    size_width=375,
    size_height=569,
    zones=[
        ZoneConfig("A", Span(100, 223), Span(0, 375), 1),
        ZoneConfig("B", Span(223, 346), Span(0, 375), 1),
        ZoneConfig("C", Span(346, 469), Span(0, 375), 1),
    ],
    bases={
        "north": BaseConfig(Vec2(187.5, 20), 1000),
        "south": BaseConfig(Vec2(187.5, 549), 1000),
    },
    deployment={
        "north": DeploymentStrip(Span(40, 100), Span(0, 375)),
        "south": DeploymentStrip(Span(469, 529), Span(0, 375)),
    },
)


def _assert_span_within(span: Span, limit: float, what: str) -> None:
    if span.start >= span.end:
        raise ValueError(f"{what} has a lane span that does not run north to south")
    if span.start < 0 or span.end > limit:
        raise ValueError(f"{what} falls outside the map")


def validate_map_config(config: MapConfig) -> None:
    """Raises unless the map is coherent. Called once, at battle start."""
    if config.size_width <= 0 or config.size_height <= 0:
        raise ValueError("map size must be positive")
    if not config.zones:
        raise ValueError("map must have at least one zone")

    seen: set[str] = set()
    for index, zone in enumerate(config.zones):
        if zone.id in seen:
            raise ValueError(f'map has two zones called "{zone.id}"')
        seen.add(zone.id)

        _assert_span_within(zone.lane, config.size_height, f"zone {zone.id}")
        _assert_span_within(zone.extent, config.size_width, f"zone {zone.id} extent")

        if zone.points_per_tick <= 0:
            raise ValueError(f"zone {zone.id} is worth no points per tick")

        if index > 0:
            previous = config.zones[index - 1]
            if zone.lane.start < previous.lane.end:
                raise ValueError(
                    f"zones {previous.id} and {zone.id} overlap along the lane"
                )

    for side in SIDES:
        strip = config.deployment[side]
        _assert_span_within(strip.lane, config.size_height, f"{side} deployment strip")
        _assert_span_within(
            strip.extent, config.size_width, f"{side} deployment strip extent"
        )

        for zone in config.zones:
            if strip.lane.start < zone.lane.end and zone.lane.start < strip.lane.end:
                raise ValueError(f"{side} deployment strip overlaps zone {zone.id}")

        base = config.bases[side]
        if base.max_hp <= 0:
            raise ValueError(f"{side} base has no HP")
        if base.position.y < 0 or base.position.y > config.size_height:
            raise ValueError(f"{side} base falls outside the map")


def _span_contains(span: Span, value: float) -> bool:
    return span.start <= value < span.end


def zone_containing(config: MapConfig, position: Vec2) -> ZoneConfig | None:
    """The zone a position sits in, or None for strips, base plates and bypass lanes.

    This is the occupancy test zone scoring will read, so it lives here rather
    than being re-derived per system.
    """
    for zone in config.zones:
        if _span_contains(zone.lane, position.y) and _span_contains(
            zone.extent, position.x
        ):
            return zone
    return None
