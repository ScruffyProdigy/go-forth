"""When a unit with a ready ability actually spends it.

A full gauge does **not** fire the ability. It makes it *available*, and
something then decides whether this tick is the moment — which is the whole
point of having a dash: you hold it until the gap is worth closing, and you
would rather not spend it shoving a cheap melee summon that was walking into
your face anyway when a ranged unit is standing behind it.

That decision belongs to the behaviour layer (JQ-296/328), not here. This
module is the seam it plugs into, plus a deliberately unclever default so a
battle with no behaviour data still does something sensible.

The seam is a `CastPolicy`: given a unit whose gauge is full, either aim the
cast or decline it for now. Declining costs nothing — the gauge stays full and
the unit is asked again next tick.

Deliberately a leaf. It must not import `resolution`, `context`, or anything
under `phases` — `TickContext` holds a policy, so a reach back into the phases
package would drag its `__init__` in half-initialised and the whole sim would
fail to import. The policy answers *whether and where*; the abilities phase
turns that answer into a cast, and passes in the target it already found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.sim.abilities import Ability
from app.sim.effects import ORIGIN_SELF, DashToTarget
from app.sim.geometry import distance
from app.sim.types import Vec2
from app.sim.world import Unit, World


def ability_ready(unit: Unit, ability: Ability) -> bool:
    """Whether this unit's gauge has reached its ability's cost."""
    return unit.energy >= ability.energy_cost


@dataclass(frozen=True)
class AimedCast:
    """A decision to cast, and what it is aimed at."""

    origin: Vec2
    target: Unit | None = None
    #: Whether the origin rides along with the caster — see `resolution.Cast`.
    follows_caster: bool = False


class CastPolicy(Protocol):
    """Decides whether a unit spends a ready ability this tick, and on what.

    Returning None holds the ability. It is not a refusal, only "not yet".
    """

    name: str

    def aim(self, world: World, unit: Unit, ability: Ability, target: Unit | None) -> AimedCast | None: ...


class FirstUsefulMoment:
    """The default: cast as soon as the cast would accomplish something.

    Unclever on purpose. It is a placeholder for a behaviour layer that weighs
    what else is coming, and it exists so that a battle shipping no behaviour
    data still fires its abilities rather than hoarding them forever.

    It knows two things, and they are the two that are wrong often enough to
    matter without any notion of the future:

    * **An ability that needs a target holds until there is one.** Spending a
      full gauge on empty air makes a card's output depend on when its last
      enemy died, which is not something a designer can tune.
    * **A dash holds while its target is already in weapon range.** The dash is
      for closing a gap; spent on something the unit could already hit, it buys
      nothing and the gauge could have carried it to the next fight.

    What it does *not* do is prefer one target over another, hold for a better
    one, or spend a gauge in anticipation. That is JQ-296/328's job.
    """

    name = "firstUsefulMoment"

    def aim(self, world: World, unit: Unit, ability: Ability, target: Unit | None) -> AimedCast | None:
        if ability.origin == ORIGIN_SELF:
            return AimedCast(origin=unit.position, follows_caster=True)

        if target is None:
            return None

        if self._would_waste_a_dash(unit, ability, target):
            return None

        return AimedCast(origin=target.position, target=target)

    @staticmethod
    def _would_waste_a_dash(unit: Unit, ability: Ability, target: Unit) -> bool:
        dashes = [effect for effect in ability.effects if isinstance(effect, DashToTarget)]
        if not dashes:
            return False

        # Already close enough to swing: the dash would move the unit almost
        # nowhere and the rest of the card would land either way.
        return distance(unit.position, target.position) <= unit.range


DEFAULT_CAST_POLICY: CastPolicy = FirstUsefulMoment()
