"""The four things any action is judged on, and the weights that scale them.

Four factors, fixed. A new creature or a new personality changes *weights*; it
does not get its own factor, because a factor only means something if every
candidate action can be scored on it and the results compare. "Objective
progress" is comparable between advancing and attacking; "likes fire" is not.

Every factor produces a raw score in `[-1, 1]` and every weight is a
non-negative number in `[0, MAX_WEIGHT]`. The total is the weighted mean, so it
is also in `[-1, 1]` — bounded regardless of how many modifiers piled onto the
weights, which is what keeps one enthusiastic personality from swamping the
rest.

`danger` is scored the same way as the others and carries its own sign: a
candidate that walks into three enemies scores negative on it. Weights stay
non-negative so that "cares about danger" and "ignores danger" are a big weight
and a small one, never a sign flip — a negative weight would mean a unit that
actively seeks harm, which is not a thing any trait should be able to express by
accident.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, get_args

from app.sim.ai.vocabulary import Context, PersonalityTag

FactorName = Literal[
    "objective_progress",
    "target_suitability",
    "danger",
    "ally_support",
]

#: Declared once, in a fixed order. Never iterate a weights mapping directly —
#: walk this instead. See `rng.py` on why hash order must not reach output.
FACTORS: tuple[FactorName, ...] = get_args(FactorName)

FactorWeights = Mapping[FactorName, float]

#: A weight's ceiling. Composition clamps here rather than rejecting, so stacking
#: three eager personalities saturates instead of erroring out mid-battle.
MAX_WEIGHT = 4.0

#: What a creature with no profile at all uses: every factor matters equally.
NEUTRAL_WEIGHTS: FactorWeights = MappingProxyType({factor: 1.0 for factor in FACTORS})


def validate_weights(weights: Mapping[Any, float], what: str) -> None:
    """Raises unless every entry names a real factor and sits in range.

    Keyed `Any` deliberately: checking that the keys *are* factors is the job, so
    a caller handing over an author's raw dict must not have to prove it first.
    """
    for factor, value in weights.items():
        if factor not in FACTORS:
            raise ValueError(f"{what} weights {factor!r}, which is not a factor; expected one of {FACTORS}")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{what} weight for {factor} is {value!r}, which is not a number")
        if value < 0:
            raise ValueError(
                f"{what} weight for {factor} is {value}; weights are non-negative — "
                f"to express indifference use 0, not a negative weight"
            )
        if value > MAX_WEIGHT:
            raise ValueError(f"{what} weight for {factor} is {value}; the ceiling is {MAX_WEIGHT}")


def validate_deltas(deltas: Mapping[Any, float], what: str) -> None:
    """Raises unless every entry names a real factor. Deltas may be negative."""
    for factor, value in deltas.items():
        if factor not in FACTORS:
            raise ValueError(f"{what} modifies {factor!r}, which is not a factor; expected one of {FACTORS}")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{what} modifier for {factor} is {value!r}, which is not a number")
        if abs(value) > MAX_WEIGHT:
            raise ValueError(
                f"{what} modifier for {factor} is {value}; modifiers are bounded by +/-{MAX_WEIGHT}"
            )


def clamp_weight(value: float) -> float:
    return min(MAX_WEIGHT, max(0.0, value))


def clamp_score(value: float) -> float:
    """Every factor's raw score lives in `[-1, 1]`."""
    return min(1.0, max(-1.0, value))


def freeze_weights(weights: Mapping[FactorName, float]) -> FactorWeights:
    """A read-only weights mapping built in declared factor order."""
    return MappingProxyType({factor: float(weights.get(factor, 0.0)) for factor in FACTORS})


@dataclass(frozen=True)
class FactorContribution:
    """One factor's say in one candidate's score.

    Kept alongside the score rather than folded into it so a decision can be
    explained after the fact — JQ-331's inspector reads exactly this.
    """

    factor: FactorName
    #: The factor's own verdict, in `[-1, 1]`.
    raw: float
    #: How much this unit cares, in `[0, MAX_WEIGHT]`.
    weight: float

    @property
    def contribution(self) -> float:
        return self.raw * self.weight


@dataclass(frozen=True)
class PersonalityInfluence:
    """One personality tag's say in one candidate's *weights*, and why.

    The other half of explaining a decision. `FactorContribution` says what the
    unit weighed; this says which authored tag put that weight there and which
    situation woke it up — "reckless, at strength 1.5, took 1.13 off how much
    danger counted, because this candidate was a commitment".

    Recorded per candidate rather than per unit because that is the whole point
    of a contextual rule: the same tag is loud on one candidate and silent on
    the next, and a record that collapsed them could not show it. An empty tuple
    on a candidate means no tag had anything to say about it.
    """

    tag: PersonalityTag
    #: The situation that activated the rule. One per rule, so the record is
    #: unambiguous — a rule that speaks to two situations is two rules.
    context: Context
    factor: FactorName
    #: The weight delta, after strength scaling and before the final clamp.
    delta: float
