"""Formations, derived from the order and nothing else.

Every number about where a unit stands comes from here: the shape of the block,
which rank a unit is in, where in the deployment strip the troop starts, and the
spot on the map it is walking to. None of it is an input. A plan is five verbs;
this module is what turns a verb into a place.

Three constraints out of the JQ-243 readability work shape the layout:

* **Columns before rows.** A rank costs 21 px of the scarce portrait axis and a
  column costs 22 px of width the map is not using, so a troop widens until it
  runs out of room and only then deepens. At 375 px that is about fourteen
  columns, and a twenty-unit troop is as shallow as an eight-unit one was.
* **Summons in front.** Mages are the troop; the summons are what stands between
  them and the enemy. Push brings the mages close behind the line because the
  troop is meant to arrive together; Hold and Defend set them further back,
  where the line has time to form.
* **Hold builds around the mage.** A lane is held by a mage standing in its
  hotspot, so a holding troop's formation is anchored on the mage rank rather
  than the summon line: the mage stands on the objective and the screen forms up
  past it. Getting into scoring position and winning the ground in front of it
  are therefore the same act.
* **Nothing in the chip corner.** Each zone band reserves its top-left for the
  renderer's zone state chip, so no army size can occlude it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.map import MapConfig, clear_of_chip, zone_by_id
from app.sim.orders import Order, anchors_on_mage, faces_own_base, objective_position
from app.sim.rng import Rng
from app.sim.types import Side, Span, Vec2

#: Side-to-side gap between neighbours in a rank, in map units. Sprites are
#: 18-28 px wide (JQ-243), so this is a sprite plus a sliver of daylight.
FORMATION_SPACING = 24.0
#: Front-to-back gap between ranks.
FORMATION_RANK_GAP = 24.0
#: Hold and Defend: a clear rank of daylight behind the summon line, so the
#: screen has room to form and the mages are visibly a second rank.
MAGE_SETBACK_GUARDED = 24.0
#: Push: "close behind the line" — half a rank, so the troop arrives as one body.
MAGE_SETBACK_PUSH = 12.0
#: The measured ceiling at a 375 px portrait width (JQ-243).
MAX_RANK_COLUMNS = 14
#: A unit of jitter, so placement reads as an army rather than a spreadsheet.
DEPLOY_JITTER = 1.0


@dataclass(frozen=True)
class Formation:
    """Where each member of a troop stands, relative to the troop's objective.

    Offsets are in map coordinates and listed mages-first, matching the order
    `create_world` instantiates a troop in.
    """

    offsets: tuple[Vec2, ...]
    #: Total front-to-back extent, front rank to rear rank.
    depth: float
    #: How far ahead of the origin the front rank sits. Zero when the formation
    #: is built around its own front rank, the mage setback when it is built
    #: around the mage rank instead.
    lead: float
    #: How wide the summon line is, in columns.
    columns: int


def forward(side: Side) -> float:
    """Which way along the lane this side faces. North fights southward."""
    return 1.0 if side == "north" else -1.0


def columns_for(count: int, band_width: float) -> int:
    """How wide a block of `count` units spreads before it starts a second rank."""
    if count <= 0:
        return 1
    fits = max(1, int(band_width // FORMATION_SPACING))
    return max(1, min(count, fits, MAX_RANK_COLUMNS))


def _block(count: int, columns: int, depth_start: float) -> list[tuple[float, float]]:
    """A block of `count` slots as (sideways offset, depth), filling columns first."""
    return [
        (
            (index % columns - (columns - 1) / 2) * FORMATION_SPACING,
            depth_start + (index // columns) * FORMATION_RANK_GAP,
        )
        for index in range(count)
    ]


def _rows(count: int, columns: int) -> int:
    return -(-count // columns)


def _lane(facing: float, depth: float) -> float:
    """Depth turned into a lane offset. Zero stays positive zero: a negative zero
    survives into the serialised output and would make two identical battles
    compare unequal as text."""
    return -facing * depth if depth else 0.0


def derive_formation(
    order: Order,
    side: Side,
    mage_count: int,
    summon_count: int,
    band_width: float,
) -> Formation:
    """The troop's shape. Derived from the order; never supplied by a plan."""
    summon_columns = columns_for(summon_count, band_width)
    summons = _block(summon_count, summon_columns, 0.0)

    if summon_count > 0:
        setback = MAGE_SETBACK_PUSH if order.kind == "pushEnemyBase" else MAGE_SETBACK_GUARDED
        mage_depth = (_rows(summon_count, summon_columns) - 1) * FORMATION_RANK_GAP + setback
    else:
        # No summons to screen behind: the mages are the line.
        mage_depth = 0.0

    mages = _block(mage_count, columns_for(mage_count, band_width), mage_depth)
    slots = [*mages, *summons]

    # Depth is measured from the front rank; the origin is whichever rank the
    # objective is about. Shifting here rather than at every call site means a
    # unit's offset is always "where I stand relative to my troop's objective".
    origin = mage_depth if anchors_on_mage(order) else 0.0
    facing = forward(side)

    return Formation(
        offsets=tuple(Vec2(across, _lane(facing, depth - origin)) for across, depth in slots),
        depth=max((depth for _, depth in slots), default=0.0),
        lead=origin,
        columns=summon_columns,
    )


def deployment_band(
    config: MapConfig,
    side: Side,
    order: Order,
    share_index: int = 0,
    share_count: int = 1,
) -> Span:
    """The slice of the deployment strip one troop starts in.

    Derived from the order, like everything else: a troop holding a lane starts
    in the part of the strip **in front of that lane**, so it walks straight up
    its own lane rather than diagonally across the map. Troops sharing an order
    share that band side by side rather than stacking — three troops given three
    different orders start as three readable blocks.
    """
    strip = config.deployment[side]

    if order.kind == "holdZone" and order.zone_id is not None:
        zone = zone_by_id(config, order.zone_id)
        span = Span(
            max(strip.extent.start, zone.extent.start),
            min(strip.extent.end, zone.extent.end),
        )
    else:
        # Defend and Push are not about a lane, so they get the whole strip.
        span = strip.extent

    width = (span.end - span.start) / max(1, share_count)
    start = span.start + width * share_index
    return Span(start, start + width)


def deployment_anchor(
    config: MapConfig,
    side: Side,
    order: Order,
    band: Span,
    formation: Formation,
) -> Vec2:
    """Where the troop stands at the opening whistle.

    One rule covers every order: the troop starts on the side of the deployment
    strip nearest its objective. Hold and Push have their objective out in front,
    so they are pressed against the far edge; Defend base's objective is behind
    it, so it gives up all the strip's free depth and sits back against its own
    base. Either way the summons are the rank facing the enemy — a defending
    troop faces outward, it does not turn around.

    Expressed as the free depth given up rather than as "flush with an edge", so
    that a troop too deep for the strip degrades to the same spot under both
    readings instead of inverting them.

    Returns the position of the formation's **origin**, which is the mage rank
    under a Hold order and the summon line under the others — so `lead` is added
    to put the *front* rank where this rule says it goes either way.
    """
    strip = config.deployment[side]
    inset = FORMATION_SPACING / 2
    free = max(0.0, (strip.lane.end - strip.lane.start) - 2 * inset - formation.depth)
    far_edge = strip.lane.end if side == "north" else strip.lane.start
    given_up = free if faces_own_base(order) else 0.0
    setback = inset + given_up + formation.lead

    return Vec2((band.start + band.end) / 2, far_edge - setback * forward(side))


def _clamp_into(value: float, span: Span, inset: float) -> float:
    low, high = span.start + inset, span.end - inset
    if low > high:
        return (span.start + span.end) / 2
    return min(high, max(low, value))


def deployment_spot(config: MapConfig, side: Side, anchor: Vec2, offset: Vec2, rng: Rng) -> Vec2:
    """One unit's opening position: its slot in the formation, inside the strip.

    The jitter keeps two units off the same spot and gives a seeded battle a
    recognisable opening; it is drawn per unit so the draw order stays fixed.
    """
    strip = config.deployment[side]
    jitter = (rng.next_float() * 2 - 1) * DEPLOY_JITTER

    return Vec2(
        _clamp_into(anchor.x + offset.x + jitter, strip.extent, 0),
        _clamp_into(anchor.y + offset.y, strip.lane, 0),
    )


def station(order: Order, side: Side, offset: Vec2, config: MapConfig) -> Vec2:
    """Where a unit holding this formation slot is trying to stand, right now.

    Clamped into the region the order is about, so that a troop ordered to hold a
    zone ends up *in* the zone however big it has grown — a station outside the
    zone would score nothing — and routed out of the zone's reserved chip corner.
    """
    objective = objective_position(order, side, config)
    spot = Vec2(objective.x + offset.x, objective.y + offset.y)
    inset = FORMATION_SPACING / 2

    if order.kind == "holdZone" and order.zone_id is not None:
        zone = zone_by_id(config, order.zone_id)
        return clear_of_chip(
            config,
            zone,
            Vec2(_clamp_into(spot.x, zone.extent, inset), _clamp_into(spot.y, zone.lane, inset)),
        )

    if order.kind == "defendBase":
        strip = config.deployment[side]
        return Vec2(_clamp_into(spot.x, strip.extent, 0), _clamp_into(spot.y, strip.lane, 0))

    return Vec2(
        _clamp_into(spot.x, Span(0, config.size_width), inset),
        _clamp_into(spot.y, Span(0, config.size_height), inset),
    )
