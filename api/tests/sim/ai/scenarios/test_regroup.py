"""Scenario: regroup.

The invariant the ticket names is that a scattered troop "returns to coordinated
positions once the commitment that scattered it is released". Two halves, and
the second is the one worth testing: anything can scatter a troop, and what
distinguishes a defence from a rout is that it ends.

So this is a before-and-after over one run rather than an assertion at a tick.
A threat appears, the coordinator commits defenders to it, the threat dies, and
the troop has to come back — assignments released, units returning to the
stations JQ-287's orders phase keeps rewriting underneath them.

Asserted through the trace, because that is what a playtester reads when a troop
fails to come home: the inspector should be able to say which units were
committed, on whose behalf, and when the commitment ended.
"""

from __future__ import annotations

from app.sim.ai.fixtures import PROTECTIVE, SAMPLE_PERSONALITIES, SAMPLE_PROFILES, SAMPLE_TRAITS
from app.sim.ai.profiles import BehaviorLibrary, MagePersonality, PersonalityRef
from app.sim.geometry import distance
from app.sim.types import Vec2
from app.sim.world import Unit
from tests.sim.ai.helpers import make_unit
from tests.sim.ai.scenarios.harness import ScenarioRun, assignments_of, play
from tests.sim.fixtures_units import ADEPT, HOUND, WISP

#: Long enough for the threat to die and the troop to walk back from it.
TICKS = 90
UNIT_TYPES = (ADEPT, HOUND, WISP)
STAGED = tuple(p for p in SAMPLE_PROFILES if p.type_id in {t.id for t in UNIT_TYPES})
TROOP = "north-t0"


def scattered() -> list[Unit]:
    """A protective troop, and one threat on the mage that will not survive.

    The threat is a `cinder-hound` on one hit point. It has to **have damage**
    to be a threat at all — `coordination._under_threat` declines a harmless
    enemy, which is right and is why the obvious `dying-wisp` produced no
    commitment and the positive control below caught it — and it has to die
    quickly, so the release this scenario is about is guaranteed rather than
    merely likely.
    """
    return [
        make_unit("mage", ADEPT, "north", Vec2(100, 100), destination=Vec2(100, 100)),
        make_unit("guard-a", HOUND, "north", Vec2(90, 105), destination=Vec2(90, 105)),
        make_unit("guard-b", HOUND, "north", Vec2(110, 105), destination=Vec2(110, 105)),
        make_unit("threat", HOUND, "south", Vec2(112, 100), hp=1),
    ]


def library() -> BehaviorLibrary:
    return BehaviorLibrary(
        traits=SAMPLE_TRAITS,
        personalities=SAMPLE_PERSONALITIES,
        profiles=STAGED,
        mage_personalities=(MagePersonality(unit_id="mage", personalities=(PersonalityRef(PROTECTIVE),)),),
    )


def run() -> ScenarioRun:
    return play(scattered(), UNIT_TYPES, library(), ticks=TICKS)


def death_tick(result: ScenarioRun) -> int | None:
    removals = (
        event.tick
        for event in result.events
        if any(target.unit_id == "threat" for target in event.swing.units_removed)
    )
    return min(removals, default=None)


def test_the_threat_actually_dies() -> None:
    """Guards every assertion below: with the threat alive nothing is released."""
    result = run()

    assert not result.alive("threat")
    assert death_tick(result) is not None


def test_the_troop_commits_somebody_before_the_threat_dies() -> None:
    """The positive control. A troop that never scatters cannot be seen to regroup.

    Without this every assertion about release is satisfied by a coordinator
    that allocated nothing in the first place, which is the larger failure and
    would read as a pass.
    """
    result = run()
    committed = [
        record
        for record in result.records
        if record.assignment is not None and record.tick <= (death_tick(result) or 0)
    ]

    assert committed, "no unit was ever assigned, so there was nothing to regroup from"
    assert {record.assignment.protecting_id for record in committed if record.assignment} == {"mage"}


def test_every_assignment_is_released_once_the_threat_is_gone() -> None:
    """The regroup itself, in the authoritative state rather than in behaviour."""
    result = run()
    died = death_tick(result)

    assert died is not None
    assert assignments_of(result, TROOP) == (), "the troop is still committed to a dead threat"


def test_no_decision_after_the_death_still_carries_an_assignment() -> None:
    """And the trace agrees with the world, which is the inspector's whole job."""
    result = run()
    died = death_tick(result)

    assert died is not None
    stale = [record for record in result.records if record.tick > died + 1 and record.assignment is not None]

    assert stale == [], f"{len(stale)} decisions still cited an assignment after the threat died"


def test_the_guards_end_the_run_nearer_their_stations_than_the_threat() -> None:
    """Returning to post, stated as a comparison rather than as a coordinate.

    The station is what JQ-287's orders phase writes, and a guard that came home
    is nearer to it than to the place it was drawn out to. Asserted this way
    because the exact station drifts with formation work, and "came back" is the
    invariant that survives retuning.
    """
    result = run()
    drawn_to = Vec2(112, 100)

    for guard_id in ("guard-a", "guard-b"):
        guard = result.unit(guard_id)
        to_station = distance(guard.position, guard.destination)
        to_threat = distance(guard.position, drawn_to)

        assert to_station <= to_threat, f"{guard_id} ended nearer the threat than its post"


def test_a_troop_with_no_threat_is_never_committed_at_all() -> None:
    """The contrast case: scattering is a response, not a resting state."""
    peaceful = [unit for unit in scattered() if unit.id != "threat"]
    peaceful.append(make_unit("bystander", HOUND, "south", Vec2(600, 600), hp=1))
    result = play(peaceful, UNIT_TYPES, library(), ticks=20)

    assert assignments_of(result, TROOP) == ()
    assert all(record.assignment is None for record in result.records)
