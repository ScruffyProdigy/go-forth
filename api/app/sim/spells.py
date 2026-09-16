"""Player spells, injected from outside the battle.

A spell is an effect fired at a location by an external trigger, which is why
JQ-288 carries it rather than giving it a ticket: once abilities resolve
through `resolution.py`, a spell is the same machinery with a different
trigger. It shares the vocabulary and shares nothing else — a spell has no
gauge, no caster on the field, and no school-resonance strength scaling
(JQ-288 is explicit: that scaling is for unit abilities only).

An injection is the `(tick, spellId, location)` envelope JQ-288 asks for, plus
the side it was cast by, because "enemy" is not derivable from a point on the
map. It carries no damage: the sim looks the effects up in its own catalog, so
a client that lies about a spell's payload changes nothing. JQ-187/188 own the
seat, the tick and whether the cast was legal at all; a rejected cast never
becomes an injection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from app.sim.effects import Effect
from app.sim.types import Side, Vec2


@dataclass(frozen=True)
class Spell:
    id: str
    effects: tuple[Effect, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SpellInjection:
    """One scheduled cast: what fires, when, where, and for whom."""

    tick: int
    spell_id: str
    location: Vec2
    side: Side


SpellCatalog = Mapping[str, Spell]

EMPTY_SPELL_CATALOG: SpellCatalog = MappingProxyType({})


def build_spell_catalog(spells: Sequence[Spell]) -> SpellCatalog:
    catalog: dict[str, Spell] = {}

    for spell in spells:
        if spell.id in catalog:
            raise ValueError(f"spell {spell.id} is defined twice")
        if not spell.effects:
            raise ValueError(f"spell {spell.id} has no effects, so casting it would do nothing")
        catalog[spell.id] = spell

    return MappingProxyType(catalog)


def injection_order(injection: SpellInjection) -> tuple[int, str, str, float, float]:
    """The sort key two injections are compared on.

    The whole envelope rather than the tick alone: two spells landing on one
    tick must not depend on the order the match layer happened to hand them
    over in. Named rather than inlined because a cast accepted mid-battle is
    inserted into an already-sorted list (`BattleRunner.inject`) and has to land
    where this same key would have put it.
    """
    return (
        injection.tick,
        injection.spell_id,
        injection.side,
        injection.location.x,
        injection.location.y,
    )


def schedule_injections(injections: Sequence[SpellInjection], catalog: SpellCatalog) -> list[SpellInjection]:
    """Orders the battle's injections so two on the same tick resolve the same way."""
    for injection in injections:
        if injection.spell_id not in catalog:
            raise ValueError(f"spell {injection.spell_id} is injected but is not in the spell catalog")
        if injection.tick < 1:
            raise ValueError(
                f"spell {injection.spell_id} is injected at tick {injection.tick}; "
                "tick 0 is the opening state, before any phase has run"
            )

    return sorted(injections, key=injection_order)
