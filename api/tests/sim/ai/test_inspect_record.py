"""The trace recorder: what it keeps, what it refuses to keep, and what it copies.

Two properties matter more than the field list. It **flattens on the way in** —
a record holds values, never a reference to a `Decision` or a `Unit` that later
ticks go on to rewrite — and it is **bounded**, because a 1800-tick battle at
opening-demo density would otherwise hold a record for every unit of every tick
in memory and call that a developer tool.
"""

from __future__ import annotations

from app.sim.ai.decide import decide
from app.sim.ai.inspect.record import DecisionTrace, TraceConfig
from app.sim.ai.profiles import NEUTRAL_BEHAVIOR
from app.sim.types import Vec2
from app.sim.world import Unit, World
from tests.sim.ai.helpers import look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND


def staged() -> tuple[World, Unit]:
    """One hound in reach of one enemy adept: a decision with real rivals."""
    hound = make_unit("h1", HOUND, "north", Vec2(100, 100))
    adept = make_unit("a1", ADEPT, "south", Vec2(110, 100))
    world = make_world([hound, adept])
    return world, hound


def test_records_the_tick_and_the_unit_that_decided() -> None:
    world, hound = staged()
    observation = look(world, hound)
    decision = decide(observation, NEUTRAL_BEHAVIOR)

    trace = DecisionTrace()
    trace.record(7, observation, decision)

    assert len(trace.records) == 1
    assert trace.records[0].tick == 7
    assert trace.records[0].unit_id == "h1"


def test_records_the_troop_and_the_assignment_the_unit_decided_against() -> None:
    world, hound = staged()
    hound.destination = Vec2(140, 160)
    observation = look(world, hound)

    trace = DecisionTrace()
    trace.record(1, observation, decide(observation, NEUTRAL_BEHAVIOR))

    record = trace.records[0]
    assert record.troop_id == "north-t0"
    assert record.station == Vec2(140, 160)


def test_records_the_chosen_action_with_its_factor_contributions() -> None:
    world, hound = staged()
    observation = look(world, hound)
    decision = decide(observation, NEUTRAL_BEHAVIOR)

    trace = DecisionTrace()
    trace.record(1, observation, decision)

    chosen = trace.records[0].chosen
    assert chosen.kind == decision.selected.kind
    assert chosen.score == decision.score
    assert [c.factor for c in chosen.contributions] == [c.factor for c in decision.contributions]


def test_keeps_the_top_rivals_and_counts_every_candidate_considered() -> None:
    world, hound = staged()
    observation = look(world, hound)
    decision = decide(observation, NEUTRAL_BEHAVIOR)

    trace = DecisionTrace(TraceConfig(rivals=1))
    trace.record(1, observation, decision)

    record = trace.records[0]
    assert record.candidate_count == len(decision.considered)
    assert len(record.rivals) == 1
    # The rival kept is the best of the losers, not merely the next in list order.
    losers = sorted(
        (e for e in decision.considered if e.candidate != decision.selected),
        key=lambda e: -e.score,
    )
    assert record.rivals[0].score == losers[0].score


def test_a_record_does_not_move_when_the_unit_does() -> None:
    """JQ-329's warning: commitment state on the unit outlives one tick."""
    world, hound = staged()
    observation = look(world, hound)

    trace = DecisionTrace()
    trace.record(1, observation, decide(observation, NEUTRAL_BEHAVIOR))
    station_when_recorded = trace.records[0].station

    hound.destination = Vec2(999, 999)
    hound.position = Vec2(999, 999)

    assert trace.records[0].station == station_when_recorded


def test_stops_recording_at_its_bound_and_counts_what_it_dropped() -> None:
    world, hound = staged()
    observation = look(world, hound)
    decision = decide(observation, NEUTRAL_BEHAVIOR)

    trace = DecisionTrace(TraceConfig(max_records=2))
    for tick in range(5):
        trace.record(tick, observation, decision)

    assert len(trace.records) == 2
    assert trace.dropped == 3


def test_records_only_the_units_it_was_asked_about() -> None:
    world, hound = staged()
    adept = world.units[1]
    trace = DecisionTrace(TraceConfig(unit_ids=frozenset({"a1"})))

    for unit in (hound, adept):
        observation = look(world, unit)
        trace.record(1, observation, decide(observation, NEUTRAL_BEHAVIOR))

    assert [r.unit_id for r in trace.records] == ["a1"]


def test_records_only_within_the_tick_window_it_was_asked_about() -> None:
    world, hound = staged()
    observation = look(world, hound)
    decision = decide(observation, NEUTRAL_BEHAVIOR)

    trace = DecisionTrace(TraceConfig(first_tick=3, last_tick=5))
    for tick in range(8):
        trace.record(tick, observation, decision)

    assert [r.tick for r in trace.records] == [3, 4, 5]


def test_a_window_outside_the_bound_drops_nothing() -> None:
    """Out-of-window is not the same as dropped; only the cap loses data."""
    world, hound = staged()
    observation = look(world, hound)
    decision = decide(observation, NEUTRAL_BEHAVIOR)

    trace = DecisionTrace(TraceConfig(first_tick=100))
    trace.record(1, observation, decision)

    assert trace.records == ()
    assert trace.dropped == 0
