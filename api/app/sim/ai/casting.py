"""Spending an ability when the decision loop says to, and not before.

JQ-288 made a full gauge mean *available* rather than *fired*, and left a seam
for whatever is making decisions to say when the moment has come. This is the
behaviour layer's side of it.

The rule is the same one movement follows, for the same reason: **a unit
carrying an intent does what it decided.** If the loop chose to cast, this aims
the cast at the target the loop chose. If it chose anything else — to swing, to
press on, to stand still — the gauge is held, because the alternative is a unit
whose ability fires against its own judgement the moment the bar fills.

A unit with no behaviour data falls through to the default policy, so a battle
shipping no library casts exactly as it did before this existed. That is the
same fallback shape as the movement phase's, and it is what lets the behaviour
layer land without changing any battle that has not opted into it.
"""

from __future__ import annotations

from app.sim.abilities import Ability
from app.sim.casting import DEFAULT_CAST_POLICY, AimedCast, CastPolicy
from app.sim.effects import ORIGIN_SELF
from app.sim.world import Unit, World


class FollowsIntent:
    """Casts what the decision phase committed to, and holds otherwise."""

    name = "followsIntent"

    __slots__ = ("fallback",)

    def __init__(self, fallback: CastPolicy = DEFAULT_CAST_POLICY) -> None:
        #: For units with no behaviour attached. Never consulted for one that has.
        self.fallback = fallback

    def aim(self, world: World, unit: Unit, ability: Ability, target: Unit | None) -> AimedCast | None:
        ai = unit.ai
        if ai is None:
            return self.fallback.aim(world, unit, ability, target)

        intent = ai.intent
        if intent is None or intent.kind != "cast" or intent.ability_id != ability.id:
            # Held. The loop weighed this cast against everything else the unit
            # could do and preferred something else; firing anyway would make
            # the gauge, not the decision, the thing in charge.
            return None

        if ability.origin == ORIGIN_SELF:
            return AimedCast(origin=unit.position, follows_caster=True)

        chosen = _living_enemy(world, unit, intent.target_id)
        if chosen is None:
            # The committed target died or left between deciding and casting.
            # Hold rather than substituting one: the loop picked that unit for
            # reasons, and the next tick will pick again with the field as it is.
            return None

        return AimedCast(origin=chosen.position, target=chosen)


def _living_enemy(world: World, unit: Unit, target_id: str | None) -> Unit | None:
    if target_id is None:
        return None

    for candidate in world.units:
        if candidate.id == target_id:
            legal = candidate.side != unit.side and candidate.hp > 0
            return candidate if legal else None

    return None
