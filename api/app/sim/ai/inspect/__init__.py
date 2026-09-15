"""Explaining a decision after the fact, without being able to change it.

JQ-328 built the decision loop so that everything needed to explain a choice
survives it: `Decision` keeps every candidate it scored, `FactorContribution`
keeps each factor's raw verdict next to the weight that scaled it, and
`ResolvedBehavior` keeps the traits and personalities that produced the weights.
None of that is read by the sim. This package is what reads it.

Two rules hold the whole thing up.

**Tracing is opt-in, and off by default.** A battle with no trace on its tick
context runs the code path it ran before this package existed — one `is None`
check per unit per tick. Nothing here is ever on the critical path of a real
match.

**Tracing observes; it never participates.** Nothing in here draws from the rng,
writes to the world, or is read by any scoring decision. `tests/sim/ai/
test_inspect_determinism.py` holds that to byte-identical output between a run
with tracing on and the same run with it off, in fresh processes.

=================  ============================================================
Module             What it owns
=================  ============================================================
`record`           the flat, immutable records and the bounded recorder
`report`           turning records into something a human or a diff can read
=================  ============================================================

The split matters: `record` is pure sim (it is reachable from `app/sim/__init__`
and so is held to `tests/sim/test_purity.py` — no clock, no I/O, no `print`), and
`report` only ever returns strings. Whatever finally *writes* those strings lives
in `app/scripts/`, outside the sim entirely.

**Nothing is re-exported here**, for the same reason as `ai/__init__.py`: the
import cycle through `world.py` is real. Import the submodule you want.
"""
