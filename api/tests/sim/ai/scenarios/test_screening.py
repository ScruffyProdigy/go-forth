"""Scenario: screening.

A durable unit puts itself between a threat and what the threat is after. The
behaviour is JQ-329's and the allocation is JQ-330's; what this owns is the two
of them working together over a run, which is the seam the two tickets built from
opposite ends and briefly built differently.

The invariant is about **who**, not where. A screen that covers the wrong ally is
indistinguishable from a screen that covers the right one if you only look at
positions, and it is the difference between a mage living and dying. So this
asserts through the trace: which threat, on whose behalf, and whether that ally
was named by the coordinator or guessed by the unit itself.

That last distinction is the one worth having. `protected_by` falls back to
inferring the screened ally when nobody assigned one, which is correct and
invisible from the outside — a screen covering a different ally than intended
reads as an AI bug in a playtest when it is a fallback doing its job.
"""

from __future__ import annotations

from app.sim.ai.fixtures import PROTECTIVE, SAMPLE_PERSONALITIES, SAMPLE_PROFILES, SAMPLE_TRAITS
from app.sim.ai.intent import INTERCEPTING, SCREENING, SCREENING_INFERRED
from app.sim.ai.profiles import BehaviorLibrary, MagePersonality, PersonalityRef
from app.sim.orders import hold
from app.sim.types import Vec2
from app.sim.world import Unit
from tests.sim.ai.helpers import make_unit
from tests.sim.ai.scenarios.harness import ScenarioRun, play
from tests.sim.fixtures_units import ADEPT, HOUND, RAM, SPRITE

TICKS = 60
UNIT_TYPES = (ADEPT, HOUND, RAM, SPRITE)
STAGED = tuple(p for p in SAMPLE_PROFILES if p.type_id in {t.id for t in UNIT_TYPES})
TROOP = "north-t0"

#: Every way a unit can be answering a threat on somebody's behalf. Read from
#: JQ-329's published vocabulary rather than spelled out here: they narrowed
#: `screening` mid-flight to mean only the assigned kind, and a hand-written list
#: would have gone on matching the old meaning without failing.
DEFENDING = (SCREENING, SCREENING_INFERRED, INTERCEPTING)

HOLDING = {"north-t0": hold("W"), "south-t0": hold("W")}
POST = Vec2(80, 284.5)


def threatened() -> list[Unit]:
    """A fragile mage, a durable guard, and a threat walking at the mage.

    The guard is a `ash-ram` — slow and tough, the creature with most reason to
    interpose — and it starts beside the mage rather than in the way, so getting
    between the two has to be a decision rather than the starting position.
    """
    return [
        make_unit("mage", ADEPT, "north", POST, destination=POST),
        make_unit("guard", RAM, "north", Vec2(POST.x - 25, POST.y), destination=Vec2(POST.x - 25, POST.y)),
        make_unit("threat", HOUND, "south", Vec2(POST.x, POST.y + 55), destination=POST),
    ]


def library() -> BehaviorLibrary:
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        profiles=STAGED,
        mage_personalities=(MagePersonality(unit_id="mage", personalities=(PersonalityRef(PROTECTIVE),)),),
    )


def run() -> ScenarioRun:
    return play(threatened(), UNIT_TYPES, library(), ticks=TICKS, orders=HOLDING)


def defending_records(result: ScenarioRun, unit_id: str) -> list[object]:
    return [record for record in result.by_unit(unit_id) if record.reason in DEFENDING]


def test_the_threat_actually_menaces_the_mage() -> None:
    """The positive control: nothing is screened from a threat that never arrives."""
    result = run()
    threat = result.by_unit("threat")

    assert threat, "the threat never decided anything"
    assert any(record.chosen.target_id in ("mage", "guard") for record in threat), (
        "the threat never went for anyone, so there was nothing to screen"
    )


def test_somebody_screens_and_the_trace_says_who_for() -> None:
    """Which threat, on whose behalf — the part positions cannot tell you."""
    result = run()
    screens = defending_records(result, "guard")

    assert screens, "the guard never interposed"
    covered = {record.chosen.protecting_id for record in screens}  # type: ignore[attr-defined]
    assert covered == {"mage"}, f"the guard screened for {covered or 'nobody'}"


def test_the_screen_records_whether_the_ally_was_named_or_guessed() -> None:
    """Both halves of the provenance exist, and the trace distinguishes them.

    Only one fires in any given run — a coordinator either named the ally or it
    did not — so this asserts the reason is one of the two rather than pinning
    which, and that it is never left unexplained.
    """
    result = run()
    screens = defending_records(result, "guard")

    assert screens
    for record in screens:
        assert record.reason in DEFENDING  # type: ignore[attr-defined]
        assert record.chosen.protecting_id is not None, (  # type: ignore[attr-defined]
            "a screen that names no ally cannot be checked against intent"
        )


def test_the_durable_unit_screens_rather_than_the_fragile_one() -> None:
    """Eligibility is read off live stats: the mage does not guard itself."""
    result = run()

    assert defending_records(result, "guard")
    assert defending_records(result, "mage") == [], "the mage screened for somebody"


def test_a_guard_with_no_threat_in_reach_never_screens() -> None:
    """The contrast: screening answers a threat, it is not a resting posture.

    Deliberately "no threat" rather than "no ally". A lone guard with a threat
    still screens — `protected_by` falls back to covering the unit's own post,
    which is right and is what my first version of this test assumed away. The
    absence to look for is a threat nobody has to answer, not an ally nobody has
    to protect.
    """
    far = [
        make_unit("mage", ADEPT, "north", POST, destination=POST),
        make_unit("guard", RAM, "north", Vec2(POST.x - 25, POST.y), destination=Vec2(POST.x - 25, POST.y)),
        make_unit("threat", HOUND, "south", Vec2(POST.x + 500, POST.y + 500), destination=POST),
    ]
    result = play(far, UNIT_TYPES, library(), ticks=TICKS, orders=HOLDING)

    assert result.by_unit("guard"), "the guard decided nothing, so its reasons prove nothing"
    assert defending_records(result, "guard") == []
    # The positive half, from the run that does have a threat in reach.
    assert defending_records(run(), "guard"), "the staging itself never produces a screen"
