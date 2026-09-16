"""What a player spell *is*, before a plan has been made.

`spells.py` holds the sim's side of a spell: an id, a tuple of effects, and the
`(tick, id, location, side)` envelope that fires one. That is deliberately
thin — the sim looks effects up in its own catalog so a client that lies about
a payload changes nothing.

This module is the layer above it, and the one JQ-297 is about: the **stable
definition** a spell is authored as, and the rules that turn a definition plus
a set of deployed mages into the effects the sim will actually run. Three
things live here and nowhere else.

**Mage tags (§4.8).** Disciplines, roles and personality. They are *not*
schools, and the distinction is load-bearing rather than tidy: a mage tagged
`artifice` is a mage who works in artifice, and that must never make it a
member of the Artifice faction, grant it Artifice summons, or feed the school
resonance curve in `resonance.py`. Nothing in this module or in `loadout.py`
reads `schools` at all, which is the only way to make that guarantee cheap —
there is no code path from a tag to a school to get wrong.

**Access.** How a spell reaches the menu: granted by deploying its mage
(`SignatureOf`), owned independently by the side's roster (`IndependentAccess`),
or always there (`AlwaysAvailable`). JQ-292's rule is that independent access is
*explicit data*, never inferred — a spell nobody was granted does not appear
because a tag happened to match.

**Per-effect scaling.** The heart of the ticket. A spell does not have one
strength; each of its numbers has its own bounded curve, keyed on the count of
deployed mages carrying one tag:

    bonus = min(cap, per_mage * max(0, support - threshold))
    value = base + bonus

So Fireball can take damage from `evocation` and radius from `reckless`
independently, which is exactly what JQ-292 asks to see demonstrated, and a
mage carrying both tags raises both numbers *once each* rather than multiplying
anything. Two properties make that a fact rather than an intention:

1. **A field has at most one curve.** `validate_definition` refuses a second
   scaling entry aimed at the same `(effect_index, field)`. Two tags stacking
   on one number is the shape a multiplication bug takes, so it is not
   expressible.
2. **Scaling is additive on the base value and capped per field.** There is no
   multiplier anywhere, and in particular no school-resonance term: JQ-292
   replaces player-spell strength scaling through resonance with this, and
   `resonance.py` keeps scaling *units* and nothing else.

Every number here is a tuning input under JQ-309's scheduling note, not a
balance claim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from types import MappingProxyType
from typing import Any, Literal, cast

from app.sim.effects import (
    AreaDamage,
    Burn,
    BurningGround,
    DashToTarget,
    Effect,
    EnergyRefill,
    Knockback,
)

# ----------------------------------------------------------------------- tags --

#: The initial tag vocabulary (JQ-292). Provisional, and grouped only in this
#: comment — the resolver treats every tag the same way, so a role tag and a
#: personality tag are interchangeable to it and a designer can add a fourth
#: axis without touching code.
#:
#: * discipline — `evocation`, `summoner`, `artifice`, `necromancy`, `warding`
#: * role — `vanguard`, `support`, `siege`
#: * personality — `reckless`, `patient`
#:
#: `artifice` and `necromancy` are in the list on purpose. They are the two
#: names that collide with faction names, and JQ-297 calls out that carrying
#: either must never imply membership. Leaving them out would have made the
#: guarantee untestable.
TAGS: tuple[str, ...] = (
    "artifice",
    "evocation",
    "necromancy",
    "patient",
    "reckless",
    "siege",
    "summoner",
    "support",
    "vanguard",
    "warding",
)

MageTag = str


# --------------------------------------------------------------------- access --


@dataclass(frozen=True, slots=True)
class AlwaysAvailable:
    """A basic fallback. On the menu whatever is fielded, including nothing.

    JQ-292 requires these so the spell step is never empty, and JQ-297 requires
    that they stay available — an army with no mage on it still has something
    to cast.
    """


@dataclass(frozen=True, slots=True)
class SignatureOf:
    """Granted by deploying this mage *type*, separate from its automatic ability.

    By type rather than by instance: two copies of the same mage grant the same
    spell, and the menu shows it once (JQ-297). Which instances did the granting
    is still reported — `ResolvedSpell.granted_by` — because the plan screen has
    to be able to say *why* a button is there.
    """

    mage_type_id: str


@dataclass(frozen=True, slots=True)
class IndependentAccess:
    """A roster spell, reached without fielding any particular mage.

    Two gates, both explicit, and both required:

    * the spell id is in the side's roster access list — the data JQ-292 says
      preconstructed supplies and a later constructed/draft mode would fill
      differently;
    * `requires_tag`, when set, has at least `minimum` deployed mages carrying
      it.

    A spell is never eligible because a tag merely matched. Without the roster
    grant the tag requirement is not even consulted.
    """

    requires_tag: MageTag | None = None
    minimum: int = 1


AccessRule = AlwaysAvailable | SignatureOf | IndependentAccess

#: How a spell reached the menu. Reported so the screen can group the menu the
#: way the design describes it rather than re-deriving the rule.
AccessKind = Literal["signature", "independent", "fallback"]


def access_kind(rule: AccessRule) -> AccessKind:
    if isinstance(rule, SignatureOf):
        return "signature"
    if isinstance(rule, IndependentAccess):
        return "independent"
    return "fallback"


# -------------------------------------------------------------------- scaling --


@dataclass(frozen=True, slots=True)
class EffectScaling:
    """One number of one effect, and the tag whose count raises it.

    `field` is a dotted path into the effect dataclass — `"radius"`, or
    `"damage.amount"` for the amount inside an `AreaDamage`'s `DamageProfile`.
    A path rather than a flat name because damage shaping lives on
    `DamageProfile` (see `effects.py`), so the number a designer wants to scale
    is genuinely one level down.

    The curve is bounded at both ends and stated in full here rather than
    spread across the resolver:

    * below `threshold` deployed mages carrying `tag`, nothing happens at all —
      a spell that wants two supporters before it does anything says so;
    * each mage past the threshold adds `per_mage`;
    * the total added is never more than `cap`.

    `cap` is mandatory. An unbounded curve is the one thing JQ-297 explicitly
    rules out ("each effect has its own bounded curve/threshold/cap"), and a
    default of infinity would have made forgetting it silent.
    """

    effect_index: int
    field: str
    tag: MageTag
    per_mage: float
    cap: float
    threshold: int = 0

    def bonus_at(self, support: int) -> float:
        """What `support` mages carrying this tag add to the field."""
        return min(self.cap, self.per_mage * max(0, support - self.threshold))


@dataclass(frozen=True, slots=True)
class SpellDefinition:
    """A spell as authored: a stable id, what it costs, and what it does.

    **Stable across rounds and matches**, and distinct from the deployed
    instance ids the resolver reads (JQ-297's "preserve stable definition IDs
    versus deployed instance IDs"). `effects` are the *base* values — what the
    spell does with no supporting tags at all, which is also what a zero-support
    resolution returns unchanged.
    """

    id: str
    name: str
    cost: float
    text: str
    access: AccessRule
    effects: tuple[Effect, ...]
    scaling: tuple[EffectScaling, ...] = ()

    @property
    def reads(self) -> tuple[MageTag, ...]:
        """The tags this spell's numbers key off, in first-mention order.

        Derived rather than declared: a `reads` list a designer maintained by
        hand would drift from the scaling that actually applies, and the plan
        screen prints this on the card.
        """
        found: list[MageTag] = []
        for entry in self.scaling:
            if entry.tag not in found:
                found.append(entry.tag)
        return tuple(found)


SpellDefinitionCatalog = Mapping[str, SpellDefinition]

EMPTY_DEFINITION_CATALOG: SpellDefinitionCatalog = MappingProxyType({})


# ------------------------------------------------------------- field access --


def read_field(effect: Effect, path: str) -> float:
    """The current value of a dotted field path on an effect."""
    value: Any = effect
    for part in path.split("."):
        value = getattr(value, part)
    return float(value)


def write_field(effect: Effect, path: str, value: float) -> Effect:
    """A copy of `effect` with the dotted field path set.

    Rebuilt with `dataclasses.replace` rather than mutated: effects are frozen
    and shared — a definition's base effects are read by every resolution of
    it — so scaling one for one side must not be visible to the other.
    """
    return cast(Effect, _write(effect, path, value))


def _write(node: Any, path: str, value: float) -> Any:
    head, _, rest = path.partition(".")
    if not rest:
        return replace(node, **{head: value})
    return replace(node, **{head: _write(getattr(node, head), rest, value)})


def _field_exists(effect: Effect, path: str) -> bool:
    node: Any = effect
    for part in path.split("."):
        if not is_dataclass(node) or part not in {f.name for f in fields(node)}:
            return False
        node = getattr(node, part)
    return isinstance(node, (int, float)) and not isinstance(node, bool)


# ----------------------------------------------------------------- validation --


def validate_definition(definition: SpellDefinition) -> None:
    """Raise `ValueError` unless this definition is one the resolver can run.

    Everything here is checked when a catalog is built rather than when a spell
    is cast, so a typo in a field path is a startup failure with the spell's
    name in it instead of a silently unscaled number in a battle.
    """
    if not definition.id.strip():
        raise ValueError("a spell definition needs an id")
    if not definition.effects:
        raise ValueError(f"spell {definition.id} has no effects, so casting it would do nothing")
    if definition.cost < 0:
        raise ValueError(f"spell {definition.id} has a negative cost")

    access = definition.access
    if isinstance(access, SignatureOf) and not access.mage_type_id.strip():
        raise ValueError(f"spell {definition.id} is a signature of no mage")
    if isinstance(access, IndependentAccess):
        if access.requires_tag is not None and access.requires_tag not in TAGS:
            raise ValueError(f"spell {definition.id} requires {access.requires_tag!r}, which is not a tag")
        if access.minimum < 1:
            raise ValueError(
                f"spell {definition.id} requires {access.minimum} mages; a minimum is at least 1"
            )

    # Keyed on (effect, field) rather than on the field name alone: two effects
    # in one spell may each have a `radius`, and each is scalable.
    claimed: dict[tuple[int, str], MageTag] = {}
    for entry in definition.scaling:
        if not 0 <= entry.effect_index < len(definition.effects):
            raise ValueError(
                f"spell {definition.id} scales effect {entry.effect_index}, "
                f"but it has {len(definition.effects)}"
            )
        effect = definition.effects[entry.effect_index]
        if not _field_exists(effect, entry.field):
            raise ValueError(
                f"spell {definition.id} scales {entry.field!r} on a "
                f"{type(effect).__name__}, which has no such number"
            )
        if entry.tag not in TAGS:
            raise ValueError(f"spell {definition.id} reads {entry.tag!r}, which is not a tag")
        if entry.cap < 0:
            raise ValueError(f"spell {definition.id} caps {entry.field!r} below zero")
        if entry.threshold < 0:
            raise ValueError(f"spell {definition.id} has a negative threshold on {entry.field!r}")

        key = (entry.effect_index, entry.field)
        if key in claimed:
            # The refusal JQ-297 is really asking for. Two tags feeding one
            # number is how "without automatically multiplying bonuses" gets
            # violated by accident, so it is rejected rather than defined.
            raise ValueError(
                f"spell {definition.id} scales {entry.field!r} on effect {entry.effect_index} "
                f"from both {claimed[key]!r} and {entry.tag!r}; a number takes one curve"
            )
        claimed[key] = entry.tag


def build_definition_catalog(definitions: Sequence[SpellDefinition]) -> SpellDefinitionCatalog:
    """Indexes spell definitions by their stable id, rejecting incoherent ones."""
    catalog: dict[str, SpellDefinition] = {}
    for definition in definitions:
        if definition.id in catalog:
            raise ValueError(f"spell {definition.id} is defined twice")
        validate_definition(definition)
        catalog[definition.id] = definition
    return MappingProxyType(catalog)


# ------------------------------------------------------------------- effect io --

#: The wire/fixture name of each effect primitive. Explicit rather than derived
#: from the class name, so renaming a Python class does not silently invalidate
#: every checked-in conformance fixture.
EFFECT_KINDS: Mapping[type, str] = MappingProxyType(
    {
        AreaDamage: "areaDamage",
        Burn: "burn",
        BurningGround: "burningGround",
        DashToTarget: "dashToTarget",
        EnergyRefill: "energyRefill",
        Knockback: "knockback",
    }
)


def camel(name: str) -> str:
    """`damage_per_second` -> `damagePerSecond`, for anything crossing to TypeScript."""
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def camel_path(path: str) -> str:
    return ".".join(camel(part) for part in path.split("."))


def effect_to_json(effect: Effect) -> dict[str, Any]:
    """An effect as the conformance fixtures and the client see it.

    Deliberately not `dataclasses.asdict`: the field names have to be camelCase
    on the other side of the fixture, and `kind` has to be a name the client can
    switch on. Walked in declaration order, so the JSON of a given effect is
    byte-stable across interpreters (`fields()` preserves declaration order;
    `__dict__` would not be a safe substitute under slots).
    """
    payload: dict[str, Any] = {"kind": EFFECT_KINDS[type(effect)]}
    for field in fields(effect):
        payload[camel(field.name)] = _value_to_json(getattr(effect, field.name))
    return payload


def _value_to_json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {camel(f.name): _value_to_json(getattr(value, f.name)) for f in fields(value)}
    return value
