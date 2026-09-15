"""State an effect leaves behind on the field.

Separate from `effects.py` because the two are different things: an effect is
the declaration on a card, a status is the consequence sitting on a unit or on
the ground afterwards. `world.py` holds these, so they must not import it.

Both carry the tick count they have left rather than a deadline. Durations are
counted down in whole ticks for the reason `config.to_ticks` gives: subtracting
0.05 twenty times does not reliably land on zero, and a status that sometimes
lasts an extra tick is a determinism bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.types import Side, UnitRef, Vec2


@dataclass
class BurnStatus:
    """A burn sitting on one unit. A unit carries at most one.

    Spreading happens once, when the burn is applied — `resolution.py` lights
    the victim's neighbours there and then. Nothing about the hop survives onto
    the status, which is what makes "exactly one hop" true by construction
    rather than by a counter something could get wrong.

    A second application refreshes this one to the stronger of the two on each
    axis instead of stacking: two mages burning the same target should not
    multiply, and a weaker burn should not cut a stronger one short.
    """

    damage_per_tick: float
    ticks_remaining: int
    bonus_vs_mage: float = 1.0
    #: Who lit it, for the event stream. The caster may be dead by the time it bites.
    source: UnitRef | None = None


@dataclass
class GroundHazard:
    """An area that does something to whoever stands in it.

    v1 has one kind — burning ground — but the shape is general, because an
    Artifice roster's ground effects should be data on this rather than a
    second nearly-identical list in the world.
    """

    id: str
    kind: str
    #: Whose hazard it is. It bites the other side.
    side: Side
    center: Vec2
    radius: float
    damage_per_tick: float
    ticks_remaining: int
    bonus_vs_mage: float = 1.0
    source: UnitRef | None = None


BURNING_GROUND = "burningGround"
