"""Runs a battle with the decision inspector on and says why units did things.

Deliberately outside `app/sim/`, for the same reason `battle_demo.py` is: this is
the piece that talks to the outside world — argv in, stdout out, a wall clock for
`--cost` — and `tests/sim/test_purity.py` asserts nothing of the sort is
reachable from `run_battle`. The sim collects records; this prints them.

    python -m app.scripts.decision_report
    python -m app.scripts.decision_report --unit north-t0-s0 --from 40 --to 60
    python -m app.scripts.decision_report --json
    python -m app.scripts.decision_report --cost
    python -m app.scripts.decision_report --emit battle --trace

`--emit report` (the default) prints the explanation. `--emit battle` prints the
canonical battle serialization instead — the same bytes `battle_demo` prints —
which is what lets `tests/sim/ai/test_inspect_determinism.py` run the same battle
with `--trace` and `--no-trace` in fresh interpreters and compare the two.

`--cost` answers the ticket's measurement question: how many candidates a unit
weighs at opening-demo density, and what the decision phase costs against the
tick budget. It is a targeted check printed for the record, not a benchmark
platform — the numbers depend on the machine, so it prints the machine's terms
alongside them.
"""

from __future__ import annotations

import argparse
import platform
import sys
import time
from collections.abc import Sequence

from app.sim import (
    DEFAULT_SIM_CONFIG,
    TWO_LANE_MAP,
    SimConfig,
    placeholder_battle,
    run_battle,
    sample_library,
    serialize_battle,
)
from app.sim.ai.inspect.record import DecisionTrace, TraceConfig
from app.sim.ai.inspect.report import render_json, render_text

DEFAULT_SEED = 20260911


def _trace_config(args: argparse.Namespace) -> TraceConfig:
    return TraceConfig(
        unit_ids=frozenset(args.unit) if args.unit else None,
        first_tick=args.from_tick,
        last_tick=args.to_tick,
        max_records=args.max_records,
        rivals=args.rivals,
    )


def _run(args: argparse.Namespace, trace: DecisionTrace | None):  # type: ignore[no-untyped-def]
    setup = placeholder_battle()
    setup.behavior = sample_library()
    config = SimConfig(max_battle_seconds=args.seconds) if args.seconds is not None else DEFAULT_SIM_CONFIG
    return run_battle(TWO_LANE_MAP, [], setup, args.seed, config, trace=trace)


def _cost(args: argparse.Namespace) -> int:
    """Candidate counts and decision cost, with the terms they were measured on.

    Timed against a run with tracing *on*, because the trace is what can report
    the candidate counts — and then against one with it off, so the cost of the
    inspector itself is visible rather than folded into the AI's.
    """
    trace = DecisionTrace(TraceConfig(max_records=200_000))

    started = time.perf_counter()
    _run(args, trace)
    traced_seconds = time.perf_counter() - started

    started = time.perf_counter()
    plain = _run(args, None)
    plain_seconds = time.perf_counter() - started

    ticks = plain.final_state.tick
    units = len(plain.ticks[0].state.units)
    counts = [record.candidate_count for record in trace.records]
    budget_ms = 1000 / plain.config.tick_rate

    print(f"machine        {platform.platform()}")
    print(f"python         {platform.python_version()} ({platform.machine()})")
    print(f"map/seed       {plain.map.id} / {args.seed}")
    print(f"units at open  {units}")
    print(f"ticks run      {ticks} at {plain.config.tick_rate}/s (budget {budget_ms:.1f} ms/tick)")
    print()
    print(f"decisions      {len(counts)}")
    if counts:
        print(f"candidates     min {min(counts)}, mean {sum(counts) / len(counts):.1f}, max {max(counts)}")
    print(f"whole battle   {plain_seconds * 1000:.0f} ms untraced, {traced_seconds * 1000:.0f} ms traced")
    if ticks:
        per_tick = plain_seconds * 1000 / ticks
        print(f"per tick       {per_tick:.3f} ms untraced  ({per_tick / budget_ms:.1%} of budget)")
        print(f"               {traced_seconds * 1000 / ticks:.3f} ms traced")
        print(f"headroom       {budget_ms - per_tick:.2f} ms/tick untraced")
    print()
    print("The whole battle is timed, not the decision phase alone — every other")
    print("phase is in these numbers too, so the headroom shown is the real one.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="shorten the battle's backstop length; the determinism tests use it",
    )
    parser.add_argument(
        "--emit",
        choices=("report", "battle"),
        default="report",
        help="the decision report, or the canonical battle serialization",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument(
        "--unit",
        action="append",
        default=[],
        help="only this unit; repeatable",
    )
    parser.add_argument("--from", dest="from_tick", type=int, default=0)
    parser.add_argument("--to", dest="to_tick", type=int, default=None)
    parser.add_argument("--rivals", type=int, default=3, help="losing candidates kept per decision")
    parser.add_argument("--max-records", dest="max_records", type=int, default=2000)
    parser.add_argument(
        "--cost",
        action="store_true",
        help="measure candidate counts and decision cost against the tick budget",
    )

    tracing = parser.add_mutually_exclusive_group()
    tracing.add_argument("--trace", dest="trace", action="store_true", default=True)
    tracing.add_argument("--no-trace", dest="trace", action="store_false")

    args = parser.parse_args(argv)

    if args.cost:
        return _cost(args)

    trace = DecisionTrace(_trace_config(args)) if args.trace else None
    result = _run(args, trace)

    if args.emit == "battle":
        # The canonical bytes and nothing else, so two runs can be diffed.
        print(serialize_battle(result))
        return 0

    if trace is None:
        print("nothing to report: --emit report with --no-trace", file=sys.stderr)
        return 2

    render = render_json if args.json else render_text
    print(render(trace.records, trace.dropped), end="" if not args.json else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
