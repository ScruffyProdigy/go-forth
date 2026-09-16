"""The report: records in, something a human or a diff can read out.

The assertions here are about what the ticket asks the report to *explain* —
which unit, on which tick, posted where, weighing what, against which rivals —
rather than about exact column widths. A test that pinned the layout would fail
on every wording improvement and catch no real defect.

The machine-readable half is held to a stricter standard: it has to be stable
across processes, because comparing two runs is the whole point of it existing.
"""

from __future__ import annotations

import json

from app.sim.ai.decide import decide
from app.sim.ai.factors import FACTORS
from app.sim.ai.inspect.record import DecisionTrace, PersonalityRecord, TraceConfig
from app.sim.ai.inspect.report import NO_REASON, as_dicts, render_json, render_text
from app.sim.ai.profiles import NEUTRAL_BEHAVIOR, PersonalityTag
from app.sim.types import Vec2
from tests.sim.ai.helpers import look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND


def traced(config: TraceConfig | None = None, tick: int = 12) -> DecisionTrace:
    hound = make_unit("h1", HOUND, "north", Vec2(100, 100))
    adept = make_unit("a1", ADEPT, "south", Vec2(110, 100))
    world = make_world([hound, adept])

    observation = look(world, hound)
    trace = DecisionTrace(config) if config else DecisionTrace()
    trace.record(tick, observation, decide(observation, NEUTRAL_BEHAVIOR))
    return trace


def test_text_names_the_tick_the_unit_and_its_troop() -> None:
    text = render_text(traced().records)

    assert "12" in text
    assert "h1" in text
    assert "north-t0" in text


def test_text_names_the_chosen_action_and_its_target() -> None:
    trace = traced()
    text = render_text(trace.records)
    chosen = trace.records[0].chosen

    assert chosen.kind in text
    if chosen.target_id:
        assert chosen.target_id in text


def test_text_shows_each_factor_that_moved_the_chosen_score() -> None:
    trace = traced()
    text = render_text(trace.records)
    contributions = trace.records[0].chosen.contributions

    # Without this the loop below is satisfied by a record that contributed
    # nothing, which is the failure it is here to catch.
    assert len(contributions) == len(FACTORS)
    for contribution in contributions:
        assert contribution.factor in text


def test_text_shows_the_losing_candidates_it_kept() -> None:
    trace = traced(TraceConfig(rivals=2))
    text = render_text(trace.records)

    assert len(trace.records[0].rivals) > 0
    for rival in trace.records[0].rivals:
        assert f"{rival.score:+.3f}" in text


def test_text_says_when_it_dropped_records_rather_than_quietly_truncating() -> None:
    trace = traced(TraceConfig(max_records=1))
    hound = make_unit("h2", HOUND, "north", Vec2(50, 50))
    world = make_world([hound, make_unit("a2", ADEPT, "south", Vec2(60, 50))])
    observation = look(world, hound)
    trace.record(13, observation, decide(observation, NEUTRAL_BEHAVIOR))

    assert trace.dropped == 1
    assert "dropped" in render_text(trace.records, dropped=trace.dropped).lower()


def test_text_reports_a_personality_strength_and_marks_it_unexplained_when_unknown() -> None:
    """Provenance is JQ-330's to supply; until then the report must not pretend."""
    record = traced().records[0]
    with_personality = type(record)(
        **{
            **record.__dict__,
            "personalities": (
                PersonalityRecord(tag=PersonalityTag("reckless"), strength=1.5, overridden=None),
            ),
        }
    )

    text = render_text((with_personality,))

    assert "reckless" in text
    assert "1.5" in text
    assert "overridden" not in text


def test_text_reports_whether_a_strength_was_defaulted_or_overridden_once_known() -> None:
    record = traced().records[0]
    both = type(record)(
        **{
            **record.__dict__,
            "personalities": (
                PersonalityRecord(tag=PersonalityTag("reckless"), strength=1.5, overridden=True),
                PersonalityRecord(tag=PersonalityTag("guardian"), strength=1.0, overridden=False),
            ),
        }
    )

    text = render_text((both,))

    assert "overridden" in text
    assert "default" in text


def test_dicts_carry_the_fields_a_comparison_needs() -> None:
    entry = json.loads(render_json(traced().records))["decisions"][0]

    assert entry["tick"] == 12
    assert entry["unit"]["id"] == "h1"
    assert entry["unit"]["troop"] == "north-t0"
    assert entry["chosen"]["kind"]
    assert entry["candidateCount"] >= 1


def test_as_dicts_is_what_the_json_is_built_from() -> None:
    """Keeps the test above honest about which function it is exercising."""
    assert as_dicts(traced().records) == json.loads(render_json(traced().records))["decisions"]


def test_json_is_stable_for_the_same_records() -> None:
    assert render_json(traced().records) == render_json(traced().records)


def test_json_parses_and_keeps_factors_in_declared_order() -> None:
    parsed = json.loads(render_json(traced().records))
    factors = [c["factor"] for c in parsed["decisions"][0]["chosen"]["contributions"]]

    assert factors == ["objective_progress", "target_suitability", "danger", "ally_support"]


def test_an_empty_trace_reports_that_rather_than_rendering_nothing() -> None:
    assert render_text(()).strip() != ""


def test_text_renders_the_reason_when_one_is_present() -> None:
    """Written against the function, because no battle here can produce one.

    `Decision` gains its `reason` in JQ-329, so on this branch `_reason_of`
    returns empty for every unit of every tick and the populated half of the
    render is unreachable from any fixture. An unwired seam is untested by
    construction: the suite can spawn as many subprocesses as it likes and never
    once exercise this line. So it is exercised directly, on a record built by
    hand, and the day the seam is wired this is already covered rather than
    surfacing as a fault in whoever merged.
    """
    record = traced().records[0]
    explained = type(record)(**{**record.__dict__, "reason": "pursuit_abandoned_leash"})

    assert "pursuit_abandoned_leash" in render_text((explained,))


def test_text_says_unexplained_when_no_reason_was_recorded() -> None:
    """The other half — a reason that is absent rather than merely short.

    The record is built with an empty reason rather than taken as it comes. An
    earlier version asserted `record.reason == ""` on a freshly traced decision,
    which is true on this branch and false the moment JQ-329's vocabulary lands —
    a fact about when the test was written, encoded as an assertion. The trial
    integration failed on exactly that.
    """
    record = traced().records[0]
    unexplained = type(record)(**{**record.__dict__, "reason": ""})

    assert NO_REASON in render_text((unexplained,))


def test_json_carries_the_dropped_count_too() -> None:
    """The text renderer had this test and the JSON did not.

    The whole reason the cap counts what it turned away is so a truncated report
    says it is truncated. A comparison run off the JSON needs that as much as a
    person reading the text does — more, since there is no prose to notice its
    absence in.
    """
    trace = traced(TraceConfig(max_records=1))
    hound = make_unit("h2", HOUND, "north", Vec2(50, 50))
    world = make_world([hound, make_unit("a2", ADEPT, "south", Vec2(60, 50))])
    observation = look(world, hound)
    trace.record(13, observation, decide(observation, NEUTRAL_BEHAVIOR))

    assert trace.dropped == 1, "nothing was dropped, so the count proves nothing"
    assert json.loads(render_json(trace.records, trace.dropped))["dropped"] == 1
