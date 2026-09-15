"""Abilities — the automatic cast a full energy gauge fires.

An ability is *only* data: an id, what a full gauge costs, how far it reaches,
where its effects land, and the tuple of primitives from `effects.py` it
resolves into. Nothing about a particular card lives in code, which is the
whole point of JQ-288 — JQ-185's Fire roster has to be expressible here, and a
card that needs a `if ability_id == ...` anywhere has broken the contract.

Abilities are a separate concept from player spells (JQ-292/297): an ability is
automatic and fires off its own gauge, a spell is cast by a player at a
location. They share the effect machinery below them and nothing above it.

The catalog is resolved once at battle start and read through the tick
context, which is why `UnitType` names an ability by id rather than holding
one — a value type that pointed at effects would drag the whole vocabulary
into `units.py` and back out again as an import cycle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from app.sim.effects import CAST_ORIGINS, ORIGIN_TARGET, CastOrigin, Effect


@dataclass(frozen=True)
class Ability:
    id: str
    #: The gauge's full mark. Reaching it casts, and the gauge resets to zero.
    energy_cost: float
    effects: tuple[Effect, ...] = field(default_factory=tuple)
    #: Where the effects land. `target` holds the cast until there is one.
    origin: CastOrigin = ORIGIN_TARGET
    #: How far a target may be. None means the unit's own weapon range.
    range: float | None = None


AbilityCatalog = Mapping[str, Ability]

EMPTY_ABILITY_CATALOG: AbilityCatalog = MappingProxyType({})


def _validate(ability: Ability) -> None:
    if not ability.energy_cost > 0:
        raise ValueError(
            f"ability {ability.id} has an energy cost of {ability.energy_cost}; "
            "a gauge that is full at zero would cast every tick"
        )
    if ability.origin not in CAST_ORIGINS:
        raise ValueError(
            f"ability {ability.id} has origin {ability.origin!r}; expected one of {CAST_ORIGINS}"
        )
    if ability.range is not None and ability.range < 0:
        raise ValueError(f"ability {ability.id} has a negative range")
    if not ability.effects:
        raise ValueError(f"ability {ability.id} has no effects, so casting it would do nothing")


def build_ability_catalog(abilities: Sequence[Ability]) -> AbilityCatalog:
    """Indexes the battle's abilities by id, rejecting incoherent ones up front."""
    catalog: dict[str, Ability] = {}

    for ability in abilities:
        if ability.id in catalog:
            raise ValueError(f"ability {ability.id} is defined twice")
        _validate(ability)
        catalog[ability.id] = ability

    return MappingProxyType(catalog)
