"""The seven behavior scenarios this ticket packages into repeatable runs.

JQ-331 does not author behaviors and does not own their per-behavior tests —
JQ-329 and JQ-330 do, in `tests/sim/ai/`. What this package owns is the *runs*:
staged fixtures, played through the real phase pipeline, asserted on **behavior
invariants rather than on score values**. A scenario that asserted `score ==
0.227` would fail on every tuning pass and tell nobody anything; one that asserts
"the ranged unit never ends a tick inside the melee unit's reach" survives
retuning and still catches the regression.

Four of the seven run today. The other three need JQ-329's positioning, which is
still in review, and are registered here as pending against it rather than
quietly left out — `test_registry.py` holds the list honest, so this package says
what it does not yet cover.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """One named run, and what it is for."""

    name: str
    #: The invariant it pins, in a sentence a reader can check the test against.
    asserts: str
    #: The ticket whose behavior it needs, or None when it runs today.
    blocked_on: str | None = None
    #: The module implementing it, once it is runnable.
    module: str | None = None


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="personality comparison with identical entourage",
        asserts="two troops identical but for their mage's personality diverge, "
        "and the trace names the tag that separated them",
        module="test_personality_comparison",
    ),
    Scenario(
        name="combined traits",
        asserts="stacking traits composes rather than cancelling, and stays inside the weight bounds",
        module="test_combined_traits",
    ),
    Scenario(
        name="invalid and dead targets",
        asserts="a unit never commits to a target that is dead or gone, and recovers the same tick",
        module="test_invalid_targets",
    ),
    Scenario(
        name="ranged spacing",
        asserts="a ranged unit keeps useful firing distance instead of closing to melee",
        blocked_on="JQ-329",
    ),
    Scenario(
        name="screening",
        asserts="a durable unit interposes between a threat and what it threatens",
        blocked_on="JQ-329",
    ),
    Scenario(
        name="repeated bait",
        asserts="bounded pursuit means a unit cannot be walked away from its station "
        "indefinitely by repeated bait",
        blocked_on="JQ-329",
    ),
    Scenario(
        name="regroup",
        asserts="a scattered troop returns to coordinated positions once the "
        "commitment that scattered it is released",
        module="test_regroup",
    ),
)

#: Named by the ticket for the final integration pass. Kept as data so the
#: registry test can say which are still outstanding without anyone updating prose.
RUNNABLE = tuple(scenario for scenario in SCENARIOS if scenario.blocked_on is None)
PENDING = tuple(scenario for scenario in SCENARIOS if scenario.blocked_on is not None)
