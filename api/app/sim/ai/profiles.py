"""Behavior as data: creature defaults, individual overrides, mage personalities.

Four vocabularies meet near here and the ticket is explicit that they must stay
apart, so to be unambiguous:

=================  ====================================  ==================
Vocabulary         Lives in                              Example
=================  ====================================  ==================
School (faction)   `schools.py`                          ``fire``
Creature type      `units.py`, a `UnitType.id`           ``cinder-hound``
Behavioral trait   here, a `TraitTag`                    ``skittish``
Mage personality   here, a `PersonalityTag`              ``reckless``
=================  ====================================  ==================

Spell tags are JQ-288's and appear nowhere in this module. `TraitTag` and
`PersonalityTag` are distinct `NewType`s over `str` rather than one shared alias
so that handing a personality where a trait belongs is a type error, not a
mystery at runtime. Both are open vocabularies — content work adds a tag by
adding a definition, not by editing an enum.

**Composition.** A unit's weights are built in one fixed order:

1. the creature-type profile's base weights (anything unset is neutral),
2. trait deltas, from the type's traits plus the individual's additions, minus
   the individual's removals,
3. personality deltas, scaled by strength, from the unit's own personalities and
   from the mages of its troop,
4. clamp every weight into `[0, MAX_WEIGHT]`.

Two rules make that reproducible. **Conflicts resolve by summation, never by
precedence** — a bold trait and a wary trait pulling on `danger` add up and both
show in the result, so no modifier silently wins on the strength of where it was
declared. And every list is **sorted by tag before it is summed**, because
floating-point addition is not associative: the same modifiers applied in a
different order give a different last bit, which is exactly the kind of drift the
determinism tests exist to catch.

**Strength.** A personality reference carries a tag and an optional strength; an
omitted strength resolves to the definition's default. Strength scales a
personality's contribution and nothing else — never legality, never capabilities.
Strength zero contributes nothing; it does not invert the personality, because a
"reckless mage, dialled to zero" is a mage with no opinion, not a cautious one.

Numbers here are provisional tuning data. The shapes are the deliverable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, NewType

from app.sim.ai.capabilities import (
    Capabilities,
    CapabilityName,
    missing_capabilities,
    validate_capability_names,
)
from app.sim.ai.factors import (
    FACTORS,
    NEUTRAL_WEIGHTS,
    FactorName,
    FactorWeights,
    clamp_weight,
    freeze_weights,
    validate_deltas,
    validate_weights,
)
from app.sim.types import TroopId, UnitId
from app.sim.units import UnitTypeCatalog

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from app.sim.world import Unit

TraitTag = NewType("TraitTag", str)
PersonalityTag = NewType("PersonalityTag", str)

#: Strength is a finite, non-negative dial. Zero means "no opinion"; the ceiling
#: keeps a stack of enthusiastic mages from running away with the weights.
MIN_STRENGTH = 0.0
MAX_STRENGTH = 2.0

#: Tie-break jitter's ceiling, as a fraction of a score. Zero by default, which
#: is the only setting under which a battle is reproducible without drawing.
MAX_JITTER = 0.25


@dataclass(frozen=True)
class TraitDefinition:
    """What a behavioral trait does to the weights, and what it needs to work."""

    tag: TraitTag
    #: Added to the weights. May be negative; the sum is clamped, not the term.
    weights: Mapping[FactorName, float] = field(default_factory=dict)
    #: Capabilities a creature must have for this trait to mean anything.
    requires: tuple[CapabilityName, ...] = ()


@dataclass(frozen=True)
class PersonalityDefinition:
    """A mage personality: weight deltas, scaled by strength when applied."""

    tag: PersonalityTag
    #: Used when a reference omits its strength override.
    default_strength: float
    weights: Mapping[FactorName, float] = field(default_factory=dict)
    requires: tuple[CapabilityName, ...] = ()


@dataclass(frozen=True)
class PersonalityRef:
    """A tag, and optionally how strongly. Omitted strength means the default."""

    tag: PersonalityTag
    strength: float | None = None


@dataclass(frozen=True)
class CreatureProfile:
    """Defaults for everything of one creature type."""

    type_id: str
    #: Anything left out is neutral, not zero — an unmentioned factor still counts.
    base_weights: Mapping[FactorName, float] = field(default_factory=dict)
    traits: tuple[TraitTag, ...] = ()
    #: Seeded randomness, drawn only when this is above zero. See `decide.py`.
    tie_break_jitter: float = 0.0


@dataclass(frozen=True)
class UnitBehavior:
    """One individual's departures from its type's profile."""

    unit_id: UnitId
    traits: tuple[TraitTag, ...] = ()
    #: Traits this individual does not have, despite its type.
    removed_traits: tuple[TraitTag, ...] = ()


@dataclass(frozen=True)
class MagePersonality:
    """A mage's personality references. Reaches its own troop's summons too."""

    unit_id: UnitId
    personalities: tuple[PersonalityRef, ...] = ()


@dataclass(frozen=True)
class BehaviorLibrary:
    """Every definition and profile a battle uses. Validated once, at build."""

    traits: tuple[TraitDefinition, ...] = ()
    personalities: tuple[PersonalityDefinition, ...] = ()
    profiles: tuple[CreatureProfile, ...] = ()
    unit_behaviors: tuple[UnitBehavior, ...] = ()
    mage_personalities: tuple[MagePersonality, ...] = ()


EMPTY_LIBRARY = BehaviorLibrary()


@dataclass(frozen=True)
class ResolvedBehavior:
    """One unit's composed weights, plus what went into them.

    Immutable, and shared by reference across the per-tick world snapshots — see
    `__deepcopy__`. JQ-331's inspector reads `traits` and `personalities` to
    explain a decision without re-running the composition.
    """

    weights: FactorWeights
    traits: tuple[TraitTag, ...] = ()
    #: Tag and resolved strength, sorted by tag. Diagnostics only.
    personalities: tuple[tuple[PersonalityTag, float], ...] = ()
    tie_break_jitter: float = 0.0

    def __deepcopy__(self, memo: dict[int, object]) -> ResolvedBehavior:
        """Frozen and never mutated, so a snapshot can share it.

        `run_battle` deep-copies the whole world once per tick. Copying an
        immutable weights record 1800 times a battle buys nothing.
        """
        return self


NEUTRAL_BEHAVIOR = ResolvedBehavior(weights=NEUTRAL_WEIGHTS)


def _validate_strength(value: float, what: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{what} has strength {value!r}, which is not a number")
    if value < MIN_STRENGTH or value > MAX_STRENGTH:
        raise ValueError(
            f"{what} has strength {value}; strength runs {MIN_STRENGTH} to {MAX_STRENGTH}. "
            f"Zero means no preference — it does not invert the personality"
        )
    return float(value)


def _index_traits(library: BehaviorLibrary) -> Mapping[TraitTag, TraitDefinition]:
    index: dict[TraitTag, TraitDefinition] = {}
    for definition in library.traits:
        if definition.tag in index:
            raise ValueError(f"behavioral trait {definition.tag!r} is defined twice")
        validate_deltas(definition.weights, f"trait {definition.tag!r}")
        validate_capability_names(definition.requires, f"trait {definition.tag!r}")
        index[definition.tag] = definition
    return MappingProxyType(index)


def _index_personalities(library: BehaviorLibrary) -> Mapping[PersonalityTag, PersonalityDefinition]:
    index: dict[PersonalityTag, PersonalityDefinition] = {}
    for definition in library.personalities:
        if definition.tag in index:
            raise ValueError(f"mage personality {definition.tag!r} is defined twice")
        validate_deltas(definition.weights, f"personality {definition.tag!r}")
        validate_capability_names(definition.requires, f"personality {definition.tag!r}")
        _validate_strength(definition.default_strength, f"personality {definition.tag!r}")
        index[definition.tag] = definition
    return MappingProxyType(index)


def _index_profiles(library: BehaviorLibrary, catalog: UnitTypeCatalog) -> Mapping[str, CreatureProfile]:
    index: dict[str, CreatureProfile] = {}
    for profile in library.profiles:
        if profile.type_id in index:
            raise ValueError(f"creature type {profile.type_id!r} has two behavior profiles")
        if profile.type_id not in catalog:
            raise ValueError(
                f"behavior profile names creature type {profile.type_id!r}, "
                f"which is not in the unit type catalog"
            )
        validate_weights(profile.base_weights, f"profile {profile.type_id!r}")
        if not isinstance(profile.tie_break_jitter, (int, float)) or isinstance(
            profile.tie_break_jitter, bool
        ):
            raise ValueError(f"profile {profile.type_id!r} has a non-numeric tie_break_jitter")
        if profile.tie_break_jitter < 0 or profile.tie_break_jitter > MAX_JITTER:
            raise ValueError(
                f"profile {profile.type_id!r} has tie_break_jitter {profile.tie_break_jitter}; "
                f"the range is 0 to {MAX_JITTER}"
            )
        index[profile.type_id] = profile
    return MappingProxyType(index)


@dataclass(frozen=True)
class BehaviorIndex:
    """A library, checked over and indexed for lookup. Built once per battle."""

    traits: Mapping[TraitTag, TraitDefinition]
    personalities: Mapping[PersonalityTag, PersonalityDefinition]
    profiles: Mapping[str, CreatureProfile]
    unit_behaviors: Mapping[UnitId, UnitBehavior]
    #: Personality refs by the mage that holds them.
    mage_personalities: Mapping[UnitId, tuple[PersonalityRef, ...]]


def index_library(library: BehaviorLibrary, catalog: UnitTypeCatalog) -> BehaviorIndex:
    """Validates a library against the battle's cards and indexes it."""
    traits = _index_traits(library)
    personalities = _index_personalities(library)
    profiles = _index_profiles(library, catalog)

    for profile in library.profiles:
        for tag in profile.traits:
            if tag not in traits:
                raise ValueError(f"profile {profile.type_id!r} names trait {tag!r}, which is not defined")

    behaviors: dict[UnitId, UnitBehavior] = {}
    for behavior in library.unit_behaviors:
        if behavior.unit_id in behaviors:
            raise ValueError(f"unit {behavior.unit_id!r} has two behavior overrides")
        for tag in (*behavior.traits, *behavior.removed_traits):
            if tag not in traits:
                raise ValueError(f"unit {behavior.unit_id!r} names trait {tag!r}, which is not defined")
        contradictory = sorted(set(behavior.traits) & set(behavior.removed_traits))
        if contradictory:
            raise ValueError(
                f"unit {behavior.unit_id!r} both adds and removes {', '.join(contradictory)}; "
                f"a trait cannot be in two minds"
            )
        behaviors[behavior.unit_id] = behavior

    refs: dict[UnitId, tuple[PersonalityRef, ...]] = {}
    for entry in library.mage_personalities:
        if entry.unit_id in refs:
            raise ValueError(f"mage {entry.unit_id!r} has two personality lists")
        seen: set[PersonalityTag] = set()
        for ref in entry.personalities:
            if ref.tag not in personalities:
                raise ValueError(
                    f"mage {entry.unit_id!r} names personality {ref.tag!r}, which is not defined"
                )
            if ref.tag in seen:
                raise ValueError(
                    f"mage {entry.unit_id!r} names personality {ref.tag!r} twice; "
                    f"give it one reference at the strength you want"
                )
            seen.add(ref.tag)
            if ref.strength is not None:
                _validate_strength(ref.strength, f"mage {entry.unit_id!r} personality {ref.tag!r}")
        refs[entry.unit_id] = entry.personalities

    return BehaviorIndex(
        traits=traits,
        personalities=personalities,
        profiles=profiles,
        unit_behaviors=MappingProxyType(behaviors),
        mage_personalities=MappingProxyType(refs),
    )


def _effective_traits(profile: CreatureProfile | None, behavior: UnitBehavior | None) -> tuple[TraitTag, ...]:
    """The traits a unit actually has, sorted so summation order is fixed."""
    tags: set[TraitTag] = set(profile.traits) if profile else set()
    if behavior is not None:
        tags.update(behavior.traits)
        tags.difference_update(behavior.removed_traits)
    # Sorted before it leaves: a set iterates differently in a fresh interpreter.
    return tuple(sorted(tags))


def _resolved_personalities(
    refs: Sequence[tuple[UnitId, PersonalityRef]],
    index: BehaviorIndex,
) -> tuple[tuple[PersonalityTag, float], ...]:
    """Tags and strengths, with the same tag from two mages summed then clamped.

    Two reckless mages in one troop make their summons more reckless, not twice
    as reckless — the ceiling is what makes the composition bounded.
    """
    totals: dict[PersonalityTag, float] = {}

    # Sorted by (mage, tag) so the additions below happen in a fixed order.
    for _, ref in sorted(refs, key=lambda pair: (pair[0], pair[1].tag)):
        definition = index.personalities[ref.tag]
        strength = definition.default_strength if ref.strength is None else float(ref.strength)
        totals[ref.tag] = totals.get(ref.tag, 0.0) + strength

    return tuple((tag, min(MAX_STRENGTH, totals[tag])) for tag in sorted(totals))


def _assert_capabilities(
    unit_id: UnitId,
    capabilities: Capabilities,
    required: tuple[CapabilityName, ...],
    what: str,
) -> None:
    lacking = missing_capabilities(capabilities, required)
    if lacking:
        raise ValueError(
            f"{what} applies to unit {unit_id!r}, which lacks {', '.join(lacking)}. "
            f"Capabilities decide what is possible; traits only decide what is preferred"
        )


def resolve_behavior(
    unit: Unit,
    capabilities: Capabilities,
    index: BehaviorIndex,
    troop_personality_refs: Sequence[tuple[UnitId, PersonalityRef]],
    baseline: FactorWeights = NEUTRAL_WEIGHTS,
) -> ResolvedBehavior:
    """Composes one unit's weights. Pure, and independent of call order.

    `baseline` is what the creature would hold if nobody authored anything —
    normally its ability contour, read off its own stat block (`contour.py`).
    `base_weights` then overrides it factor by factor, which is the relationship
    that makes authoring optional: a card that fights the way its numbers say it
    should needs no profile at all, and a profile is how you say it does not.
    """
    profile = index.profiles.get(unit.type_id)
    behavior = index.unit_behaviors.get(unit.id)

    weights: dict[FactorName, float] = {
        factor: float((profile.base_weights if profile else {}).get(factor, baseline[factor]))
        for factor in FACTORS
    }

    traits = _effective_traits(profile, behavior)
    for tag in traits:
        definition = index.traits[tag]
        _assert_capabilities(unit.id, capabilities, definition.requires, f"trait {tag!r}")
        for factor in FACTORS:
            weights[factor] += float(definition.weights.get(factor, 0.0))

    personalities = _resolved_personalities(troop_personality_refs, index)
    for personality_tag, strength in personalities:
        personality = index.personalities[personality_tag]
        _assert_capabilities(unit.id, capabilities, personality.requires, f"personality {personality_tag!r}")
        for factor in FACTORS:
            # Strength scales the contribution and nothing else. At zero this
            # adds nothing, which is "no opinion" — never the opposite opinion.
            weights[factor] += float(personality.weights.get(factor, 0.0)) * strength

    return ResolvedBehavior(
        weights=freeze_weights({factor: clamp_weight(weights[factor]) for factor in FACTORS}),
        traits=traits,
        personalities=personalities,
        tie_break_jitter=float(profile.tie_break_jitter) if profile else 0.0,
    )


def personality_refs_for_troop(
    troop_id: TroopId,
    mage_ids: Sequence[UnitId],
    index: BehaviorIndex,
) -> tuple[tuple[UnitId, PersonalityRef], ...]:
    """Every personality reference reaching a troop, tagged with its mage.

    A mage's personality shapes the summons it sustains as well as itself — that
    is the point of personalities being authored on mages. Composing *several*
    mages' personalities into a coordinated troop plan is JQ-330; what happens
    here is the bounded sum that ticket builds on.
    """
    del troop_id  # part of the signature so callers read at the troop level
    return tuple(
        (mage_id, ref) for mage_id in sorted(mage_ids) for ref in index.mage_personalities.get(mage_id, ())
    )
