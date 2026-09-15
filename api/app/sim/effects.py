"""The effect vocabulary — what an ability or a spell actually does.

This is the contract JQ-185's Fire roster has to be expressible in: every
ability on it reduces to the primitives below, declared as data, with no
bespoke code behind any one card. A new card is a new `Ability` holding a
different tuple of these; a new *primitive* is the only thing that costs code,
and needing one is the signal that the design has left the vocabulary.

Effects are inert data. They hold no world state and know nothing about how
they are applied — `resolution.py` owns that, which is what keeps this module
importable from anywhere without a cycle.

Damage-shaping lives on `DamageProfile` rather than in separate effects.
`bonus_vs_mage` and `bonus_vs_base` are listed as primitives in JQ-288, but a
"bonus vs mage" that is not attached to a blow does nothing, so they ride along
on every primitive that deals damage and each one can be tuned per card.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where the effects of a cast are centred.
#:
#: ``self`` puts them on the caster — the shape a self-buff or an aura wants.
#: ``target`` puts them on the acquired enemy, and a cast with no target is
#: held rather than wasted. A spell is injected with an explicit location and
#: uses neither.
CastOrigin = str

ORIGIN_SELF: CastOrigin = "self"
ORIGIN_TARGET: CastOrigin = "target"
CAST_ORIGINS: tuple[CastOrigin, ...] = (ORIGIN_SELF, ORIGIN_TARGET)


@dataclass(frozen=True)
class DamageProfile:
    """How much a blow lands for, and what it lands especially hard on."""

    amount: float
    #: Multiplier applied when the victim is a mage. 1.0 is no bonus.
    bonus_vs_mage: float = 1.0
    #: Multiplier applied when the blow lands on a base rather than a unit.
    bonus_vs_base: float = 1.0

    def against_unit(self, kind: str) -> float:
        return self.amount * (self.bonus_vs_mage if kind == "mage" else 1.0)

    def against_base(self) -> float:
        return self.amount * self.bonus_vs_base


@dataclass(frozen=True)
class DashToTarget:
    """Closes on the cast's target, up to `max_distance` map units.

    Stops `stop_short` units out so the dash ends in weapon range rather than
    inside the target — the engagement gap JQ-243 asks for.
    """

    max_distance: float
    stop_short: float = 0.0


@dataclass(frozen=True)
class AreaDamage:
    """One blow to every enemy within `radius` of the cast origin.

    The enemy base counts as a target when it stands inside the radius, which
    is what makes `bonus_vs_base` mean anything. Destroying a base is slice B's
    ending, not this one's: the HP comes off and the battle runs on.
    """

    radius: float
    damage: DamageProfile
    #: Whether the blow reaches the enemy base standing inside the radius.
    hits_base: bool = True


@dataclass(frozen=True)
class Burn:
    """A damage-over-time that spreads exactly one hop.

    Every enemy within `radius` catches it. Each of *those* passes it to its own
    neighbours within `spread_radius` and there it stops — a spread copy never
    spreads again, so a packed line does not carry a single burn end to end.
    Set `spread_radius` to 0 for a burn that does not travel at all.
    """

    radius: float
    damage_per_second: float
    duration_seconds: float
    spread_radius: float = 0.0
    bonus_vs_mage: float = 1.0


@dataclass(frozen=True)
class BurningGround:
    """An area that damages enemies standing in it until it burns out."""

    radius: float
    damage_per_second: float
    duration_seconds: float
    bonus_vs_mage: float = 1.0


@dataclass(frozen=True)
class Knockback:
    """Shoves enemies within `radius` away from the origin.

    An emplacement holds position (JQ-288: it "holds position"), so it is the
    one thing knockback does not move.
    """

    radius: float
    distance: float


@dataclass(frozen=True)
class EnergyRefill:
    """Tops up the gauges of nearby allies.

    The caster is excluded by default: a self-refill on a cast that costs a full
    gauge is a card that never stops casting.
    """

    radius: float
    amount: float
    include_self: bool = False


#: Every primitive, as declared data. A card is a tuple of these.
Effect = DashToTarget | AreaDamage | Burn | BurningGround | Knockback | EnergyRefill

EFFECT_KINDS: tuple[type, ...] = (
    DashToTarget,
    AreaDamage,
    Burn,
    BurningGround,
    Knockback,
    EnergyRefill,
)
