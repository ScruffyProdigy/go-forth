"""Behavior as data: creature defaults, individual overrides, mage personalities.

Four vocabularies meet near here and the ticket is explicit that they must stay
apart, so to be unambiguous:

=================  ====================================  ==================
Vocabulary         Lives in                              Example
=================  ====================================  ==================
School (faction)   `schools.py`                          ``fire``
Creature type      `units.py`, a `UnitType.id`           ``cinder-hound``
Behavioral trait   `vocabulary.py`, a `TraitTag`         ``skittish``
Mage personality   `vocabulary.py`, a `PersonalityTag`   ``reckless``
=================  ====================================  ==================

Spell tags are JQ-288's and appear nowhere in this module.

**What a personality is.** Not one set of weight deltas — JQ-330 rules that out
directly, because `reckless` discounting danger and `protective` pricing it
cancel to nothing and a mage that is both comes out identical to a mage that is
neither. A personality is a **default strength, an optional context-free
opinion, and a list of contextual rules**. Each rule names one situation, the
actions it is eligible on, the priorities it moves, the range it looks at, and
the exceptions that silence it. `vocabulary.py` is where those situations are
declared, and where the reasoning behind all this is written out at length.

**Composition.** A unit's weights are built in one fixed order:

1. the creature-type profile's base weights (anything unset is neutral),
2. trait deltas, from the type's traits plus the individual's additions, minus
   the individual's removals,
3. the context-free half of personality deltas, scaled by strength, from the
   mages of its troop,
4. clamp every weight into `[0, MAX_WEIGHT]`.

That is a unit's **standing** weights, and it is all that can be settled at
battle start. Contextual rules cannot be: whether an ally is under threat is a
fact about this tick, so a rule's deltas are applied per candidate, in
`scoring.py`, on top of the standing weights and clamped again there.

Two rules make the whole of it reproducible. **Conflicts resolve by summation,
never by precedence** — a bold trait and a wary trait pulling on `danger` add up
and both show in the result, so no modifier silently wins on the strength of
where it was declared. And every list is **sorted by tag before it is summed**,
because floating-point addition is not associative: the same modifiers applied
in a different order give a different last bit, which is exactly the kind of
drift the determinism tests exist to catch. Rules within one tag are applied in
the order they were authored, which is fixed data rather than anything derived.

**Strength.** A personality reference carries a tag and an optional strength; an
omitted strength resolves to the definition's default. Strength scales a
personality's contribution — context-free and contextual alike — and nothing
else: never legality, never capabilities, never which situations a rule speaks
to. Strength zero contributes nothing; it does not invert the personality,
because a "reckless mage, dialled to zero" is a mage with no opinion, not a
cautious one.

**Provenance.** Every resolved tag keeps the references it came from, each with
its own strength and whether that strength was authored or defaulted. Two mages
in one troop can name the same tag and only one of them override it, so "was
this defaulted?" has no single answer at the tag level and the record does not
pretend otherwise. JQ-331's inspector reads this rather than re-running the
composition with instrumentation.

Numbers here are provisional tuning data. The shapes are the deliverable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

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
from app.sim.ai.vocabulary import (
    ActionKind,
    Context,
    PersonalityTag,
    TraitTag,
    validate_action_names,
    validate_context_names,
)
from app.sim.types import TroopId, UnitId
from app.sim.units import UnitTypeCatalog

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from app.sim.world import Unit

__all__ = [
    "EMPTY_LIBRARY",
    "MAX_JITTER",
    "MAX_STRENGTH",
    "MIN_STRENGTH",
    "NEUTRAL_BEHAVIOR",
    "BehaviorIndex",
    "BehaviorLibrary",
    "CoordinationInfluence",
    "CreatureProfile",
    "MagePersonality",
    "PersonalityDefinition",
    "PersonalityRef",
    "PersonalityRule",
    "PersonalitySource",
    "PersonalityTag",
    "ResolvedBehavior",
    "ResolvedPersonality",
    "TraitDefinition",
    "TraitTag",
    "UnitBehavior",
    "defaulted",
    "describe_behavior",
    "index_library",
    "personality_refs_for_troop",
    "resolve_behavior",
]

#: Strength is a finite, non-negative dial. Zero means "no opinion"; the ceiling
#: keeps a stack of enthusiastic mages from running away with the weights.
MIN_STRENGTH = 0.0
MAX_STRENGTH = 2.0

#: Tie-break jitter's ceiling, as a fraction of a score. Zero by default, which
#: is the only setting under which a battle is reproducible without drawing.
MAX_JITTER = 0.25

#: How far a contextual rule looks, when it does not say. Roughly half a lane on
#: the two-lane map — near enough to be local, which is the whole claim a troop
#: coordination rule is allowed to make.
DEFAULT_INFLUENCE = 60.0
#: And the furthest one may look. Half the map's width: past this a rule is not
#: describing a local situation any more, it is describing the battle, and a
#: global battle strategist is explicitly out of scope.
MAX_INFLUENCE = 190.0

#: Bounds on how far a personality may move its troop's coordination habits.
#: Provisional, like every number here, but bounded on purpose: a habit that
#: could be dialled arbitrarily far would let one authored tag turn the
#: coordinator into the thing the ticket says it must not be.
MAX_GUARD_RADIUS_SHIFT = 120.0
MAX_LEASH_SHIFT = 120.0
MAX_COMMITMENT_SHIFT_SECONDS = 4.0
MAX_DEFENDER_SHIFT = 2.0


@dataclass(frozen=True)
class TraitDefinition:
    """What a behavioral trait does to the weights, and what it needs to work."""

    tag: TraitTag
    #: Added to the weights. May be negative; the sum is clamped, not the term.
    weights: Mapping[FactorName, float] = field(default_factory=dict)
    #: Capabilities a creature must have for this trait to mean anything.
    requires: tuple[CapabilityName, ...] = ()


@dataclass(frozen=True)
class PersonalityRule:
    """One contextual rule: in *this* situation, care about *these* priorities.

    The four dimensions JQ-330 asks a trait to be defined in, one field each:

    ==================  ======================================================
    Dimension           Field
    ==================  ======================================================
    eligible actions    `actions` — empty means every action
    eligible targets    `when`, the situation, which is what a target makes true
    affected priorities `weights`
    influence range     `influence`, in map units
    exceptions          `unless`
    ==================  ======================================================

    Rules compose along those dimensions rather than by precedence: two rules
    that both match both apply, and two that match in different situations never
    meet. That is the whole of why a reckless mage and a protective one can be
    the same mage. There is no last-wins ordering anywhere, and no averaging
    into a single aggression number for the two of them to fight over.

    One situation per rule, deliberately. A rule that spoke to two could not be
    reported honestly — "which context woke this up" would have no answer — and
    splitting it costs an author one line.
    """

    when: Context
    #: Added to the standing weights, for candidates this rule matches. May be
    #: negative. Scaled by strength when the personality is resolved.
    weights: Mapping[FactorName, float] = field(default_factory=dict)
    #: Empty means every action. Otherwise this rule is silent on anything else.
    actions: tuple[ActionKind, ...] = ()
    #: Situations that silence this rule even when `when` holds.
    unless: tuple[Context, ...] = ()
    #: How far this rule looks, in map units, where its situation involves a
    #: distance at all. Local by default: see `DEFAULT_INFLUENCE`.
    influence: float = DEFAULT_INFLUENCE


@dataclass(frozen=True)
class CoordinationInfluence:
    """How a personality shifts its troop's coordination habits.

    Bounded shifts on a baseline rather than absolute settings, because a troop
    may have two mages and "whose number wins" is not a question with a good
    answer. Shifts add, and the result is clamped — the same rule the weights
    follow, for the same reason.

    This is the "explicitly scoped troop coordination" the ticket asks for, and
    the scope is these four numbers. A personality cannot reach the coordinator
    in any other way: it cannot name a unit, choose a target, or add a rule.
    """

    #: Widens or narrows how far from a troop-mate a threat is noticed.
    guard_radius: float = 0.0
    #: Lengthens or shortens how far a defender will travel to answer one.
    leash: float = 0.0
    #: How much longer an assignment is held before it is re-judged. The dial a
    #: methodical mage turns up and an opportunistic one turns down.
    commitment_seconds: float = 0.0
    #: How many more or fewer units may be committed at once.
    defenders: float = 0.0


NO_COORDINATION = CoordinationInfluence()


@dataclass(frozen=True)
class PersonalityDefinition:
    """A mage personality: a plain-language summary, deltas, and rules."""

    tag: PersonalityTag
    #: Used when a reference omits its strength override.
    default_strength: float
    #: One sentence, for the content and UI consumers that will never read a
    #: weights table. Authored rather than generated: a sentence assembled out
    #: of factor names would say "values target suitability", which is true and
    #: tells a reader nothing they could not have guessed from the tag.
    summary: str = ""
    #: The context-free half: what this tag believes everywhere. Most tags say
    #: little here — an opinion that applies in every situation is close to
    #: being a statement about the creature rather than about its leader.
    weights: Mapping[FactorName, float] = field(default_factory=dict)
    #: The contextual half, applied per candidate. Where the work happens.
    rules: tuple[PersonalityRule, ...] = ()
    #: What this tag does to its troop's coordination habits.
    coordination: CoordinationInfluence = NO_COORDINATION
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
class PersonalitySource:
    """One mage's reference to a tag, and where its strength came from."""

    mage_id: UnitId
    #: This reference's own strength, before it is summed with any other.
    strength: float
    #: True when the reference carried an explicit strength, false when the
    #: definition's default was used. Per source, not per tag: two mages can
    #: name one tag and only one of them override it, and a single flag on the
    #: tag would have to lie about one of them.
    overridden: bool


@dataclass(frozen=True)
class ResolvedPersonality:
    """One personality tag as it applies to one unit: strength, rules, origins."""

    tag: PersonalityTag
    #: Summed across sources and clamped to `MAX_STRENGTH`.
    strength: float
    #: Sorted by mage id.
    sources: tuple[PersonalitySource, ...] = ()
    #: The context-free deltas, already scaled by `strength`.
    unconditional: FactorWeights = NEUTRAL_WEIGHTS
    #: The contextual rules, their weights already scaled by `strength`, in the
    #: order they were authored.
    rules: tuple[PersonalityRule, ...] = ()
    #: This tag's shift on its troop's coordination habits, already scaled.
    coordination: CoordinationInfluence = NO_COORDINATION
    summary: str = ""


def defaulted(personality: ResolvedPersonality) -> bool:
    """Whether every reference to this tag took the definition's default."""
    return not any(source.overridden for source in personality.sources)


@dataclass(frozen=True)
class ResolvedBehavior:
    """One unit's standing weights, plus everything that went into them.

    Immutable, and shared by reference across the per-tick world snapshots — see
    `__deepcopy__`.

    **`weights` is not the answer to "what is this unit like".** It is the
    standing set — what the unit believes before it has looked at anything — and
    a personality made entirely of contextual rules does not touch it at all.
    Both shipped example tags are like that, so a hound under a reckless mage,
    under a methodical mage, and under no mage at all have *byte-identical*
    standing weights. Read this field to compare two personalities and the
    honest, useless answer is that they are the same.

    This has already cost someone a debugging session (JQ-331 read it and
    concluded a working personality did nothing), so it is worth being blunt
    about where the answer actually lives:

    ==========================================  ===============================
    Question                                    Read
    ==========================================  ===============================
    what a unit believes before it looks        `weights`, here
    what it believed about one candidate        `FactorContribution.weight` on
                                                that `ScoredCandidate`
    which tag changed that, and why             `ScoredCandidate.influences`
                                                / `Intent.influences`
    which tags a unit carries at all            `personalities`, here
    what a tag would say, in prose              `describe_behavior`
    ==========================================  ===============================

    The rule of thumb: anything contextual needs a candidate to be true *of*,
    so any question whose answer could change between two candidates cannot be
    answered by this field, by construction.
    """

    weights: FactorWeights
    traits: tuple[TraitTag, ...] = ()
    #: Sorted by tag. Non-empty whenever a mage authored anything on this troop,
    #: **even when `weights` above is untouched** — which is the check to make
    #: when a personality looks like it did not land.
    personalities: tuple[ResolvedPersonality, ...] = ()
    tie_break_jitter: float = 0.0

    def __deepcopy__(self, memo: dict[int, object]) -> ResolvedBehavior:
        """Frozen and never mutated, so a snapshot can share it.

        `run_battle` deep-copies the whole world once per tick. Copying an
        immutable weights record 1800 times a battle buys nothing.
        """
        return self


NEUTRAL_BEHAVIOR = ResolvedBehavior(weights=NEUTRAL_WEIGHTS)


def describe_behavior(behavior: ResolvedBehavior) -> tuple[str, ...]:
    """One plain-language line per personality, for content and UI consumers.

    The authored summary, with the strength said out loud only when it is not
    the default — a line that appended "(at strength 1.0)" to every entry would
    train a reader to stop seeing the number, which is the one thing the line is
    for. Sorted by tag, like everything else that leaves this module.
    """
    lines: list[str] = []

    for personality in behavior.personalities:
        summary = personality.summary or f"{personality.tag}."
        if personality.strength <= MIN_STRENGTH:
            lines.append(f"{personality.tag}: dialled to zero, so it says nothing here.")
        elif defaulted(personality):
            lines.append(f"{personality.tag}: {summary}")
        else:
            lines.append(f"{personality.tag}: {summary} Dialled to {personality.strength:g}.")

    return tuple(lines)


def _validate_number(value: float, what: str, quantity: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{what} has {quantity} {value!r}, which is not a number")
    return float(value)


def _validate_strength(value: float, what: str) -> float:
    _validate_number(value, what, "strength")
    if value < MIN_STRENGTH or value > MAX_STRENGTH:
        raise ValueError(
            f"{what} has strength {value}; strength runs {MIN_STRENGTH} to {MAX_STRENGTH}. "
            f"Zero means no preference — it does not invert the personality"
        )
    return float(value)


def _validate_bounded(value: float, limit: float, what: str, quantity: str) -> None:
    _validate_number(value, what, quantity)
    if abs(value) > limit:
        raise ValueError(f"{what} shifts {quantity} by {value}; the bound is +/-{limit}")


def _validate_coordination(coordination: CoordinationInfluence, what: str) -> None:
    _validate_bounded(coordination.guard_radius, MAX_GUARD_RADIUS_SHIFT, what, "guard_radius")
    _validate_bounded(coordination.leash, MAX_LEASH_SHIFT, what, "leash")
    _validate_bounded(
        coordination.commitment_seconds, MAX_COMMITMENT_SHIFT_SECONDS, what, "commitment_seconds"
    )
    _validate_bounded(coordination.defenders, MAX_DEFENDER_SHIFT, what, "defenders")


def _validate_rule(rule: PersonalityRule, what: str) -> None:
    validate_context_names((rule.when,), what)
    validate_context_names(rule.unless, what)
    validate_action_names(rule.actions, what)
    validate_deltas(rule.weights, what)

    if rule.when in rule.unless:
        raise ValueError(
            f"{what} is silenced by the very situation that wakes it, {rule.when!r}; "
            f"a rule that can never fire is a rule that was meant to say something else"
        )

    _validate_number(rule.influence, what, "influence")
    if rule.influence <= 0 or rule.influence > MAX_INFLUENCE:
        raise ValueError(
            f"{what} looks {rule.influence} map units; the range is just above 0 to {MAX_INFLUENCE}. "
            f"Past that a rule is describing the battle rather than a local situation"
        )

    if not rule.weights:
        raise ValueError(f"{what} moves no priorities, so it could not change a decision")


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
        what = f"personality {definition.tag!r}"
        if definition.tag in index:
            raise ValueError(f"mage personality {definition.tag!r} is defined twice")
        validate_deltas(definition.weights, what)
        validate_capability_names(definition.requires, what)
        _validate_strength(definition.default_strength, what)
        _validate_coordination(definition.coordination, what)

        if not definition.weights and not definition.rules and definition.coordination == NO_COORDINATION:
            raise ValueError(
                f"{what} says nothing: no weights, no rules and no coordination habit. "
                f"A tag that changes no behavior would still appear in diagnostics as though it had"
            )

        for position, rule in enumerate(definition.rules):
            _validate_rule(rule, f"{what} rule {position} ({rule.when!r})")

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
        _validate_number(profile.tie_break_jitter, f"profile {profile.type_id!r}", "tie_break_jitter")
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


def _scaled(weights: Mapping[FactorName, float], strength: float) -> FactorWeights:
    """Deltas at this strength. Walks FACTORS, so the order is declared, not hashed."""
    return freeze_weights({factor: float(weights.get(factor, 0.0)) * strength for factor in FACTORS})


def _scaled_rule(rule: PersonalityRule, strength: float) -> PersonalityRule:
    """The same rule with its deltas already at strength — scoring reads no dial.

    Doing the multiplication once, here, is what makes strength zero mean what
    the ticket says it means everywhere at once: the rule survives into the
    diagnostics with deltas of zero, so an inspector can still say the tag was
    present and silent, rather than the tag vanishing and looking un-authored.
    """
    return PersonalityRule(
        when=rule.when,
        weights=_scaled(rule.weights, strength),
        actions=rule.actions,
        unless=rule.unless,
        influence=rule.influence,
    )


def _scaled_coordination(influence: CoordinationInfluence, strength: float) -> CoordinationInfluence:
    """The same habit shifts at this strength. Strength scales everything a tag
    contributes, coordination included — a reckless mage dialled to zero leads
    its troop exactly as a mage with no personality at all would."""
    return CoordinationInfluence(
        guard_radius=influence.guard_radius * strength,
        leash=influence.leash * strength,
        commitment_seconds=influence.commitment_seconds * strength,
        defenders=influence.defenders * strength,
    )


def _resolved_personalities(
    refs: Sequence[tuple[UnitId, PersonalityRef]],
    index: BehaviorIndex,
) -> tuple[ResolvedPersonality, ...]:
    """Tags, strengths and provenance, with the same tag from two mages summed.

    Two reckless mages in one troop make their summons more reckless, not twice
    as reckless — the ceiling is what makes the composition bounded.
    """
    totals: dict[PersonalityTag, float] = {}
    sources: dict[PersonalityTag, list[PersonalitySource]] = {}

    # Sorted by (mage, tag) so the additions below happen in a fixed order.
    for mage_id, ref in sorted(refs, key=lambda pair: (pair[0], pair[1].tag)):
        definition = index.personalities[ref.tag]
        strength = definition.default_strength if ref.strength is None else float(ref.strength)
        totals[ref.tag] = totals.get(ref.tag, 0.0) + strength
        sources.setdefault(ref.tag, []).append(
            PersonalitySource(mage_id=mage_id, strength=strength, overridden=ref.strength is not None)
        )

    resolved: list[ResolvedPersonality] = []
    for tag in sorted(totals):
        definition = index.personalities[tag]
        strength = min(MAX_STRENGTH, totals[tag])
        resolved.append(
            ResolvedPersonality(
                tag=tag,
                strength=strength,
                sources=tuple(sources[tag]),
                unconditional=_scaled(definition.weights, strength),
                rules=tuple(_scaled_rule(rule, strength) for rule in definition.rules),
                coordination=_scaled_coordination(definition.coordination, strength),
                summary=definition.summary,
            )
        )

    return tuple(resolved)


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
    """Composes one unit's standing weights. Pure, and independent of call order.

    `baseline` is what the creature would hold if nobody authored anything —
    normally its ability contour, read off its own stat block (`contour.py`).
    `base_weights` then overrides it factor by factor, which is the relationship
    that makes authoring optional: a card that fights the way its numbers say it
    should needs no profile at all, and a profile is how you say it does not.

    Contextual rules are resolved and carried, not applied. They depend on the
    field, and the field does not exist yet.
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
    for personality in personalities:
        _assert_capabilities(
            unit.id,
            capabilities,
            index.personalities[personality.tag].requires,
            f"personality {personality.tag!r}",
        )
        for factor in FACTORS:
            # Already scaled by strength. At zero this adds nothing, which is
            # "no opinion" — never the opposite opinion.
            weights[factor] += personality.unconditional[factor]

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
    is the point of personalities being authored on mages. What each of those
    summons then *does* about it is its own business, decided against its own
    capabilities, which is how a troop shares a disposition without sharing a
    fighting style.
    """
    del troop_id  # part of the signature so callers read at the troop level
    return tuple(
        (mage_id, ref) for mage_id in sorted(mage_ids) for ref in index.mage_personalities.get(mage_id, ())
    )
