"""Tracing wired into a real battle: it collects, and it changes nothing.

The wiring is one optional field on `TickContext` and one call in the decision
phase. What these tests pin is the *optional* half — that a battle with no trace
behaves exactly as it did before this package existed, and that a battle with one
comes out with the same result as a battle without.

The byte-identical claim is made properly, across fresh processes, in
`test_inspect_determinism.py`. These are the in-process version, which is
cheaper and catches the ordinary mistakes: a recorder that draws from the rng, or
one that writes to the world it is reading.
"""

from __future__ import annotations

from app.sim.ai.fixtures import sample_library
from app.sim.ai.inspect.record import DecisionTrace, TraceConfig
from app.sim.config import SimConfig
from app.sim.fixtures import placeholder_battle
from app.sim.map import TWO_LANE_MAP
from app.sim.run_battle import BattleResult, run_battle
from app.sim.serialize import digest_battle

SEED = 20260915
#: Long enough for units to meet and decide something; short enough to run often.
SHORT = SimConfig(max_battle_seconds=6)


def battle(trace: DecisionTrace | None = None) -> BattleResult:
    setup = placeholder_battle()
    setup.behavior = sample_library()
    return run_battle(TWO_LANE_MAP, [], setup, SEED, SHORT, trace=trace)


def test_a_battle_with_no_trace_still_runs() -> None:
    assert battle().outcome in ("annihilation", "timeUp", "baseDestroyed")


def test_tracing_collects_decisions_from_a_real_battle() -> None:
    trace = DecisionTrace()
    battle(trace)

    assert len(trace.records) > 0
    assert {r.tick for r in trace.records} != {0}


def test_tracing_does_not_change_the_battle() -> None:
    assert digest_battle(battle(DecisionTrace())) == digest_battle(battle())


def test_tracing_does_not_change_the_battle_when_it_is_recording_nothing() -> None:
    """A filter that matches no unit must not be a different code path either."""
    narrow = DecisionTrace(TraceConfig(unit_ids=frozenset({"nobody"})))
    result = battle(narrow)

    assert narrow.records == ()
    assert digest_battle(result) == digest_battle(battle())


def test_tracing_does_not_consume_randomness() -> None:
    """The clearest way a recorder could corrupt a battle, pinned on its own."""
    with_trace = battle(DecisionTrace())
    without = battle()

    assert with_trace.final_state.rng_state == without.final_state.rng_state


def test_a_trace_records_the_unit_it_was_narrowed_to_and_no_other() -> None:
    everyone = DecisionTrace()
    battle(everyone)
    one_id = everyone.records[0].unit_id

    narrowed = DecisionTrace(TraceConfig(unit_ids=frozenset({one_id})))
    battle(narrowed)

    assert {r.unit_id for r in narrowed.records} == {one_id}


def test_a_trace_honours_its_tick_window_in_a_real_battle() -> None:
    trace = DecisionTrace(TraceConfig(first_tick=10, last_tick=12))
    battle(trace)

    assert {r.tick for r in trace.records} <= {10, 11, 12}
    assert trace.records != ()
