# AI decision cost, and what the inspector found

Two things the JQ-331 acceptance asks to be written down rather than asserted:
what the decision loop costs at opening-demo density, and what watching it
through the inspector actually turned up. The numbers are one machine's and the
tuning is provisional, but the tree is the merged one — JQ-328, JQ-329 and
JQ-330 all landed.

Reproduce the measurement with:

```bash
python -m app.scripts.decision_report --cost
```

## Measured cost

Recorded 2026-09-15 on the merged tree, default two-lane map, placeholder roster.

| | |
|---|---|
| Machine | macOS 14.7.6, x86_64 |
| Python | 3.12.14 |
| Map / seed | `two-lane` / 20260911 |
| Units at open | 18 |
| Battle length | 1324 ticks at 20/s |
| Tick budget | 50.0 ms |

| | |
|---|---|
| Decisions traced | 19,569 |
| Candidates per decision | min 2, mean 2.5, max 9 |
| Whole battle, untraced | 17,071 ms |
| Whole battle, traced | 17,314 ms |
| **Per tick, untraced** | **12.89 ms — 25.8% of budget** |
| Per tick, traced | 13.08 ms |
| **Headroom** | **37.11 ms/tick** |

Three things worth saying plainly.

**The whole battle is timed, not the decision phase alone.** Movement, combat,
abilities, energy, coordination and the per-tick world deep-copy are all inside
the 12.89 ms. That makes the headroom the real one rather than a flattering
slice, and the decision loop's own share is smaller than the number shown.

**Cost has tripled across the three tickets and is still comfortable.** JQ-328
alone measured 7.65 ms/tick; JQ-329's oscillation fix took it to 5.63 by
shortening battles; the merged tree with coordination and threat modelling is
12.89. A quarter of budget, with the demo's full roster, on a four-year-old
laptop.

**Tracing now costs almost nothing** — 0.18 ms/tick, down from 2.3 — because the
recorder flattens fewer per-candidate structures than it did before `influences`
moved onto `ScoredCandidate`. Nobody pays it in a match either way: a battle with
no trace pays one `is None` per unit per tick.


## What the inspector found

These came out of reading actual reports, and are recorded for JQ-313's
playtests. **None of them is fixed here** — JQ-331 is the tool, and each of
these belongs to the ticket that owns the behavior.

### 1. `danger` is inert at the opening-demo roster (JQ-329 owns this) — **fixed and merged**

Every report shows the same thing:

```
danger +0.00x2.5=+0.00
```

The raw danger score is 0.00 for essentially every candidate, so the weight
scaling it — however carefully tuned — multiplies nothing. A `wary` adept with
danger weighted 2.5 behaves identically to one that ignores danger entirely.

JQ-329 has independently identified the cause: danger is scored on what is
already adjacent rather than on what is *closing*, so a melee unit forty units
from a skirmisher reads as perfectly safe. Recorded here because it means **any
danger-related tuning done before JQ-329 lands is tuning a number that never
reaches a decision**.

### 2. Aggressive creatures saturate the danger weight floor — **half-fixed and merged**

`cinder-hound` opens at danger 0.75; the `aggressive` trait takes 0.5 off it,
and a single `reckless` mage takes off the remaining 0.25 and more. The weight
clamps at 0.

The clamping is correct and deliberate — `factors.py` keeps weights non-negative
so "ignores danger" can never become "seeks harm". The consequence for tuning is
that **personality strength above the default has no further effect on danger
for an already-aggressive creature**. A designer raising a mage's reckless
strength from 1.0 to 2.0 and seeing its hounds behave identically is looking at
this, not at a bug. Pinned in
`tests/sim/ai/scenarios/test_personality_comparison.py`.

Worth revisiting once (1) is fixed, since a danger score that actually varies may
make the floor easier to reach than intended.

**Status.** JQ-330 measured this against its own branch: the contextual redesign
fixes half of it. Raising reckless from 1.0 to 2.0 still moves nothing on the
candidates the tag speaks to, because its closing delta pins the floor above
strength 0.42. What it does fix is the *leak* — the hound keeps its standing
danger of 0.25 instead of being fearless in every context for a whole battle. A
better failure rather than an absent one, and both halves are now pinned as
tests here and on JQ-330's side.

### 3. `hold` and `advance` on the station tie more often than expected — **fixed and merged**

With danger inert and ally support saturated, a unit already at its post often
scores `hold` and `advance`-on-station within a rounding error of each other, and
the tie is broken by declared candidate order rather than by anything meaningful.
It is reproducible and harmless today. It is the kind of thing that becomes
visible as jitter once units have somewhere more interesting to be, so it is
worth a second look during JQ-329's positioning work.

**Status.** Bigger than this entry guessed. JQ-329 found the cause is structural
rather than a matter of tuning: every factor is a *rate*, so `hold` scores zero
however well placed a unit is, while both walking to the post and walking at an
enemy score positive — moving beat standing almost everywhere. They measured a
unit alternating 23.0 / 24.0 / 23.0 for a hundred and seventy ticks, committing
to a chase and abandoning it every tick. Fixed with `decide.MOVEMENT_THRESHOLD`
plus a smooth objective gradient; reversals now under 1%. Written up in
`CONVENTIONS.md` under "Boundaries in scoring are the same hazard as boundaries
in geometry".

## Profile descriptions vs. visible behavior

The acceptance asks to confirm the one-sentence profile descriptions match what
units visibly do. **Re-measured on the merged tree**, one seed, a full 1324-tick
battle, as the share of each type's chosen actions:

| Profile | hold | advance→station | advance→enemy | attack | retreat |
|---|---|---|---|---|---|
| `ash-ram` | 90% | 7% | 2% | 1% | — |
| `cinder-hound` | 82% | 7% | 3% | **9%** | — |
| `ember-adept` | 50% | 46% | 3% | 0% | 0% |
| `ember-sprite` | 58% | 37% | 3% | 1% | **2%** |

| Profile | Description says | Verdict |
|---|---|---|
| `cinder-hound` | fast, short-ranged, so it closes | **matches.** Nine times the attack share of the adept, and the only type that fights rather than positions. |
| `ash-ram` | slow and tough, walks at the objective | **matches.** It arrives and then stands on its post — 90% hold is what "arrived" looks like for the slowest creature on the field. |
| `ember-sprite` | has reach and keeps it | **matches, and only became checkable on this tree.** It is the one type that retreats at all, which is range management showing up in the action mix rather than in a weight. |
| `ember-adept` | wary | **matches now.** It closes on enemies 3% of the time against the hound's 3% but attacks 0% against the hound's 9% — it positions and declines fights. On JQ-328's tree it closed 48% of the time, more often than the aggressive hound, because `danger` scored 0.00 and the trait that defines it bought nothing. |

All four confirmed. Two of them were not confirmable before JQ-329, and the
fourth was an outright mismatch — recorded below as finding (1), fixed by the
work it prompted.

**Reason mix** — 1 seed, full 90-second battle, and *always quote the run length
beside one of these*: `holding_station` 62.8%, `pressing_objective` 31.4%,
`pursuing` 1.9%, `engaging` 1.8%, `retreating` 0.8%, `screening_inferred` 0.6%,
`returned_to_station` 0.3%, `screening` 0.2%, `pursuit_started` 0.1%,
`intercepting` 0.1%, then `target_switched` and two pursuit-abandonment reasons
under 0.1%.

Both screen provenances appear in one battle, which is the distinction working
end to end: `screening` where JQ-330's coordinator named the ally, and
`screening_inferred` where the unit worked it out for itself.

Reproduce with:

```bash
python -m app.scripts.decision_report --cost
python -m app.scripts.decision_report --json
```

### 4. Ranged spacing does not survive a whole battle (open)

Found by packaging the scenarios, and the clearest example of why this ticket
assembles runs rather than trusting per-behaviour tests.

JQ-329's `a_ranged_unit_keeps_its_distance_from_something_that_has_to_close`
stages an adept thirty units from a ram and asserts the gap has **grown** by the
end. It holds on their fixture. Played through the real phase pipeline for sixty
ticks, with the orders phase rewriting stations underneath, it does not: the
adept ends **2.4** units from the ram and the sprite **17.0**, both inside its
reach of 18. `maintaining_range` fires — 14 of the sprite's 60 decisions — and
then loses to `engaging`.

Neither result is wrong about its own fixture. The divergence is what sixty ticks
do to a one-decision claim, and it is invisible from either end alone. Recorded
rather than asserted away in `tests/sim/ai/scenarios/test_ranged_spacing.py`,
which pins the invariants that do hold: range management is named in the trace, a
ranged unit hurts a melee unit before contact, and more reach buys more distance.

Worth a look before JQ-313 playtests, since a skirmisher dying in melee is the
kind of thing a player notices and a test does not.

## How to read these numbers, and how they were checked

Five methods notes, every one learned by getting something wrong first. The
umbrella over all of them:

> **A check that can only return "fine" is not a check.**

Each of the failures below was a step that could not express *"I did not
actually run"* — a render read by eye, a mutation that might not have landed, an
`all()` over a collection that might be empty, a field-by-field comparison where
a dropped field holds its default on both sides. All four reported success while
testing nothing, and in every case the fix was the same: make the step capable of
failing for the right reason.

They are cheap to follow and each of them hid a real defect for a while.

### A distribution without its run length is misleading

The reason mix is not one number, it is a number per run length. Measured on the
same code, `holding_station` is 73% of decisions over a full 90-second battle and
33% over the first 20 seconds, because a short slice is mostly the approach phase
and a full battle spends a long tail holding once the lines have met.

Neither figure is wrong and the two look like different games. JQ-329 and I
briefly thought we disagreed about the sim; we were measuring different windows.
They settled it by truncating their own runs and reproducing my distribution
within a few points. **So label the seed count and the simulated duration beside
any reason distribution**, here or anywhere else it is quoted.

### A render verified by eye cannot tell a formatter from a no-op

The screen-provenance line — `screening_inferred for south-t0-u2` — shipped once
as dead code. The helper existed, was correct, and was never called: a formatter
had reflowed the line the call was meant to replace, the edit silently matched
nothing, and the report read exactly as it had before. Every render in this
document had been checked by looking at it, which is precisely the check that
cannot catch a function nobody calls.

It surfaced as a contradiction rather than as a failure — the rendered output
showed no ally while the data said all 149 screens had one — and chasing that
rather than assuming the data was wrong is what found it. The tests that now
cover it were each confirmed to fail against the broken version before being
kept, which is the step that separates a test from a decoration.

This is the same lesson `CONVENTIONS.md` already records for scoring, from the
other direction: a single-tick assertion cannot tell a decision from an
oscillation, and a render verified by eye cannot tell a formatter from a no-op.
Both were caught by looking at **output over time** rather than asserting at a
point.

### A negative control has to prove it ran

The sharpest of the three, and the one the other two depend on. Breaking the code
on purpose to watch a test fail is the only evidence that the test can fail —
but **"I broke it and the test failed" and "I believe I broke it and the test
failed" look identical in a terminal**, and only the first is evidence.

This is not hypothetical. Twice in one session a patch script that edited source
by matching an anchor string silently matched nothing, because a formatter had
reflowed the line it was looking for. It printed its success message over a file
it had not touched. In one case that hid a helper nobody called; in the other it
made a green test look like proof that a fix worked.

So a negative control asserts that it landed before its result is read — the
anchor matched, the file changed, and by how much — and the restore asserts the
same in reverse. Three lines, and without them a mutation check is a ritual
rather than a measurement.

The same reasoning kills a subtler version, which is a test that asserts
something about nothing. `all(...)` over an empty sequence is true, and an empty
set differs from a populated one, so a test can pass both of its assertions while
the thing it describes has ceased to exist. **Assert the collection is non-empty
before asserting anything about its contents**, whenever "there is nothing here"
is one of the failures you are trying to catch.

All three notes above came out of one session of three agents merging each
other's branches. Each defect was invisible from the branch that contained it,
and every suite involved was green throughout.

### A check whose coverage is a function of the code it checks

The variant that grep cannot find, because nothing about it is wrong. It was
doing real work when written and quietly stopped, not because it changed but
because the arrangements it enumerates moved out from under it.

Anything that sweeps a set of situations and asserts over *whatever each one
produces* has this property. Tighten a gate upstream and some situations start
producing nothing; the assertions over them still pass, the test still reads as
covering the whole sweep, and the count of things actually checked is nowhere in
the output. JQ-329 found one of theirs down to three live cases out of ten, and
knew only because they printed the number instead of reasoning about it.

The instance here: `test_no_unit_attacks_a_target_that_had_already_died` sweeps
every record after the wisp dies and checks that none names it. The wisp dies on
tick 1, and for most of what follows the hunter is walking to its station naming
nobody — **40 hunter records, 1 before the death, and 2 of the remaining 39
naming any target at all.** "No record names the dead unit" was being satisfied
by thirty-seven records that named no unit whatsoever.

It is bracketed at both ends now: the hunter must have named the wisp *while it
lived*, and must still be naming somebody afterwards. Without the first the
absence proves nothing; without the second the sweep has stopped looking. Its
neighbour was worse and simpler — it closed on `chosen.kind in ("advance",
"attack", "cast", "hold")`, which lists every action kind there is.

**So count what a sweep actually examined, and assert the count.** Reasoning
about how many cases a fixture exercises is exactly the step that was wrong in
every instance above.

### An unwired seam is untested by construction

JQ-329's, and the only one here that is not a check which *cannot fail* — it is a
check that **never runs**. No amount of strengthening the assertion helps,
because the code path is not reachable from any fixture.

Three consumers on this branch are written against producers that have not
merged. `Decision.reason` arrives with JQ-329, so `_reason_of` returns empty for
every unit of every tick and the populated half of the reason render is dead. The
same was true of personality provenance until JQ-330 landed. A determinism suite
can spawn as many subprocesses as it likes and never once exercise those lines.

The failure mode is nastier than a normal gap: the break surfaces **on the day
the seam is wired**, in the producer's pull request, looking like a fault in
their work rather than a hole in the consumer's. JQ-329 found two dropped sorts
in their own package this way — set iteration reaching candidate order, which
they measured at eight distinct orders across eight fresh interpreters — sitting
behind a seam nothing populated yet.

**So a consumer built against an unlanded producer has to be tested against the
function rather than against a battle.** Hand-build the record, call the
renderer, assert on the string. It is less satisfying than an end-to-end run and
it is the only kind of test that can reach the code.

This is also the standing hazard of building three tickets in parallel against
each other's interfaces. It is genuinely efficient, and it silently removes a
whole path from every suite involved.

### The same seam, from the other side: a parameter with no caller

The nastier half of the variant above, because it looks wired from both ends. A
function grows an optional parameter so that consuming a not-yet-merged producer
will be a wire-up rather than a redesign — and nothing ever passes it. The
function is called. The parameter is optional, so nothing complains. There is a
test, it passes, and it reads exactly like coverage.

JQ-329 found one of theirs where a branch could not produce its first half from
any input at all; mutating it to a sentinel left 150 tests green. The instance
here was smaller and the same shape: `DecisionTrace.wants` was public and its
docstring said the decision phase asks first, so a narrowed trace would cost the
other units a comparison rather than a record. No such caller was ever written,
and it would have bought nothing if it had been, since `record` performs the same
check before building anything. The behaviour was covered; the **rationale** was
fiction, and a reader would have taken it for a description of the architecture.

Alongside it, the JSON renderer's dropped-count could have reported zero forever.
The text renderer had that test and the JSON did not — the same asymmetry as the
weights and the contributions, twice in one package, both found by mutation and
neither by reading.

**A parameter or a method justified by a caller that does not exist is a claim,
not a contract.** Either wire it or say plainly that it is not wired.

### Preconditions are not free, and neither is skipping them

Asserting a test's own preconditions is the fix for most of the shapes above, so
it is worth saying that it has its own failure modes in both directions.

**Too weak** is the vacuous case already covered: a precondition over a
collection that may be empty asserts nothing.

**Too strong is the one that bites while the fix is correct.** JQ-329's
oscillation test needed to establish that a unit had something to alternate
between. The obvious precondition — "it chose more than one distinct action" —
is sound reasoning and the wrong assertion, because *a unit that settles
correctly picks one thing for ever*. The precondition contradicted the behaviour
under test and failed on working code. What had to hold was that two moves were
**available**, which is a property of the candidate set rather than of the
outcome. Their second attempt then failed too, because a unit standing exactly on
its station generates no walk-to-station candidate, so the tension it needed does
not exist until the unit has stepped off.

The rule that survives: **a precondition belongs on the inputs, not on the
result.** Anything phrased over what the code decided is liable either to be
satisfied by the failure you are hunting or to forbid the success you want.

### And the one that catches the rest: come back to the tests you are not editing

The most common variant is the check nobody revisits. Every negative control in
this document was run on a test that was being written or changed at the time.
JQ-329 found their oscillation test — the one guarding the headline result of
their ticket — passed with the mechanism deleted, and found it only by running a
control on something they had shipped and moved past.

The determinism suite here was audited for exactly that reason and holds: with
the decision phase made to draw from the rng whenever a trace is attached,
eleven tests fail, `test_tracing_does_not_consume_randomness` among them. That
is the ticket's central claim, and it is guarded. It had never been checked
before it was checked.



## What the suite is actually worth

**"All tests pass" is a weak claim. "Each mechanism was removed and the suite
objected" is the strong one.** The first is a statement about the suite; the
second is a statement about the code. Fourteen vacuous or degraded assertions
found across three packages in one afternoon say the first is worth very little
on its own.

So every mechanism this ticket delivers was removed, one at a time, and the suite
asked whether it noticed:

| mutation | |
|---|---|
| decision phase never hands the recorder anything | caught |
| tracing consumes randomness | caught |
| record cap ignored | caught |
| unit filter ignored | caught |
| tick window ignored | caught |
| rivals no longer the best losers | caught |
| report omits factor contributions | caught |
| report hides that records were dropped | caught |
| JSON emits factors in reverse order | caught |
| weights no longer walk declared factor order | **survived — now caught** |
| *control: whitespace-only edit* | *survived, as it must* |

Two things make that table worth reading rather than merely reassuring, and both
are this document's own lessons turned on the harness that produced it.

**Every mutation asserts its anchor matched and reports its byte delta before the
run.** A mutation that silently fails to apply reports "caught" for free, which
is the formatter-reflow failure above, mechanised.

**The anchor guard earned itself, on the run where it mattered.** Auditing the
unwired seams below, a mutation aimed at the reason render printed `ANCHOR MISS`
and refused to report — the line was one f-string, not the two the patch had
guessed. Without the guard it would have printed `caught`, and a gap that was
genuinely open would have been closed in the notes while staying open in the
code. The failure it prevented was the plausible-looking answer, on the single
run where the wrong answer would have been believed.

**The control mutation must survive.** Ten-for-ten is exactly the result that
should make a reader suspect the harness rather than trust it — a harness broken
toward always-reporting-caught looks identical to a well-tested package. A
whitespace-only edit survives, so the other ten results mean what they say.

The one survivor was real. `_weights_of` could walk the factors in reverse and
nothing objected: the determinism tests compare runs of the same code, so a
consistently *wrong* order is still consistent, and the contributions had an
order test while the weights did not. Writing it exposed a second thing — the
recorder tests attach no behavior, so their records carry no weights at all, and
the obvious placement would have asserted against an empty tuple. It lives with
the scenarios instead, where weights exist.
