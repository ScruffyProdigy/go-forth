"""Sample behavior data: the interfaces, filled in, for everyone downstream.

Published early on purpose. JQ-307 owns the actual five Fire packages, JQ-329
owns positioning and JQ-331 owns the inspector and the scenario harness, and
none of them should have to wait on tuning to start — what they need is a worked
example of the shapes and something runnable to point at. That is all this is.

**The numbers are provisional and expected to move.** They are chosen to make
the differences legible rather than balanced: `reckless` visibly trades safety
for a kill and `methodical` visibly declines a chase, because a sample that
produced identical behavior would demonstrate nothing. Tuning is JQ-307's.

**The four example personalities** are the ones JQ-330 names as reusable
examples rather than as a committed roster. Read together they are also the
argument for contextual rules, so it is worth seeing what each one does *not*
say:

* `reckless` discounts danger **when committing**, not everywhere. A reckless
  mage's troop is not careless about where it stands; it is careless about what
  happens after it swings.
* `protective` also discounts danger — in the one context where an ally is being
  hurt. It is not the opposite of reckless and never meets it head-on. What it
  restrains is the chase that abandons the people it is covering, and it does
  that by raising what ally support is worth on a candidate that walks away.
* `opportunistic` is the only one that speaks about the *target* rather than the
  situation, which is why it composes with all three of the others.
* `methodical` is the one with an opinion about time: it turns the coordinator's
  commitment window up, so its troop finishes what it started.

Put `reckless` and `protective` on one mage and you get the combination the
ticket asks for — a troop that accepts real exposure to step in front of its
own — rather than the two of them cancelling to nothing, which is what a single
aggression slider gives you and why there is not one.

Trait and personality tags are data, and adding one means adding a definition
here or in a caller's own library — not editing an enum, and never a branch on a
creature id anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.profiles import (
    BehaviorLibrary,
    CoordinationInfluence,
    CreatureProfile,
    MagePersonality,
    PersonalityDefinition,
    PersonalityRef,
    PersonalityRule,
    TraitDefinition,
    UnitBehavior,
)
from app.sim.ai.vocabulary import PersonalityTag, TraitTag
from app.sim.types import UnitId

# --- behavioral traits: what a creature is like -----------------------------

#: Presses attacks and discounts the risk of taking them.
AGGRESSIVE = TraitTag("aggressive")
#: Weighs incoming damage heavily. The counterweight to `aggressive`.
WARY = TraitTag("wary")
#: Cares about the objective more than about whatever is in front of it.
DUTIFUL = TraitTag("dutiful")
#: Wants company. Worth more to something that dies alone.
PACK_MINDED = TraitTag("pack-minded")
#: Keeps its distance — only means anything to something that can shoot, which
#: is why it declares the capability rather than trusting the author.
SKIRMISHER = TraitTag("skirmisher")

SAMPLE_TRAITS: tuple[TraitDefinition, ...] = (
    TraitDefinition(AGGRESSIVE, {"target_suitability": 1.0, "danger": -0.5}, requires=("attack",)),
    TraitDefinition(WARY, {"danger": 1.0, "target_suitability": -0.25}),
    TraitDefinition(DUTIFUL, {"objective_progress": 1.25, "target_suitability": -0.5}),
    TraitDefinition(PACK_MINDED, {"ally_support": 1.25}),
    TraitDefinition(SKIRMISHER, {"danger": 0.75, "ally_support": 0.5}, requires=("ranged_attack", "move")),
)

# --- mage personalities: what the mage leading the troop is like ------------

#: Takes the fight, and pays for it at the moment of the swing.
RECKLESS = PersonalityTag("reckless")
#: Answers what is hurting its own, and will not chase past them.
PROTECTIVE = PersonalityTag("protective")
#: Takes the opening. Hurt things, finishable things, momentary advantages.
OPPORTUNISTIC = PersonalityTag("opportunistic")
#: Fights where the troop is fighting, and finishes what it started.
METHODICAL = PersonalityTag("methodical")

#: How far `protective` looks for one of its own in trouble. Wider than the
#: default: guarding is the one thing a troop does at troop range rather than at
#: arm's length, and a protective mage that only noticed a threat already on top
#: of an ally would be describing a funeral rather than a rescue.
GUARD_INFLUENCE = 90.0

SAMPLE_PERSONALITIES: tuple[PersonalityDefinition, ...] = (
    PersonalityDefinition(
        RECKLESS,
        default_strength=1.0,
        summary=(
            "Takes the fight. Accepts far more exposure than it should at the moment it commits "
            "to a swing, and will follow something it has decided to kill."
        ),
        rules=(
            # The exposure is accepted *at the swing*, which is the whole of what
            # reckless means here. Where to stand the rest of the time is the
            # creature's own business and its stat block already has views.
            PersonalityRule(
                when="committing",
                weights={"danger": -1.0, "target_suitability": 0.5},
            ),
            PersonalityRule(
                when="closing",
                weights={"danger": -0.6},
            ),
        ),
        coordination=CoordinationInfluence(leash=30.0, commitment_seconds=-0.5),
    ),
    PersonalityDefinition(
        PROTECTIVE,
        default_strength=1.0,
        summary=(
            "Answers whatever is hurting its own and accepts the risk of stepping in front of it. "
            "Will not chase past the people it is covering."
        ),
        rules=(
            # Note the *negative* danger delta. Protective is not cautious — it
            # is willing to be hurt for a specific reason, in a specific moment.
            # Spelling it as caution is what made it cancel with reckless, and
            # cancelling was the bug.
            PersonalityRule(
                when="ally-threatened",
                weights={"target_suitability": 1.0, "danger": -0.5},
                influence=GUARD_INFLUENCE,
            ),
            # The troop asked for this one specifically. Worth something over
            # and above whatever made it a threat, so that an allocation does
            # not have to win the argument twice.
            PersonalityRule(
                when="assigned",
                weights={"target_suitability": 0.75},
            ),
            # And the exception that makes it protective rather than merely
            # aggressive-about-allies: leaving the people you are covering is
            # judged on how little support the place you are going to has.
            PersonalityRule(
                when="leaves-allies",
                weights={"ally_support": 1.5},
                influence=GUARD_INFLUENCE,
            ),
        ),
        coordination=CoordinationInfluence(guard_radius=40.0, defenders=1.0, commitment_seconds=0.5),
    ),
    PersonalityDefinition(
        OPPORTUNISTIC,
        default_strength=1.0,
        summary=(
            "Goes for the opening — the hurt, the finishable, the briefly outnumbered — "
            "and changes its mind the moment a better one appears."
        ),
        rules=(
            PersonalityRule(
                when="vulnerable-target",
                weights={"target_suitability": 1.25, "danger": -0.25},
            ),
            # Taking chances and being caught alone are different things. A
            # negative commitment window below is the other half of the same
            # idea: it will drop what it is doing for a better opening.
            PersonalityRule(
                when="isolated",
                weights={"danger": 0.75},
            ),
        ),
        coordination=CoordinationInfluence(guard_radius=-20.0, commitment_seconds=-1.0),
    ),
    PersonalityDefinition(
        METHODICAL,
        default_strength=1.0,
        summary=(
            "Fights where its troop is fighting, declines the engagement it would have to take "
            "alone, and sticks to a decision once it has made one."
        ),
        rules=(
            PersonalityRule(
                when="supported",
                weights={"objective_progress": 0.5, "target_suitability": 0.5},
            ),
            PersonalityRule(
                when="isolated",
                weights={"ally_support": 1.25, "danger": 0.5},
            ),
            PersonalityRule(
                when="leaves-allies",
                weights={"ally_support": 1.0},
            ),
        ),
        # The commitment dial is this tag's signature, and it is the one place a
        # personality reaches time rather than space.
        coordination=CoordinationInfluence(guard_radius=10.0, commitment_seconds=2.0),
    ),
)

# --- creature profiles: defaults per card -----------------------------------

#: Behavior follows the stat block, not the name: the hound is fast and short
#: ranged so it closes, the sprite has reach so it keeps it, the ram is slow and
#: tough so it walks at the objective and ignores most of what shoots at it.
SAMPLE_PROFILES: tuple[CreatureProfile, ...] = (
    CreatureProfile(
        type_id="ember-adept",
        base_weights={
            "objective_progress": 1.0,
            "target_suitability": 0.75,
            "danger": 1.5,
            "ally_support": 1.0,
        },
        traits=(WARY,),
    ),
    CreatureProfile(
        type_id="cinder-hound",
        base_weights={
            "objective_progress": 0.75,
            "target_suitability": 1.5,
            "danger": 0.75,
            "ally_support": 1.0,
        },
        traits=(AGGRESSIVE, PACK_MINDED),
    ),
    CreatureProfile(
        type_id="ember-sprite",
        base_weights={
            "objective_progress": 1.0,
            "target_suitability": 1.0,
            "danger": 1.25,
            "ally_support": 0.75,
        },
        traits=(SKIRMISHER,),
    ),
    CreatureProfile(
        type_id="ash-ram",
        base_weights={
            "objective_progress": 1.5,
            "target_suitability": 1.0,
            "danger": 0.5,
            "ally_support": 0.5,
        },
        traits=(DUTIFUL,),
    ),
)


def definitions() -> BehaviorLibrary:
    """Every trait and personality definition, and nothing applied to anything.

    The base every library below is built on, and the one to reach for in a test
    that wants a personality's effect isolated: no creature profiles means no
    authored weights, so whatever changes is the personality's doing rather than
    a profile's.
    """
    return BehaviorLibrary(traits=SAMPLE_TRAITS, personalities=SAMPLE_PERSONALITIES)


def sample_library() -> BehaviorLibrary:
    """Definitions and profiles — fits any roster carrying the four Fire cards."""
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        profiles=SAMPLE_PROFILES,
    )


# --- the opening roster's five packages, as behavior data -------------------
#
# JQ-307 owns the packages themselves: which mage, which entourage, which
# numbers. What belongs here is the half this ticket owns — the disposition each
# package leads with, and the coordination habit that falls out of it.
#
# Every habit below is *emergent*. None of them is implemented: each is what the
# composed rules and the coordinator already do once a mage is authored this
# way, written down so a reader can check the claim. There is no branch on a
# package id anywhere in the sim, and adding a sixth package is adding an entry
# to this tuple.


@dataclass(frozen=True)
class MagePackage:
    """One opening package's disposition, and what it is meant to set up."""

    id: str
    #: What the package's mage is authored as. One defining personality, and a
    #: second only where the pair is recognisable as a thing in its own right —
    #: JQ-330's first-roster convention, not a limit the schema imposes.
    personalities: tuple[PersonalityRef, ...]
    #: The automatic ability this package's habit exists to set up. A reference
    #: for content work and for JQ-307; nothing in the sim reads it.
    supports_ability: str
    #: The coordination habit, in one sentence, for the same audience as
    #: `PersonalityDefinition.summary`.
    habit: str


FIVE_PACKAGES: tuple[MagePackage, ...] = (
    MagePackage(
        id="vanguard",
        personalities=(PersonalityRef(RECKLESS),),
        supports_ability="pounce",
        habit=(
            "Presses into contact and stays there, which is what keeps something in front of the "
            "hounds for a pounce to close on."
        ),
    ),
    MagePackage(
        id="bulwark",
        personalities=(PersonalityRef(PROTECTIVE),),
        supports_ability="cinder-nova",
        habit=(
            "Commits a defender to whatever reaches its mage, and only one — which is what keeps "
            "the adept alive and surrounded long enough for a nova to be worth spending."
        ),
    ),
    MagePackage(
        id="scavenger",
        personalities=(PersonalityRef(OPPORTUNISTIC),),
        supports_ability="ram-charge",
        habit=(
            "Re-judges its assignments almost every tick, so the troop swings onto whatever has "
            "just become finishable rather than onto whatever it picked first."
        ),
    ),
    MagePackage(
        id="anvil",
        personalities=(PersonalityRef(METHODICAL),),
        supports_ability="molten-seep",
        habit=(
            "Fights where its troop already is and holds an assignment for seconds rather than "
            "ticks, which is the only way burning ground pays: it has to be ground somebody stays on."
        ),
    ),
    MagePackage(
        id="firebrand",
        # The combination, and the one package that needs two tags to describe.
        # Neither of them is dialled: both are doing their whole job, in
        # different moments, which is the thing JQ-330 asks a combination to
        # demonstrate.
        personalities=(PersonalityRef(RECKLESS), PersonalityRef(PROTECTIVE)),
        supports_ability="ram-charge",
        habit=(
            "Throws itself in front of what is hurting its own and accepts the damage for it — "
            "a charge used as an interception rather than as a push."
        ),
    ),
)


def package_by_id(package_id: str) -> MagePackage:
    for package in FIVE_PACKAGES:
        if package.id == package_id:
            return package
    raise ValueError(f"{package_id!r} is not one of the opening packages")


def package_library(package_id: str, *mage_ids: UnitId) -> BehaviorLibrary:
    """The definitions, with one package's personalities on the named mages.

    No creature profiles, so it composes with any roster: what a package changes
    is the troop's disposition, and the cards keep their own instincts. That
    split is the ticket's — "summons retain their individual capabilities and
    instincts" — and it is the reason this is a library of personalities rather
    than a library of rewritten creature profiles.
    """
    package = package_by_id(package_id)
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        mage_personalities=tuple(
            MagePersonality(mage_id, package.personalities) for mage_id in sorted(mage_ids)
        ),
    )


# --- the three demonstration libraries --------------------------------------
#
# All three build on the same definitions and none of them carries a creature
# profile, so one fixture entourage can be run through all three and every
# difference in what it does is the mage's doing. That is the comparison JQ-330
# asks for and the one JQ-331's scenarios run.


def contrasting_library(reckless_mage: UnitId, methodical_mage: UnitId) -> BehaviorLibrary:
    """Two mages that could not lead the same troop the same way.

    Reckless and methodical rather than reckless and protective, because these
    two genuinely disagree about the same candidates — one discounts danger at
    the swing, the other declines the engagement it would have to take alone —
    whereas reckless and protective mostly speak about different moments. The
    contrast is the point here; the composition is `combined_library`'s.
    """
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        mage_personalities=tuple(
            sorted(
                (
                    MagePersonality(reckless_mage, (PersonalityRef(RECKLESS),)),
                    MagePersonality(methodical_mage, (PersonalityRef(METHODICAL),)),
                ),
                key=lambda entry: entry.unit_id,
            )
        ),
    )


def combined_library(mage_id: UnitId) -> BehaviorLibrary:
    """One mage that is both reckless and protective — the `firebrand` pairing.

    The fixture behind the ticket's own example: this mage's troop accepts
    personal exposure to intercept threats to its allies. Both tags at their
    default strength, so nothing about the result is a tuning artefact.
    """
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        mage_personalities=(
            MagePersonality(mage_id, (PersonalityRef(RECKLESS), PersonalityRef(PROTECTIVE))),
        ),
    )


def strength_library(
    mage_id: UnitId,
    tag: PersonalityTag = PROTECTIVE,
    strength: float | None = None,
) -> BehaviorLibrary:
    """One tag on one mage, at whatever strength the caller wants to ask about.

    `strength=None` is the case worth naming: it means the reference carries no
    override, so the definition's default is used — and a library built this way
    must compose identically to one built with that default spelled out.
    """
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        mage_personalities=(MagePersonality(mage_id, (PersonalityRef(tag, strength),)),),
    )


def placeholder_behavior() -> BehaviorLibrary:
    """`sample_library` wired to the placeholder armies in `sim/fixtures.py`.

    Unit ids follow `create_world`'s scheme, so the three north mages are
    `north-t0-u0`, `north-t1-u0` and `north-t2-u0`. The two sides are given
    different personalities deliberately: a mirror match in which both sides also
    think alike produces a symmetric battle that demonstrates nothing.

    North leads with the combination, which is the arrangement that puts the
    headline claim in the demo's own event stream rather than only in a test.
    """
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        profiles=SAMPLE_PROFILES,
        unit_behaviors=(
            # One hound that never got over something. Same card, same stats,
            # different behavior — no new creature type required.
            UnitBehavior(unit_id="north-t0-u1", traits=(WARY,), removed_traits=(AGGRESSIVE,)),
        ),
        mage_personalities=(
            MagePersonality("north-t0-u0", (PersonalityRef(RECKLESS), PersonalityRef(PROTECTIVE))),
            MagePersonality("north-t1-u0", (PersonalityRef(METHODICAL),)),
            # An explicit strength override, dialled down from the default 1.0.
            MagePersonality("north-t2-u0", (PersonalityRef(PROTECTIVE, strength=0.5),)),
            MagePersonality("south-t0-u0", (PersonalityRef(METHODICAL),)),
            MagePersonality("south-t1-u0", (PersonalityRef(OPPORTUNISTIC),)),
            MagePersonality("south-t2-u0", (PersonalityRef(RECKLESS, strength=1.5),)),
        ),
    )
