"""Scenario: invalid and dead targets.

The failure this guards against is a unit that commits to something which has
stopped existing — swinging at a corpse, walking at a unit that was removed three
ticks ago, or holding an intent whose target id no longer resolves. It is the
cheapest kind of bug to write and the most expensive to watch in a playtest,
because it looks like the AI "froze" rather than like a stale reference.

The invariant is stated over the whole run rather than at one tick: **at no point
does any unit choose an action aimed at something that is not a living enemy**,
and a unit whose target dies has decided something else by the very next tick it
decides at all.
"""

from __future__ import annotations

from app.sim.ai.fixtures import SAMPLE_PROFILES, SAMPLE_TRAITS
from app.sim.ai.profiles import BehaviorLibrary
from app.sim.types import Vec2
from app.sim.world import Unit
from tests.sim.ai.helpers import make_unit
from tests.sim.ai.scenarios.harness import ScenarioRun, play
from tests.sim.fixtures_units import ADEPT, HOUND, WISP

TICKS = 40
UNIT_TYPES = (ADEPT, HOUND, WISP)
STAGED = tuple(p for p in SAMPLE_PROFILES if p.type_id in {t.id for t in UNIT_TYPES})
LIBRARY = BehaviorLibrary(traits=SAMPLE_TRAITS, profiles=STAGED)


def run(units: list[Unit]) -> ScenarioRun:
    return play(units, UNIT_TYPES, LIBRARY, ticks=TICKS)


def doomed() -> list[Unit]:
    """A hound standing on a one-hp wisp: the target dies almost immediately."""
    return [
        make_unit("hunter", HOUND, "north", Vec2(100, 100), destination=Vec2(100, 100)),
        make_unit("doomed", WISP, "south", Vec2(105, 100)),
        make_unit("survivor", ADEPT, "south", Vec2(160, 100)),
    ]


def test_the_scenario_actually_kills_the_target() -> None:
    """Guards everything below: if nothing dies, no test here means anything."""
    result = run(doomed())

    assert not result.alive("doomed")


def test_no_decision_ever_names_a_unit_that_is_not_in_the_world() -> None:
    """A "nothing bad happened" assertion, so it has to prove it looked.

    Two counters rather than a bare loop. An empty trace satisfies "no record
    names a missing unit" perfectly, and so does a trace in which no candidate
    ever names anyone — both are the regression this exists to catch, and
    neither is distinguishable from success without counting.
    """
    result = run(doomed())
    known = {unit.id for unit in result.world.units} | {"doomed"}
    checked = 0

    for record in result.records:
        for candidate in (record.chosen, *record.rivals):
            if candidate.target_id is not None:
                checked += 1
                assert candidate.target_id in known, f"tick {record.tick}: {candidate.target_id}"

    assert result.records, "nothing was traced, so nothing was checked"
    assert checked > 0, "no candidate named a target, so the check never ran"


def test_no_unit_attacks_a_target_that_had_already_died() -> None:
    """The precise failure: an attack committed after the target was removed.

    The sweep is bracketed at both ends, because on its own it degrades to
    nothing without changing. The wisp dies on tick 1, and for most of the ticks
    after it the hunter is walking to its station and naming no target at all —
    so "no record names the dead unit" is satisfied by 37 records that name
    nobody. Measured, not guessed: 40 hunter records, 1 before the death, 2 of
    the remaining 39 naming any target whatsoever.

    So: it must have named the wisp while the wisp was alive, and it must still
    be naming *somebody* afterwards. Without the first the absence proves
    nothing; without the second the sweep has silently stopped looking.
    """
    result = run(doomed())
    removals = (
        event.tick
        for event in result.events
        if any(target.unit_id == "doomed" for target in event.swing.units_removed)
    )
    died_at = min(removals, default=None)

    assert died_at is not None, "the wisp never died, so this proves nothing"

    hunter = result.by_unit("hunter")
    assert any(r.chosen.target_id == "doomed" for r in hunter if r.tick <= died_at), (
        "the hunter never targeted the wisp while it lived, so losing it proves nothing"
    )
    assert any(r.chosen.target_id is not None for r in hunter if r.tick > died_at), (
        "the hunter named no target at all after the death; the sweep is not looking at anything"
    )

    for record in result.records:
        if record.tick > died_at and record.chosen.target_id == "doomed":
            raise AssertionError(f"{record.unit_id} aimed at a dead unit on tick {record.tick}")


def test_the_hunter_finds_something_else_to_do_after_its_target_dies() -> None:
    """Recovery, not just absence of error: it must not stall on the empty square.

    An earlier version closed with `chosen.kind in ("advance", "attack", "cast",
    "hold")`, which lists every action kind there is and so was true by
    construction. What recovery actually means here is that it goes on to name
    the *other* enemy, which is a claim that can fail.
    """
    result = run(doomed())
    hunter = result.by_unit("hunter")
    after = [r for r in hunter if r.chosen.target_id != "doomed"]

    assert after, "the hunter never decided anything after its target died"
    assert any(r.chosen.target_id == "survivor" for r in after), (
        "the hunter never moved on to the surviving enemy"
    )


def test_a_unit_with_no_enemies_left_still_decides_something() -> None:
    """An empty enemy list must produce `hold`, not an empty candidate set."""
    lonely = [make_unit("alone", HOUND, "north", Vec2(100, 100), destination=Vec2(100, 100))]
    result = play(lonely, UNIT_TYPES, LIBRARY, ticks=5)

    assert result.actions("alone") != ()
    assert all(record.candidate_count >= 1 for record in result.by_unit("alone"))
    assert all(record.chosen.target_id is None for record in result.by_unit("alone"))


def test_an_unreachable_enemy_is_never_offered_as_an_attack_candidate() -> None:
    """Legality is filtered *before* scoring, so it must not reach the scorer at all.

    Asserted over every candidate rather than over the chosen action. Checking
    only what was chosen passes even when the filter is removed entirely —
    scoring declines the hopeless attack on its own merits — which would leave
    this scenario reporting a healthy filter that was not there. The whole point
    of filtering before scoring is that no preference can talk a unit into an
    illegal action, and that is only observable in the candidate set.
    """
    far = [
        make_unit("hunter", HOUND, "north", Vec2(0, 0), destination=Vec2(0, 0)),
        make_unit("distant", ADEPT, "south", Vec2(600, 600)),
    ]
    result = play(far, UNIT_TYPES, LIBRARY, ticks=3)
    records = result.by_unit("hunter")

    # The positive control, in the same arrangement: move the enemy into reach
    # and an attack candidate appears. Without it, "no attack candidate" is also
    # satisfied by attack candidates having stopped being generated at all,
    # which is a larger break than the one being hunted and would read as a pass.
    near = [
        make_unit("hunter", HOUND, "north", Vec2(0, 0), destination=Vec2(0, 0)),
        make_unit("close", ADEPT, "south", Vec2(5, 0)),
    ]
    reachable = play(near, UNIT_TYPES, LIBRARY, ticks=3).by_unit("hunter")
    assert any(
        candidate.kind == "attack" for record in reachable for candidate in (record.chosen, *record.rivals)
    ), "no attack candidate even for an enemy in reach; the filter is not what this measures"

    assert records, "the hunter never decided anything"
    for record in records:
        # The kind check below only sees the candidates the record kept, so it
        # is a proof about all of them only if the record kept all of them.
        # Asserted as a relationship rather than as a count: how many positional
        # candidates a unit generates is JQ-329's business and grows as
        # positioning gets richer, but "the rivals are every loser" stays true.
        assert len(record.rivals) == record.candidate_count - 1, (
            f"tick {record.tick}: {record.candidate_count - len(record.rivals) - 1} candidates unchecked"
        )
        for candidate in (record.chosen, *record.rivals):
            assert candidate.kind != "attack", f"tick {record.tick}: attack on an unreachable enemy"


def test_every_traced_decision_has_a_candidate_behind_it() -> None:
    """A decision with zero candidates would mean the fallback stopped existing."""
    result = run(doomed())

    assert result.records != ()
    assert all(record.candidate_count >= 1 for record in result.records)
