"""Sample behavior data: the interfaces, filled in, for everyone downstream.

Published early on purpose. JQ-307 owns the actual five Fire packages, JQ-329
owns positioning and JQ-330 owns troop coordination, and none of them should have
to wait on tuning to start — what they need is a worked example of the shapes and
something runnable to point at. That is all this is.

**The numbers are provisional and expected to move.** They are chosen to make the
differences legible rather than balanced: `reckless` visibly trades safety for a
kill and `methodical` visibly declines a chase, because a sample that produced
identical behavior would demonstrate nothing. Tuning is JQ-307's.

Trait and personality tags are data, and adding one means adding a definition
here or in a caller's own library — not editing an enum, and never a branch on a
creature id anywhere.
"""

from __future__ import annotations

from app.sim.ai.objective import ObjectiveFixtures
from app.sim.ai.profiles import (
    BehaviorLibrary,
    CreatureProfile,
    MagePersonality,
    PersonalityDefinition,
    PersonalityRef,
    PersonalityTag,
    TraitDefinition,
    TraitTag,
    UnitBehavior,
)
from app.sim.map import THREE_ZONE_MAP
from app.sim.types import Vec2

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

#: Takes the fight. Discounts danger rather than ignoring it.
RECKLESS = PersonalityTag("reckless")
#: Takes the ground. Declines the chase that a reckless mage would take.
METHODICAL = PersonalityTag("methodical")
#: Keeps the troop together and alive.
GUARDIAN = PersonalityTag("guardian")

SAMPLE_PERSONALITIES: tuple[PersonalityDefinition, ...] = (
    PersonalityDefinition(
        RECKLESS, default_strength=1.0, weights={"target_suitability": 1.0, "danger": -0.75}
    ),
    PersonalityDefinition(
        METHODICAL, default_strength=1.0, weights={"objective_progress": 1.0, "danger": 0.5}
    ),
    PersonalityDefinition(GUARDIAN, default_strength=1.0, weights={"ally_support": 1.0, "danger": 0.75}),
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


def sample_library() -> BehaviorLibrary:
    """Definitions and profiles only — no individuals, so it fits any roster."""
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        profiles=SAMPLE_PROFILES,
    )


def placeholder_behavior() -> BehaviorLibrary:
    """`sample_library` wired to the placeholder armies in `sim/fixtures.py`.

    Unit ids follow `create_world`'s scheme, so the three north mages are
    `north-t0-u0`, `north-t1-u0` and `north-t2-u0`. The two sides are given
    different personalities deliberately: a mirror match in which both sides also
    think alike produces a symmetric battle that demonstrates nothing.
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
            MagePersonality("north-t0-u0", (PersonalityRef(RECKLESS),)),
            MagePersonality("north-t1-u0", (PersonalityRef(METHODICAL),)),
            # An explicit strength override, dialled down from the default 1.0.
            MagePersonality("north-t2-u0", (PersonalityRef(GUARDIAN, strength=0.5),)),
            MagePersonality("south-t0-u0", (PersonalityRef(METHODICAL),)),
            MagePersonality("south-t1-u0", (PersonalityRef(GUARDIAN),)),
            MagePersonality("south-t2-u0", (PersonalityRef(RECKLESS, strength=1.5),)),
        ),
    )


# --- stand-in objective facts ----------------------------------------------

#: The middle zone, which is what two armies are actually fighting over. Once
#: JQ-287 lands its orders phase derives these and this goes away.
_CONTESTED = THREE_ZONE_MAP.zones[1]
_CONTESTED_Y = (_CONTESTED.lane.start + _CONTESTED.lane.end) / 2
#: A troop ordered to push. The other two hold the zone — which is the shape of
#: the order mix JQ-287 will produce, and it is what makes the restriction on
#: who may take the base observable in a running battle rather than only in a test.
_PUSHERS = frozenset({"north-t1", "south-t1"})


def placeholder_objectives() -> ObjectiveFixtures:
    """Stations for the placeholder armies, until JQ-287 derives real ones.

    Without these every troop's station is the enemy base, and two armies whose
    orders are both "walk to the far end" march through each other and swap
    ends — which says nothing about whether the decision loop works, because
    nobody was ever asked to hold anything.
    """
    lanes = (90.0, 187.5, 285.0)

    stations = {
        f"{side}-t{index}": Vec2(x, _CONTESTED_Y + (-20 if side == "north" else 20))
        for side in ("north", "south")
        for index, x in enumerate(lanes)
        if f"{side}-t{index}" not in _PUSHERS
    }

    return ObjectiveFixtures(stations=stations, push_troops=_PUSHERS)
