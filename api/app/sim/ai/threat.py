"""What is dangerous about an enemy, including the ones not in reach yet.

JQ-328 shipped a `danger` factor that counted only enemies already within their
own weapon range. Measured on the delivered evaluator, that makes danger inert
for almost every decision anyone cares about: a unit forty map units from
something that has to close to hit it scores `danger = 0.00` on every candidate,
so a wary profile and a reckless one weigh the same board. JQ-331's inspector
found the same thing from the other end — every report prints
`danger +0.00x2.5=+0.00`, and the `wary` ember-adept closes on enemies *more*
often than the aggressive hound, because its defining trait multiplies zero.

That is also why giving ground could not be scored. An option that buys safety
is worthless when nothing unsafe registers, so a withdraw would have lost to
everything and a retreat would have scored worse still.

**The fix is a closing term, and its shape is the point.** Whether backing off is
viable falls out of the *speed differential* rather than out of a stance flag or
a creature label: an ash-ram that cannot catch an ember-sprite stops registering
as danger to it the moment the sprite is actually leaving, while a cinder-hound
that can catch it goes on registering. Nobody writes "kiter" on a card. The
sprite kites the ram and stands and fights the hound because of what the two
stat blocks are, and if a debuff takes the sprite's speed away it stops kiting
anything without a line of data changing.

**Continuity at the reach boundary is deliberate.** An enemy exactly at its own
weapon range scores `EDGE_EXPOSURE` whichever branch computes it: the in-reach
branch because depth is zero there, the closing branch because slack is zero and
imminence is therefore one. `CONVENTIONS.md` asks for predicates that overlap on
an interval rather than meeting at a point, and two branches that disagree across
a boundary floating point cannot land on is the same bug in a different costume.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.geometry import distance
from app.sim.types import Vec2
from app.sim.world import Unit

#: What an enemy's damage counts for when you are at the very edge of its reach,
#: versus standing on top of it. Also the ceiling on what a threat that has not
#: closed yet can count for: something about to reach you is at most as dangerous
#: as something clipping you, never more.
EDGE_EXPOSURE = 0.5

#: How long a threat can be from reaching you before it stops weighing much, in
#: seconds. At exactly this far off it counts half what a threat in contact
#: counts; the curve is `1 / (1 + seconds / horizon)`, so it decays without ever
#: reaching zero for something that is genuinely still coming.
#:
#: Provisional, like every number in this package. Two seconds is forty ticks at
#: the default rate — long enough that a unit sees a charge coming and short
#: enough that it does not flinch at the whole map.
CLOSING_HORIZON_SECONDS = 2.0


@dataclass(frozen=True)
class Threat:
    """One enemy, judged from a particular position with a particular motion."""

    unit: Unit
    #: Distance from the position being judged to this enemy.
    gap: float
    #: How imminent this enemy's damage is, in `[0, 1]`. One when it can already
    #: swing; decaying with how long it would take to close the rest.
    imminence: float
    #: `unit.damage` scaled by imminence and by how deep inside its reach the
    #: judged position sits. What actually lands, near enough.
    incoming: float


def _depth(gap: float, reach: float) -> float:
    """How far inside an enemy's reach a position sits, in `[0, 1]`.

    Being *deep* inside counts for more than clipping the edge: a unit at the
    fringe can step back out next tick, one in the middle cannot. Without the
    gradient danger would be a step function, and since a unit covers only a few
    map units per tick almost every candidate would land on the same side of the
    step and the factor would tell them apart never.
    """
    if reach <= 0:
        return 1.0
    return 1.0 - gap / reach


def _imminence(gap: float, enemy: Unit, closing_rate: float) -> float:
    """How close this enemy is to being able to swing, given how we are moving.

    `closing_rate` is the rate at which the judged motion is *itself* closing the
    distance to this enemy — negative when the motion opens the gap. Added to the
    enemy's own speed, it gives the rate the gap actually shuts at. An enemy that
    cannot shut it at all scores nothing: that is a unit which can be held off,
    and it is the whole of what "the ember-sprite can hold off an ash-ram and not
    a cinder-hound" means.
    """
    slack = gap - enemy.range
    if slack <= 0:
        return 1.0

    approach = enemy.speed + closing_rate
    if approach <= 0:
        # It never arrives. Not a threat to this candidate, however hard it hits.
        return 0.0

    return 1.0 / (1.0 + (slack / approach) / CLOSING_HORIZON_SECONDS)


def closing_rate(before: Vec2, after: Vec2, enemy: Unit, seconds_per_tick: float) -> float:
    """How fast a move from `before` to `after` closes on `enemy`, per second.

    Derived from the two positions rather than from a bearing, which is what
    makes it right for free in the awkward cases: advancing on one enemy opens
    the gap to another behind you, and this says so without anyone reasoning
    about angles. A candidate that does not move gives zero, so a unit standing
    still lets every enemy approach at its own full speed.
    """
    if seconds_per_tick <= 0:
        return 0.0
    return (distance(before, enemy.position) - distance(after, enemy.position)) / seconds_per_tick


def threat_from(enemy: Unit, before: Vec2, after: Vec2, seconds_per_tick: float) -> Threat:
    """What `enemy` is worth to a unit that would move from `before` to `after`.

    **The split between the two positions is the whole of this function**, and it
    is what lets a disengagement score without making one free.

    An enemy that can *already* swing at `before` is paid for whatever the unit
    does: it is standing in reach at the top of the tick, and turning your back
    on something does not un-swing it. So that enemy is charged the worse of the
    two ends — walking deeper in costs more, walking out costs no less. JQ-328
    priced every enemy this way, and it had to: without a closing term there was
    nothing else to price. But applied to the enemies still on their way it made
    backing off strictly worthless rather than merely costly, because the
    standing end was always at least as bad as the leaving end and the worse of
    the two is therefore always the standing one. A `withdraw` scored exactly
    what a `hold` scored, every time, and the speed differential the ticket asks
    to derive behaviour from could not reach the result.

    An enemy that *cannot* swing yet is charged at `after` alone, with the motion
    counted against its approach. That is the half a unit can genuinely refuse:
    it cannot dodge what is already on it, and it can decline to let more arrive.
    An ash-ram that an ember-sprite is outrunning stops counting altogether; a
    cinder-hound that is faster than the sprite keeps counting, somewhat reduced,
    because the sprite is buying time rather than escape.

    Two identical positions mean a unit standing still, and `closing_rate` reads
    that off them — so a non-moving candidate needs no special case here.
    """
    gap_before = distance(before, enemy.position)
    gap_after = distance(after, enemy.position)
    rate = closing_rate(before, after, enemy, seconds_per_tick)

    def weight_at(gap: float) -> tuple[float, float]:
        if gap <= enemy.range:
            return EDGE_EXPOSURE + (1.0 - EDGE_EXPOSURE) * _depth(gap, enemy.range), 1.0
        imminence = _imminence(gap, enemy, rate)
        # Capped at the edge weight so the two branches agree where they meet.
        return EDGE_EXPOSURE * imminence, imminence

    weight, imminence = weight_at(gap_after)

    if gap_before <= enemy.range:
        standing, _ = weight_at(gap_before)
        weight = max(weight, standing)
        imminence = 1.0

    return Threat(unit=enemy, gap=gap_after, imminence=imminence, incoming=enemy.damage * weight)


def threats_against(
    enemies: tuple[Unit, ...],
    before: Vec2,
    after: Vec2,
    seconds_per_tick: float,
) -> tuple[Threat, ...]:
    """Every enemy, judged at `after`, for a unit that moved there from `before`.

    Order follows `enemies`, which `observe` has already sorted by id. Nothing
    here sorts again and nothing here filters: a threat worth nothing is still
    returned, so a caller can say "nothing threatens me" without distinguishing
    an empty field from a harmless one.
    """
    return tuple(threat_from(enemy, before, after, seconds_per_tick) for enemy in enemies)


def pressing(threats: tuple[Threat, ...]) -> tuple[Threat, ...]:
    """The threats actually contributing something, in the order given."""
    return tuple(threat for threat in threats if threat.incoming > 0)


def pressure(threats: tuple[Threat, ...], hp: float) -> float:
    """Total incoming as a fraction of what this unit has left to lose.

    The same quantity `scoring._exposure` turns into the danger factor, without
    the sign or the clamp, exposed so that a *candidate* can be gated on it.
    Scoring decides how much a unit minds its situation; this says whether the
    situation is one where a given option should be on the table at all.
    """
    incoming = sum(threat.incoming for threat in threats)
    return incoming / (hp if hp > 0 else 1.0)
