"""Where a unit would stand, for each of the reasons it might want to stand there.

Four destinations, and every one of them is derived from the unit's own live
reach and speed rather than from anything written on its card. That is the same
rule `capabilities.py` holds for legality, applied to geometry: a creature
screens the way its stat block lets it screen, so a melee guard and an archer
handed the identical assignment produce different positions without either of
them being labelled.

=====================  ======================================================
Destination            What it is for
=====================  ======================================================
`useful_range`         the gap a unit wants between itself and a target
`standoff_position`    closing to that gap, rather than onto the target
`screen_position`      interposing between a threat and what it threatens
`give_ground_position` opening the gap, along the line the threats define
=====================  ======================================================

**`standoff_position` and `screen_position` are one operation.** Both stand a
weapon's reach away from the threat; they differ only in which way. Pointing back
at yourself is an approach, pointing at the thing you are covering is a screen.
Writing them as one primitive with two callers is not a saving, it is the claim
that screening *is* approaching from a particular side — which is what makes an
archer's screen sit behind the ally and a hound's sit in front of it, correctly,
with no special case for either.

Nothing here decides whether a position is a good idea. These are candidates;
`scoring.py` weighs them.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.capabilities import Capabilities
from app.sim.geometry import distance, point_along
from app.sim.types import UnitId, Vec2
from app.sim.world import Unit

#: How much of its reach a unit actually wants to use, as a fraction.
#:
#: **This must not be below `phases/movement.ENGAGEMENT_STANDOFF`**, and equality
#: is the tight end of that bound — `test_useful_range_is_not_inside_the_walking_standoff`
#: pins it. The standoff is the closest movement will let a unit walk to an
#: enemy; a unit that *wanted* to stand closer than movement allows would push
#: toward a destination it can never reach and never stop pushing. The two
#: numbers are declared separately because `ai/` cannot import `phases/` without
#: closing an import cycle, not because they are independent.
USEFUL_RANGE_FRACTION = 0.9

#: How far past the threats a give-ground destination is planted.
#:
#: The destination is a *bearing*, not a place anyone expects to arrive at: one
#: tick's walk is a few map units, and a destination that near would be reached
#: and abandoned immediately, leaving the unit stationary every other tick.
#: Planting it well beyond means the unit walks the bearing smoothly for as long
#: as backing off keeps scoring, and stops the tick it stops scoring.
GIVE_GROUND_LOOKAHEAD = 64.0


def useful_range(capabilities: Capabilities) -> float:
    """The distance this unit wants between itself and something it is fighting.

    Just inside its reach, so that "close enough to have arrived" and "close
    enough to shoot" are the same state rather than two states meeting at a
    single point. `CONVENTIONS.md` records the two separate occasions this file's
    neighbours got that wrong and froze a unit on a boundary for a whole battle.
    """
    return capabilities.reach * USEFUL_RANGE_FRACTION


def outranges(capabilities: Capabilities, other: Unit) -> bool:
    """Whether this unit can hit `other` from further off than `other` can reply.

    The precondition for giving ground *and still fighting*. A unit that does not
    outrange what is coming at it gains nothing by backing away slowly — it just
    spends the retreat being hit — so `withdraw` is offered on this and `retreat`,
    which stops fighting altogether, is not.
    """
    return capabilities.reach > other.range


def standoff_position(position: Vec2, target: Vec2, gap: float) -> Vec2:
    """The point `gap` from `target`, on the line back toward `position`.

    Where to walk to engage something: near enough to use the weapon, not so near
    as to stand inside it. A unit already closer than `gap` gets a point further
    out — `point_along` does not clamp — which is exactly what backing off to
    useful firing distance needs.
    """
    return point_along(target, position, gap)


def screen_position(threat: Vec2, protected: Vec2, gap: float) -> Vec2:
    """The point `gap` from `threat`, on the line toward what is being covered.

    The same operation as `standoff_position` pointed the other way, and the
    difference between a guard and an archer answering one assignment falls
    straight out of `gap` being each one's own useful range: a hound's screen is
    in the threat's face, an adept's is most of a lane back, and both are on the
    line the threat has to come down.
    """
    return point_along(threat, protected, gap)


@dataclass(frozen=True)
class Screened:
    """What a screen is covering, and whether anybody actually said so.

    The `assigned` flag exists because the difference is invisible from the
    outside and reads as a bug when it is not one. A screener covering the ally
    a coordinator named and a screener covering the ally it guessed at look
    identical in a battle — same verb, same line, same walk — but only one of
    them is doing what somebody asked. In a playtest, a guess that covers the
    *wrong* ally is exactly the kind of thing that gets written up as broken AI,
    and the only way to tell the two apart afterwards is to have recorded which
    path was taken. JQ-331's inspector prints it.
    """

    #: Where the screening line points. The only field the geometry uses.
    position: Vec2
    #: Who is being covered, or None when it is the unit's own post.
    unit_id: UnitId | None
    #: True when a coordinator named this ally, False when it was inferred here.
    assigned: bool


def protected_by(
    unit: Unit,
    allies: tuple[Unit, ...],
    threat: Unit,
    station: Vec2,
    protecting_id: UnitId | None = None,
) -> Screened:
    """What this unit would be screening `threat` away from.

    **`protecting_id` is an answer; everything below it is a guess.** A troop
    coordinator that assigned this unit to a threat knows which ally it assigned
    it *on behalf of*, and "answer that threat for that ally" is a strictly
    better instruction than "answer that threat" — the screening line is then the
    one the coordinator meant rather than the one this function inferred. JQ-330
    carries it on their `Assignment`; the parameter is here so consuming it is a
    wire-up rather than a redesign.

    Without one: the ally that threat is nearest to, which is the one it is most
    plausibly about to hit — ties broken on id, since `allies` arrives sorted and
    the comparison below keeps the first of an equal pair. With no allies at all
    there is still something to cover: the post this unit was given, which is
    what a lone guard is guarding.

    An earlier version also declined to cover an ally standing further from the
    threat than the unit's own post, on the theory that covering something that
    distant is leaving the line rather than holding it. It is not: an ally
    *behind* you is the ordinary case for a screen and the whole reason one is
    worth standing in. The rule quietly turned every such screen back into the
    station, which coincides with the approach whenever the unit is on the line
    already, so the candidate deduplicated away and no screen was ever generated
    in the arrangement screens exist for.
    """
    del unit  # The screener's own position decides the *gap*, not the line.

    if protecting_id is not None:
        named = next((ally for ally in allies if ally.id == protecting_id), None)
        if named is not None:
            return Screened(position=named.position, unit_id=named.id, assigned=True)
        # Assigned to cover something that has since died or left. Fall through
        # rather than refuse: the threat is still real and still worth screening,
        # and the result records that it is no longer the assigned one.

    nearest: Unit | None = None
    nearest_gap = float("inf")

    for ally in allies:
        gap = distance(threat.position, ally.position)
        if gap < nearest_gap:
            nearest = ally
            nearest_gap = gap

    if nearest is None:
        return Screened(position=station, unit_id=None, assigned=False)
    return Screened(position=nearest.position, unit_id=nearest.id, assigned=False)


def give_ground_position(position: Vec2, threats: tuple[Vec2, ...], lookahead: float) -> Vec2 | None:
    """A point `lookahead` further from the threats, or None if there is no away.

    The bearing is away from the threats' mean position rather than from the
    nearest one, so a unit with three things converging on it backs out of the
    middle instead of sidestepping one and into another.

    Returns None when the unit is standing exactly on that mean — genuinely
    surrounded, with every direction equally bad. There is no honest bearing
    there, and inventing one would put a unit's escape route on whichever way
    floating point happened to round. It holds instead, and the fight decides it.
    """
    if not threats:
        return None

    centre = Vec2(
        sum(threat.x for threat in threats) / len(threats),
        sum(threat.y for threat in threats) / len(threats),
    )

    gap = distance(centre, position)
    if gap == 0:
        return None

    return point_along(centre, position, gap + lookahead)
