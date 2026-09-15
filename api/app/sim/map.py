"""The map as data.

Zone count, each zone's depth, its horizontal extent, and its point value are all
map data rather than constants in the sim (design doc §4.12: "maps vary by data,
not by code").

**Zones are lanes, divided west to east.** They run alongside the attack axis
rather than across it, so every zone is the same distance from both bases and no
zone is safe for one player and deep for the other. The earlier layout stacked
them north to south, which gave each side a zone next to its own deployment strip
that the enemy never reached — free income nobody had to fight for, and a
dominant strategy of farming it. Measured before the change: a mirror ended
1795-1795 on every seed, and a player who committed everything to the contested
middle lost by 1633.

**Scoring sits on a hotspot, not on the whole lane.** A lane is a big box, and
"held when exactly one side is inside it" makes a single surviving straggler in a
corner enough to deny it. The hotspot is a small square at the centre of the
lane, and only a **mage** standing in it holds anything — so scoring means the
summon screen has already won the ground and the troop's slowest, most fragile
unit is now standing in the open. Denial goes back to being a combat outcome.

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
    #: Short label, as the design doc's W-E. Data, not an enum.
    id: str
    #: How far down the map the lane runs, north edge to south edge.
    lane: Span
    #: The lane's width. The gap between two lanes is the push corridor.
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
    #: Side of the square at the centre of each lane that a mage must stand in to
    #: hold it. One number for the map rather than a box per zone: an off-centre
    #: hotspot would make one lane worth more than another for reasons the player
    #: cannot see, and the whole point of lanes is that they are symmetric.
    hotspot_size: float = 60


#: v1 ships one map: two lanes divided west to east, with a push corridor up the
#: middle. Dimensions follow the JQ-243 readability plates — a 375 px portrait
#: width, and a 160 px lane holds six columns of sprites, which is a formation
#: rather than a queue. Three lanes at 125 px each would not.
#:
#: Two rather than three is a decision about the plan, not about the map: you
#: open at three mages, and three troops into two lanes forces you to double up
#: somewhere and your opponent to guess where. Three into three has an obvious
#: neutral answer.
TWO_LANE_MAP = MapConfig(
    id="two-lane",
    size_width=375,
    size_height=569,
    zones=[
        ZoneConfig("W", Span(100, 469), Span(0, 160), 1),
        ZoneConfig("E", Span(100, 469), Span(215, 375), 1),
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


def _overlaps(a: Span, b: Span) -> bool:
    """Whether two half-open intervals share any point."""
    return a.start < b.end and b.start < a.end


def _rectangles_overlap(lane_a: Span, extent_a: Span, lane_b: Span, extent_b: Span) -> bool:
    """Whether two map rectangles share any area.

    Lanes sit side by side and share their whole depth, so the old test — zones
    tile the lane axis in order — would reject every valid map now. Two zones
    only conflict when they overlap in *both* axes.
    """
    return _overlaps(lane_a, lane_b) and _overlaps(extent_a, extent_b)


def validate_map_config(config: MapConfig) -> None:
    """Raises unless the map is coherent. Called once, at battle start."""
    if config.size_width <= 0 or config.size_height <= 0:
        raise ValueError("map size must be positive")
    if not config.zones:
        raise ValueError("map must have at least one zone")
    if config.chip_reserve.width < 0 or config.chip_reserve.height < 0:
        raise ValueError("the chip reserve cannot be negative")
    if config.hotspot_size <= 0:
        raise ValueError("the hotspot must have a positive size")

    seen: set[str] = set()
    for index, zone in enumerate(config.zones):
        if zone.id in seen:
            raise ValueError(f'map has two zones called "{zone.id}"')
        seen.add(zone.id)

        _assert_span_within(zone.lane, config.size_height, f"zone {zone.id}")
        _assert_span_within(zone.extent, config.size_width, f"zone {zone.id} extent")

        if zone.points_per_tick <= 0:
            raise ValueError(f"zone {zone.id} is worth no points per tick")

        if zone.extent.end - zone.extent.start < config.hotspot_size:
            raise ValueError(f"zone {zone.id} is narrower than its hotspot")
        if zone.lane.end - zone.lane.start < config.hotspot_size:
            raise ValueError(f"zone {zone.id} is shallower than its hotspot")

        for other in config.zones[:index]:
            if _rectangles_overlap(zone.lane, zone.extent, other.lane, other.extent):
                raise ValueError(f"zones {other.id} and {zone.id} overlap")

    for side in SIDES:
        strip = config.deployment[side]
        _assert_span_within(strip.lane, config.size_height, f"{side} deployment strip")
        _assert_span_within(strip.extent, config.size_width, f"{side} deployment strip extent")

        for zone in config.zones:
            if _rectangles_overlap(strip.lane, strip.extent, zone.lane, zone.extent):
                raise ValueError(f"{side} deployment strip overlaps zone {zone.id}")

        base = config.bases[side]
        if base.max_hp <= 0:
            raise ValueError(f"{side} base has no HP")
        if base.footprint_radius < 0:
            raise ValueError(f"{side} base has a negative footprint")
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
    """The middle of the lane. Its hotspot sits here."""
    return Vec2(_span_centre(zone.extent), _span_centre(zone.lane))


def hotspot_box(config: MapConfig, zone: ZoneConfig) -> tuple[Span, Span]:
    """The square that has to be stood in to hold this lane, as (across, lane)."""
    centre = zone_centre(zone)
    reach = config.hotspot_size / 2
    return (
        Span(centre.x - reach, centre.x + reach),
        Span(centre.y - reach, centre.y + reach),
    )


def hotspot_centre(config: MapConfig, zone: ZoneConfig) -> Vec2:
    """Where a mage ordered to hold this lane is trying to stand."""
    return zone_centre(zone)


def hotspot_contains(config: MapConfig, zone: ZoneConfig, position: Vec2) -> bool:
    """Whether a position is inside this lane's hotspot."""
    across, down = hotspot_box(config, zone)
    return _span_contains(across, position.x) and _span_contains(down, position.y)


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
