"""What the decision loop costs at opening-demo density.

Split deliberately down the middle of what is knowable. **Candidate counts are
deterministic**, so they are asserted here: a bounded candidate set is the
property that keeps the loop affordable, and an accidental explosion — a
positional candidate generated per enemy per step, say — shows up as a number
rather than as a slow afternoon.

**Wall-clock cost is not deterministic**, so it is not asserted here. It depends
on the machine, and a timing assertion tight enough to catch a regression is
also tight enough to fail on a busy CI box, which teaches everyone to ignore it.
`python -m app.scripts.decision_report --cost` measures it and prints the
machine's terms alongside the numbers; `docs/ai-decision-cost.md` records a run.

See the ticket's own words: a targeted check, not a benchmark platform.
"""

from __future__ import annotations

from app.sim.ai.fixtures import sample_library
from app.sim.ai.inspect.record import DecisionTrace, TraceConfig
from app.sim.config import SimConfig
from app.sim.fixtures import placeholder_battle
from app.sim.map import TWO_LANE_MAP
from app.sim.run_battle import run_battle

SEED = 20260915
SHORT = SimConfig(max_battle_seconds=6)

#: The loop weighs a handful of options, not a search tree. Generous enough that
#: JQ-329's positional candidates and JQ-330's coordination have somewhere to
#: grow, tight enough that a per-enemy-per-step explosion trips it.
CANDIDATE_CEILING = 40


def traced() -> DecisionTrace:
    setup = placeholder_battle()
    setup.behavior = sample_library()
    trace = DecisionTrace(TraceConfig(max_records=100_000))
    run_battle(TWO_LANE_MAP, [], setup, SEED, SHORT, trace=trace)
    return trace


TRACE = traced()


def test_the_demo_roster_actually_decides_something() -> None:
    """Guards every assertion below: zero decisions would pass all of them."""
    assert len(TRACE.records) > 100


def test_no_unit_ever_weighs_more_candidates_than_the_ceiling() -> None:
    worst = max(TRACE.records, key=lambda r: r.candidate_count)

    assert worst.candidate_count <= CANDIDATE_CEILING, (
        f"{worst.unit_id} weighed {worst.candidate_count} candidates on tick {worst.tick}"
    )


def test_every_decision_had_at_least_one_candidate() -> None:
    """`hold` is always legal, so an empty candidate set means a broken filter."""
    assert min(record.candidate_count for record in TRACE.records) >= 1


def test_the_average_decision_stays_small() -> None:
    counts = [record.candidate_count for record in TRACE.records]

    assert sum(counts) / len(counts) <= 10
