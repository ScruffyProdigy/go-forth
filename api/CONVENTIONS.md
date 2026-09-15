# Conventions for the Go Forth! API

Go Forth!'s api is the **Python** reference implementation for JoinQuest. rpslr
and wordhunt cover TypeScript; this one exists so a Python developer — or their
agent — has something to read in the language they are actually writing.

That shapes two rules that override ordinary taste:

1. **The wire contract is fixed.** It must match rpslr exactly. Only the
   implementation is Python. If something here reads better with a different
   payload shape, it is still wrong.
2. **The architecture should match too.** The only difference between the
   references should be the language. That is why migrations are plain SQL
   files with a small in-repo runner rather than Alembic: someone comparing
   rpslr to go-forth to learn the JoinQuest contract should not have to learn a
   migration framework on the way.

## Determinism

JQ-186 requires the battle sim to be byte-identical across runs. Python makes
that harder than TypeScript did, in a way that is invisible if you port by
reading.

**Python randomizes string hashing per process.** Iterating a `set` gives a
different order in every fresh interpreter. Measured on eight plain strings:

```
in-process, two iterations identical: True
distinct set-iteration orders across 8 fresh processes: 8
```

TypeScript has no such hazard — its `Set` iterates in insertion order — so code
that was correct there becomes non-deterministic here with no visible change.

**The rules:**

- Use `set` for membership tests only. Never iterate one where the order can
  reach output.
- Never iterate a `dict` keyed by anything whose order matters unless you
  control insertion order deliberately.
- Sort explicitly when order matters. `sorted(...)` on a stable key, not
  whatever the container hands back.
- Seed an explicit `random.Random(seed)`. Never touch module-level `random`,
  which shares global state with everything else in the process.

**Testing it:** a determinism test must spawn a real subprocess.

```python
out = {
    subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, check=True).stdout
    for _ in range(5)
}
assert len(out) == 1
```

`PYTHONHASHSEED` is fixed once at interpreter startup, and **pytest runs the
whole suite in one interpreter**. Running the sim twice inside a test therefore
samples a single hash seed and passes unconditionally — it is the shape of test
most people write for this, and the one shape that proves nothing. This was
confirmed by deliberately breaking the removal phase to iterate a set of ids:
every in-process test still passed; only the fresh-interpreter ones failed.

For the same reason, **`PYTHONHASHSEED` must never be pinned in CI.** Pinning it
is the natural-looking fix for a determinism "flake", and it disarms every such
test everywhere while turning them green. `api-tests.yml` asserts it is unset.

## Porting from the TypeScript

**Capture golden vectors from the old implementation before deleting it.**

A wrong transliteration is still perfectly deterministic. The JQ-286 port of
mulberry32 XORed the wrong operand and shifted 15 where the JavaScript shifts
14, and produced a stable, reproducible, entirely different sequence — passing
every determinism test it had. Only output captured from the TypeScript caught
it.

**Retire a golden vector when the behaviour it pins is superseded, rather than
teaching the sim to reproduce it.** `tests/sim/golden_battles.json` proved the
JQ-286 port matched the TypeScript, which is a claim about one moment: slice B
(JQ-287) replaces the movement rule those battles encode — everybody marches at
the enemy base — with orders and derived formations, so no correct
implementation of slice B can reproduce them. Keeping them green would have
meant keeping a superseded rule alive behind a flag. The PRNG vectors in
`test_rng.py` pin the generator rather than the game and are untouched.

**Compare across languages by parsed value, not by bytes.** Python and
JavaScript format some floats differently in JSON (`1e+21` vs `1e21`, `1e-06`
vs `0.000001`). Byte-identical determinism means *one implementation
reproducing its own output* — not two languages agreeing on float formatting.
Those are different claims, and conflating them sends you chasing an impossible
one.

## Boundaries in the sim's geometry

**Where this file has failed twice: a rule that stops a unit *at* a boundary, and
a second rule that tests whether it is *past* that boundary.** The two overlap at
exactly one point, and floating point will not reliably put anything on it.

First instance (JQ-287). Movement capped a step at `distance - weapon range`, so
a unit could never end a tick inside its range; combat fired at
`distance <= range`. A unit walking straight at an enemy lands on the boundary
exactly — along the line of approach a step closes the distance by its own length
— so head-on worked and every test was written head-on. Walking *past* something
closes by less, so the unit converged on its own weapon range from outside and
stopped there for ever: a hair out of range so it could not shoot, out of slack so
it could not walk on. A hound frozen at `20.000000000000018` against a range of
20, alive and out of the battle.

Second instance (JQ-379), in the fix for the first. The standoff clamp lands a
unit *exactly* on the standoff line, and the test for "already inside the
standoff" used a strict `<`. So the unit was counted again the next tick, handed
a slack of zero, and pinned there permanently.

**The rule: the predicate that decides where a unit stops and the predicate that
decides what it may then do must overlap on an interval, not at a point.** In
practice that means one of two things, and both are cheap:

- Put the stopping distance strictly inside the acting distance — `ENGAGEMENT_STANDOFF`
  is nine tenths of weapon range for this reason, so "close enough to stop" and
  "close enough to fire" are the same state rather than two that meet at a point.
- Where a clamp lands a value on a boundary, make the test for being at that
  boundary inclusive. `gap <= standoff` counts the line as inside, because the
  line is exactly where the clamp puts things.

**Both were found by breaking a new test on purpose, not by review.** An
invariant of the form "never get closer than X" is satisfied perfectly by a unit
that never goes anywhere, so on its own it is not evidence of anything. Write the
complementary test too — that a unit whose path takes it inside range ends up
able to fire — and stage it **off-axis**, because head-on is the one arrangement
that works when this is broken.

**And check that the break actually applied.** Breaking a test on purpose is the
only way to learn whether it is evidence, and it has a failure mode of its own:
the edit that was supposed to break the code does not land — a formatter has
reflowed the line an anchor matched on, a patch script prints success over a file
it never touched — and the suite runs green against unmodified source. "I broke
it and the test passed" and "I believe I broke it and the test passed" are
indistinguishable in a terminal, and only the first means anything.

This happened twice in one hour on JQ-329, to two people, in opposite directions:
once verifying a test (a green run read as "my test has a blind spot", when
nothing had been modified) and once verifying a fix (a green run read as "the fix
works", same cause). One of them was nearly reported as a finding. So: assert the
injection matched before trusting the result, and treat a falsification
experiment that cannot fail as exactly the same error as a test that cannot fail.

A related blind spot in the test itself, from the same episode. "Nothing was
dropped from this record" is naturally written as a walk over `dataclasses.fields`
comparing each by name — and that cannot fail, because a dropped field holds its
*default* on both sides of the comparison. Compare the records whole, with the
field that legitimately varies normalised away.

## Movement does not guarantee separation — the behaviour layer does

Read the standoff clamp in `phases/movement.py` and it looks like the thing that
keeps units apart. It is not, and the difference matters because it is invisible
until a behaviour layer is attached.

What holds a line without one is the **engage-en-route** rule: a unit stops the
moment anything is within its weapon range. The standoff sits inside that range,
so an ordinary unit has already stopped before the clamp could bind. Measured on
the placeholder armies with no behaviour layer, closest approach between opposing
units over a whole battle is 16.8 on every seed.

A unit acting on an *intent* (JQ-328) skips that check by design — that is what
makes "press the objective past a weak enemy" possible, and pressing past
something in a sim with no collision means passing through it. The clamp does not
catch it either: since JQ-379 an enemy a unit is already inside the standoff of
does not cap the step.

**On JQ-328 that produced real overlap, and JQ-329 removed it.** Measured across
five seeds, before and after:

```
JQ-328   closest approach 0.00-0.79   overlap episodes 1-3 per battle
JQ-329   closest approach 1.96-13.11  overlap episodes 0 on every seed
```

Nothing was added to prevent it. The cause was that the only way to close on an
enemy was to walk at the enemy's own coordinates, so a unit that pressed on
arrived exactly on top of it. JQ-329 aims every approach at the unit's own
**useful range** from the target instead — the place it wants to stand to fight —
and units stop where they can fight rather than where the target is standing.

So the question JQ-380 was opened to decide, whether opposing units may come to
rest on the same point, is answered in practice: on the current evaluator they do
not. `tests/sim/ai/separation.py` still measures it, because the guarantee is
emergent rather than enforced — nothing in the sim *prevents* overlap, and a
future candidate that aims somewhere else would bring it back.

## Boundaries in scoring are the same hazard as boundaries in geometry

The rule two sections up — a stopping predicate and an acting predicate must
overlap on an interval rather than at a point — has a second form, one layer up,
and JQ-329 hit it twice.

**A gradient with a kink oscillates even though its value is continuous.**
`objective_progress` measured distance from a station through
`max(0, gap - tolerance)`: smooth in value, but its slope jumps from zero to one
at the tolerance. Inside, a step away from the post was free; one step outside,
it cost a full stride. A unit walked out to the edge, found the next step
expensive, walked back in, found the step out free again — and alternated between
two positions one map unit apart for a hundred and seventy ticks, committing to a
chase and abandoning it on every one of them. The fix is a ramp with no kink at
all (`gap**2 / (gap + tolerance)`), not a smaller kink.

**And a decision margin does not fix an equilibrium.** The obvious remedy —
require a new action to beat the incumbent by some margin — only widens the band
the unit wanders inside, because near an equilibrium the scores are close *by
construction*. Measured on an iron-bulwark holding a post: the two competing
candidates cross at three units off the post, both worth +0.0513, and either side
of the crossing the leader changes by about 0.03 per unit travelled. No margin
small enough to be honest covers that, and one large enough stops the unit
noticing anything.

What works is making one candidate win outright near the crossing, and the only
candidate that can is **the one that does not move**. Every factor in the
evaluator is a *rate* — ground gained this tick, not ground held — so `hold`
scores zero however well placed a unit is, while both walking toward its post and
walking toward an enemy score positive. Moving beats standing almost everywhere.
`decide.MOVEMENT_THRESHOLD` requires a step to be clearly better than standing
still, and the unit settles where no step is worth taking.

**The general lesson.** A scoring function re-derived from scratch every tick has
no memory, so anywhere two of its terms balance is a potential limit cycle. Look
for them wherever a new factor is added, and test for them by running a unit to a
settled state rather than by reading one tick — a single-tick assertion cannot
tell a decision from an oscillation.

## Layout

```
api/
├── pyproject.toml   # deps, ruff, mypy and pytest config, all in one file
├── app/
│   ├── main.py      # the FastAPI factory
│   ├── server.py    # binds the port: `python -m app.server`
│   ├── config.py    # environment, with defaults that run without a .env
│   └── sim/         # the battle sim (JQ-286)
├── migrations/      # forward-only *.sql, applied in filename order
└── tests/           # not co-located; the Python convention, unlike rpslr
```

`tests/` sits outside the package, so `pyproject.toml` puts `.` on the path via
`[tool.pytest.ini_options] pythonpath`.

## Toolchain

Python 3.12. `pip install -e ".[dev]"` from `api/` is the documented path and
needs nothing beyond a virtualenv; [uv](https://docs.astral.sh/uv/) reads the
same `pyproject.toml` and is faster if you have it, but nothing requires it —
a reference implementation should ask a reader to install as little as
possible.

```bash
ruff check .          # lint
ruff format .         # format
mypy app tests        # strict
pytest                # tests
```

All four run in CI on every change under `api/`.
