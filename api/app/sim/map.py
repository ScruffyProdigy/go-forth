"""The map as data.

Zone count, each zone's depth, its horizontal extent, and its point value are all
map data rather than constants in the sim (design doc §4.12: "maps vary by data,
not by code"). A zone narrower than the map is the one variation that adds a new
verb — it opens a bypass lane — so `extent` is separate from the map width even
though v1's single map uses the full width.

Slice B (JQ-287) adds the rest of the geometry orders are derived from: the
centre of a zone, the centre of a deployment strip, a base's footprint, and the
corner of each zone band the renderer's state chip sits in. They live here rather
than in the phases so that sim coordinates and renderer coordinates stay the same
numbers — a combat rule that hard-codes a phone pixel is the thing this module
exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.sim.types import SIDES, Side, Span, Vec2


@dataclass
class ZoneConfig:
    #: Short label, as the design doc's A-B-C. Data, not an enum.
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
    #: How far the base plate reaches. Nothing walks inside it, and a unit under
    #: Push enemy base swings at the base from its own range plus this.
    footprint_radius: float = 24


@dataclass
class DeploymentStrip:
    """Where a side's troops are auto-placed at the start of a battle."""

    lane: Span
    extent: Span


@dataclass
class ChipReserve:
    """The corner of a zone band the renderer's zone state chip occupies.

    Placement routes around it so that army size can never occlude the chip
    (JQ-243, JQ-294). It is map data rather than a constant because it is a
    property of the layout the map was drawn for — 115 x 25 in the reference
    portrait layout — and a map drawn at another size moves it.
    """

    width: float = 115
    height: float = 25


@dataclass
class MapConfig:
    id: str
    size_width: float
    size_height: float
    #: Ordered north to south.
    zones: list[ZoneConfig]
    bases: dict[Side, BaseConfig] = field(default_factory=dict)
    deployment: dict[Side, DeploymentStrip] = field(default_factory=dict)
    #: Reserved at each zone band's top-left corner. Chips align to zone extent.
    chip_reserve: ChipReserve = field(default_factory=ChipReserve)


#: v1 ships one map. Dimensions follow the JQ-243 readability plates: a 375 px
#: portrait width, three 123 px zones - the measured ceiling, since four zones
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
                raise ValueError(f"zones {previous.id} and {zone.id} overlap along the lane")

    for side in SIDES:
        strip = config.deployment[side]
        _assert_span_within(strip.lane, config.size_height, f"{side} deployment strip")
        _assert_span_within(strip.extent, config.size_width, f"{side} deployment strip extent")

        for zone in config.zones:
            if strip.lane.start < zone.lane.end and zone.lane.start < strip.lane.end:
                raise ValueError(f"{side} deployment strip overlaps zone {zone.id}")

        base = config.bases[side]
        if base.max_hp <= 0:
            raise ValueError(f"{side} base has no HP")
        if base.footprint_radius < 0:
            raise ValueError(f"{side} base has a negative footprint")
        if base.position.y < 0 or base.position.y > config.size_height:
            raise ValueError(f"{side} base falls outside the map")

    if config.chip_reserve.width < 0 or config.chip_reserve.height < 0:
        raise ValueError("the chip reserve cannot be negative")


def _span_contains(span: Span, value: float) -> bool:
    return span.start <= value < span.end


def zone_containing(config: MapConfig, position: Vec2) -> ZoneConfig | None:
    """The zone a position sits in, or None for strips, base plates and bypass lanes.

    This is the occupancy test zone scoring will read, so it lives here rather
    than being re-derived per system.
    """
    for zone in config.zones:
        if _span_contains(zone.lane, position.y) and _span_contains(zone.extent, position.x):
            return zone
    return None


def zone_by_id(config: MapConfig, zone_id: str) -> ZoneConfig:
    """The zone with this id. Raises rather than returning None: an order naming
    a zone the map does not have is a broken plan, not an empty result."""
    for zone in config.zones:
        if zone.id == zone_id:
            return zone
    raise ValueError(f'map {config.id} has no zone called "{zone_id}"')


def _span_centre(span: Span) -> float:
    return (span.start + span.end) / 2


def zone_centre(zone: ZoneConfig) -> Vec2:
    """The point a troop ordered to hold this zone forms up on."""
    return Vec2(_span_centre(zone.extent), _span_centre(zone.lane))


def strip_centre(config: MapConfig, side: Side) -> Vec2:
    """The point a troop ordered to defend this side's base forms up on."""
    strip = config.deployment[side]
    return Vec2(_span_centre(strip.extent), _span_centre(strip.lane))


def chip_box(config: MapConfig, zone: ZoneConfig) -> tuple[Span, Span]:
    """The reserved corner of a zone band, as (horizontal, lane) spans.

    Top-left of the band: the chip is drawn from the zone's own extent, so a
    narrow zone moves its chip with it rather than leaving it floating over the
    bypass lane.
    """
    return (
        Span(zone.extent.start, zone.extent.start + config.chip_reserve.width),
        Span(zone.lane.start, zone.lane.start + config.chip_reserve.height),
    )


def clear_of_chip(config: MapConfig, zone: ZoneConfig, position: Vec2) -> Vec2:
    """Moves a position out of the zone's reserved chip corner, if it is in it.

    Leaves by whichever edge is nearer, preferring east — a step sideways costs
    width the map is not using, a step south costs the depth the troop wanted.
    """
    across, down = chip_box(config, zone)
    if not (_span_contains(across, position.x) and _span_contains(down, position.y)):
        return position

    if across.end - position.x <= down.end - position.y and across.end < zone.extent.end:
        return Vec2(across.end, position.y)
    if down.end < zone.lane.end:
        return Vec2(position.x, down.end)
    return Vec2(min(across.end, zone.extent.end), position.y)
