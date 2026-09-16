"""The words a behavior rule may use: action kinds, and named situations.

A leaf module on purpose. `intent.py` and `profiles.py` both need this
vocabulary and neither may import the other — `world.py` imports `intent`, and
`intent` imports `profiles` for the composed behavior it carries — so the words
themselves live below both of them and the code that *reads* a situation off the
field lives in `situation.py`, above both.

**Why contexts exist at all.** JQ-328 gave a personality one flat set of weight
deltas, and that model has a failure it cannot be tuned out of: `reckless`
discounting danger and `protective` pricing it add to zero. A mage that is both
comes out indistinguishable from a mage that is neither, which is the outcome
JQ-330 names outright — the two must "express willingness to take risks
defending allies rather than cancel on one aggression slider".

A single slider cannot express that, and no amount of arithmetic on one will.
Two things have to be true at once — *more* willing to be hurt, and willing
specifically *for an ally* — and those are statements about different moments.
So a personality stops being one dict of deltas and becomes a set of rules, each
naming the situation it speaks to. Reckless discounts danger when committing to
an attack. Protective raises what an ally's attacker is worth when an ally is
under threat. On an interception both fire, on the same candidate, and the
result is a unit that takes a risk it would not otherwise take, for a reason it
would not otherwise have.

**And the design half of the same fix.** Protective is not a synonym for
cautious. Caring about allies and fearing for yourself are separate ideas that a
one-slider model was forced to spell the same way. Here, protective's danger
delta in the `ally-threatened` context is *negative* — it accepts interception
risk — so it never meets reckless head-on on that factor at all. What it limits
is the pursuit that abandons the people it is protecting, and it does that
through `leaves-allies` and `ally_support`, a different context and a different
factor. Two tags that disagree do so somewhere a reader can point at.

Contexts are a closed vocabulary rather than an open one like `TraitTag`. A tag
is data; a context is a question the sim knows how to ask about the field, and
adding one means writing the predicate that answers it.
"""

from __future__ import annotations

from typing import Literal, NewType, get_args

#: A behavioral trait, authored on a creature type or on one individual.
TraitTag = NewType("TraitTag", str)
#: A mage personality, authored on a mage and reaching its whole troop.
#:
#: Distinct `NewType`s over `str` rather than one shared alias, so that handing a
#: personality where a trait belongs is a type error and not a mystery at
#: runtime. Both are open vocabularies — content work adds a tag by adding a
#: definition, never by editing an enum.
PersonalityTag = NewType("PersonalityTag", str)

ActionKind = Literal["advance", "attack", "cast", "withdraw", "retreat", "hold"]

#: Declared order, which is also the order candidates are generated in and the
#: order ties break in. `hold` sits last because it is the fallback, and `cast`
#: sits after `attack` so an exact tie conserves the gauge — a ready ability that
#: is merely *as good as* swinging is worth keeping for a moment that is better.
#: Preferring the ability when it is actually better is scoring's job, not the
#: tie-break's.
#:
#: The two ways of giving ground (JQ-329) sit below both, so that fighting wins an
#: exact tie against backing off. A unit that is genuinely indifferent between
#: swinging and leaving should swing: leaving concedes ground, and conceding
#: ground on a coin-flip is how a line dissolves without anything having decided
#: to break it.
ACTION_KINDS: tuple[ActionKind, ...] = get_args(ActionKind)

Context = Literal[
    # --- what kind of moment this is ---------------------------------------
    #: A swing or a cast. The moment a unit accepts whatever comes back.
    "committing",
    #: An advance whose point is an enemy rather than the station.
    "closing",
    #: Standing still. The candidate a unit that has decided to wait picks.
    "holding",
    # --- what is true about the troop ---------------------------------------
    #: The enemy this candidate is aimed at is within reach of a troop-mate.
    #: The motivation half of interception: it says an ally is in trouble, and
    #: says nothing at all about what this unit should do about it. What a
    #: melee guard and an archer each *can* do about it is their capabilities'
    #: business, which is what keeps one rule working for both.
    "ally-threatened",
    #: This candidate acts on the troop coordinator's standing assignment.
    "assigned",
    #: The position this candidate leaves us in has troop-mates in it.
    "supported",
    #: And the position this candidate leaves us in has none.
    "isolated",
    #: This candidate walks away from the troop, past the distance its
    #: coordination habits tolerate. The exception protective needs.
    "leaves-allies",
    # --- what is true about the target ---------------------------------------
    #: Hurt, or finishable with this unit's swing. A temporary advantage.
    "vulnerable-target",
]

#: Declared once, in a fixed order. Never iterate a set of these — walk this.
CONTEXTS: tuple[Context, ...] = get_args(Context)

#: Which verbs count as taking a swing, and which as going to get one. Declared
#: here rather than matched as literals inside the predicates, so that adding a
#: verb to `ActionKind` is a decision made once, in the open, about what that
#: verb *is* — rather than a silent change of meaning wherever a predicate
#: happened to spell the old list out.
#:
#: **Neither of JQ-329's two verbs joins either tuple, and that was decided with
#: the verbs in hand rather than in advance.** `withdraw` keeps attacking, so it
#: is tempting to call it committing; it is not, because what it commits to is
#: *leaving slowly*, and a personality that discounts danger at the moment of a
#: swing should not thereby discount the danger of backing away. `retreat`
#: suppresses attacking outright. And neither closes. An author who wants a rule
#: scoped to giving ground names it in that rule's `actions` field, which says so
#: out loud instead of inheriting a meaning from a tuple it was never weighed
#: against.
COMMITTING_ACTIONS: tuple[ActionKind, ...] = ("attack", "cast")
CLOSING_ACTIONS: tuple[ActionKind, ...] = ("advance",)
HOLDING_ACTIONS: tuple[ActionKind, ...] = ("hold",)


def validate_context_names(contexts: tuple[str, ...], what: str) -> None:
    for context in contexts:
        if context not in CONTEXTS:
            raise ValueError(
                f"{what} names situation {context!r}, which is not a context; expected one of {CONTEXTS}"
            )


def validate_action_names(actions: tuple[str, ...], what: str) -> None:
    for action in actions:
        if action not in ACTION_KINDS:
            raise ValueError(
                f"{what} names action {action!r}, which is not an action; expected one of {ACTION_KINDS}"
            )
