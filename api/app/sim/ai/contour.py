"""A creature's ability contour: what its stat block is *for*.

The tactical premise this whole package rests on is that the pattern of high and
low numbers in a stat block is not decoration on top of a fighting style — it
**is** the fighting style. A creature that is tough and slow absorbs damage
because it cannot avoid it; one that is quick and fragile avoids damage because
it cannot absorb it. Neither needs to be labelled, and labelling them is how you
end up with a card whose behaviour and whose numbers disagree.

Two axes, both read off the unit as it stands:

* **Defence** — is this creature's toughness or its mobility the greater asset?
  Absorb or evade.
* **Offence** — does it hurt things by hitting them hard, by out-ranging them,
  or by spending a gauge?

**Why a roster scale is needed at all.** In the tabletop original the two
defensive abilities share one 3-18 scale, so asking which is higher is a
straight comparison. Here durability is hit points and mobility is map units per
second, and "70 HP versus 44 speed" means nothing on its own. So the battle's
own cards supply the scale: each stat is normalised across the roster, and the
*comparison* then happens inside the creature, as intended. A card is tough or
quick relative to what else is on the field, which is also the only sense in
which those words mean anything.

The payoff is that weights stop being something an author must write. A creature
with no profile at all still fights like its stat block says it should, and
`base_weights` becomes a deliberate departure from that rather than the only way
to say anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.sim.ai.factors import MAX_WEIGHT, FactorName, FactorWeights, clamp_weight, freeze_weights
from app.sim.units import UnitType, UnitTypeCatalog

Defence = Literal["absorb", "evade"]
Offence = Literal["brute", "skirmish", "ranged", "none"]

#: Where every derived weight starts before the contour pushes it around.
BASELINE = 1.0
#: How far a fully one-sided contour can move a single weight. Bounded so a
#: derived profile is opinionated rather than extreme — authored weights should
#: still be able to say something louder than the stat block does.
SWING = 0.75
#: Re-exported so a test can assert the bound without reaching past this module.
MAX_WEIGHT_CHECK = MAX_WEIGHT


@dataclass(frozen=True)
class RosterScale:
    """Per-stat spans across the battle's cards, for normalising one against another."""

    hp: tuple[float, float]
    speed: tuple[float, float]
    reach: tuple[float, float]
    damage: tuple[float, float]

    def rank(self, span: tuple[float, float], value: float) -> float:
        """Where `value` sits in `span`, as `[0, 1]`. Dead centre if the span is flat.

        A roster whose cards all have the same hit points says nothing about
        which of them is tough, and 0.5 is the honest answer to a question with
        no information in it — not zero, which would read as "the frailest".
        """
        low, high = span
        if high <= low:
            return 0.5
        return min(1.0, max(0.0, (value - low) / (high - low)))


def roster_scale(catalog: UnitTypeCatalog | Sequence[UnitType]) -> RosterScale:
    """Builds the scale from the cards a battle is actually fought with."""
    cards = list(catalog.values()) if isinstance(catalog, Mapping) else list(catalog)
    if not cards:
        return RosterScale((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0))

    def span(values: list[float]) -> tuple[float, float]:
        return (min(values), max(values))

    return RosterScale(
        hp=span([card.max_hp for card in cards]),
        speed=span([card.speed for card in cards]),
        reach=span([card.range for card in cards]),
        damage=span([card.damage for card in cards]),
    )


@dataclass(frozen=True)
class Contour:
    """One creature's read of its own stat block."""

    durability: float
    mobility: float
    reach: float
    force: float
    defence: Defence
    #: Descriptive rather than load-bearing: `derived_weights` reads the four
    #: ranks, not this. It is here for diagnostics (JQ-331) and for content work
    #: that wants to say what a card is without re-deriving it.
    offence: Offence

    @property
    def evasiveness(self) -> float:
        """How much this creature relies on not being hit, in `[0, 1]`.

        Damped by how much punishment it can take, and that second term is the
        one that matters. The naive reading — quicker than it is tough, so it
        must be avoiding damage — makes a creature that is high on *both* look
        like the most fragile thing on the field. A cinder-hound is the fastest
        card in the roster and the second toughest, and came out warier than an
        ember-sprite with half its hit points, which is precisely backwards.

        Something quick and sturdy does not avoid a fight, it wins one slowly:
        the reference calls that a scrappy skirmisher that does not mind a
        battle of attrition. Only the quick and *frail* are genuinely evasive.
        """
        return max(0.0, self.mobility - self.durability) * (1.0 - self.durability)

    @property
    def solidity(self) -> float:
        """And the reverse: how much more it absorbs than it avoids."""
        return max(0.0, self.durability - self.mobility)


def contour_of(
    max_hp: float,
    speed: float,
    reach: float,
    damage: float,
    scale: RosterScale,
    *,
    has_ability: bool = False,
) -> Contour:
    """Reads a stat block's pattern against the roster it is fighting in."""
    durability = scale.rank(scale.hp, max_hp)
    mobility = scale.rank(scale.speed, speed)
    reach_rank = scale.rank(scale.reach, reach)
    force = scale.rank(scale.damage, damage)

    if damage <= 0:
        # Nothing to be good at. The reference's read of a creature with every
        # physical ability low is that it avoids fighting altogether, and
        # labelling it a brute because zero force ties with zero reach would be
        # a lie the diagnostics then repeat.
        offence: Offence = "none"
    elif reach_rank > 0.5 and reach_rank >= force:
        offence = "ranged"
    elif force >= reach_rank and mobility <= durability:
        offence = "brute"
    else:
        offence = "skirmish"

    del has_ability  # Reserved: an ability is scored by `scoring.py`, not here.

    return Contour(
        durability=durability,
        mobility=mobility,
        reach=reach_rank,
        force=force,
        defence="absorb" if durability >= mobility else "evade",
        offence=offence,
    )


def derived_weights(contour: Contour) -> FactorWeights:
    """The weights a creature would hold if nobody authored any for it.

    Each line is one of the reference's derived styles, expressed as a push on a
    factor rather than as a named archetype — so a card that sits between two
    archetypes gets a blend rather than being forced into whichever bucket it is
    nearest:

    * **Tough absorbs, quick evades.** A creature that can take a hit discounts
      danger; one that cannot take a hit weighs it heavily, because avoiding
      damage is the only defence it has.
    * **Reach means fragility is survivable.** Something that fights from a
      distance has more to lose by being reached, so it prices danger higher
      still.
    * **Force wants targets.** A heavy hitter values a good target more than a
      light one does, because its swing settles more.
    * **The frail compensate with numbers.** A creature low on durability values
      company, which is the sense in which small weak things travel in packs.
    """
    weights: dict[FactorName, float] = {
        "objective_progress": BASELINE + SWING * (contour.mobility - 0.5),
        "target_suitability": BASELINE + SWING * (contour.force - 0.5) * 2,
        "danger": BASELINE + SWING * (contour.evasiveness + max(0.0, contour.reach - 0.5)),
        "ally_support": BASELINE + SWING * (1.0 - contour.durability - 0.5),
    }

    if contour.defence == "absorb":
        weights["danger"] -= SWING * contour.solidity

    return freeze_weights({factor: clamp_weight(value) for factor, value in weights.items()})
