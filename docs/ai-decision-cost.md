# AI decision cost, and what the inspector found

Two things the JQ-331 acceptance asks to be written down rather than asserted:
what the decision loop costs at opening-demo density, and what watching it
through the inspector actually turned up. Both are **provisional** — the numbers
are one machine's, and the findings are against JQ-328's loop before JQ-329 and
JQ-330 land.

Reproduce the measurement with:

```bash
python -m app.scripts.decision_report --cost
```

## Measured cost

Recorded 2026-09-15, on the default two-lane map and the placeholder roster.

| | |
|---|---|
| Machine | macOS 14.7.6, x86_64 |
| Python | 3.12.14 |
| Map / seed | `two-lane` / 20260911 |
| Units at open | 18 |
| Battle length | 1457 ticks at 20/s |
| Tick budget | 50.0 ms |

| | |
|---|---|
| Decisions traced | 17,924 |
| Candidates per decision | min 2, mean 2.4, max 9 |
| Whole battle, untraced | 11,147 ms |
| Whole battle, traced | 14,477 ms |
| **Per tick, untraced** | **7.65 ms — 15.3% of budget** |
| Per tick, traced | 9.94 ms |
| **Headroom** | **42.35 ms/tick** |

Two things worth saying plainly about these numbers.

**The whole battle is timed, not the decision phase alone.** Movement, combat,
abilities, energy and the per-tick world deep-copy are all inside the 7.65 ms.
That makes the headroom figure the real one rather than a flattering slice, and
it means the decision loop's own share is *smaller* than the number shown.

**Tracing costs about 2.3 ms/tick, and nobody pays it in a match.** Tracing is
off unless a developer asks for it; a battle with no trace pays one `is None`
check per unit per tick.

The candidate counts are the number to watch as JQ-329 adds positional
candidates and JQ-330 adds coordination. A mean of 2.4 says the loop is
currently choosing between "walk at my post", "walk at that enemy" and "hit the
thing in reach" — there is a great deal of room under the budget, and the
ceiling asserted in `tests/sim/ai/test_inspect_cost.py` is 40.

## What the inspector found

These came out of reading actual reports, and are recorded for JQ-313's
playtests. **None of them is fixed here** — JQ-331 is the tool, and each of
these belongs to the ticket that owns the behavior.

### 1. `danger` is inert at the opening-demo roster (JQ-329 owns this) — **fixed, in review**

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

### 2. Aggressive creatures saturate the danger weight floor — **half-fixed, in review**

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

### 3. `hold` and `advance` on the station tie more often than expected — **fixed, in review**

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
units visibly do. Measured over a 20-second battle on seed 20260911, as the
share of each type's decisions:

| Profile | advance→enemy | advance→station | attack | hold |
|---|---|---|---|---|
| `cinder-hound` | 35% | 7% | **24%** | 35% |
| `ember-adept` | 48% | 20% | 4% | 28% |
| `ember-sprite` | 50% | 10% | 6% | 35% |
| `ash-ram` | 18% | 12% | 0% | **70%** |

Against what the profiles claim:

| Profile | Description says | Verdict |
|---|---|---|
| `cinder-hound` | fast, short-ranged, so it closes | **matches.** Highest attack share of any type by a factor of four, and it closes rather than holding station. |
| `ash-ram` | slow and tough, walks at the objective | **matches, for a non-obvious reason.** The 70% hold looks wrong until you read a record: by tick 118 it has *arrived*, and its only other candidate walks it backwards (advance→enemy scoring −0.515 against hold's +0.078, because that enemy is away from the objective). It walks at the objective and then stands on it. The "ignores what shoots at it" half is untestable while (1) stands. |
| `ember-sprite` | has reach and keeps it | **cannot be confirmed.** Keeping range is JQ-329's behavior and does not exist yet; today the sprite closes like everything else (50% advance→enemy). |
| `ember-adept` | wary | **does not match.** A wary mage closes on enemies in 48% of its decisions — more often than the aggressive hound does. This is finding (1) seen from the other end: `wary` buys danger weight 2.5, and 2.5 × 0.00 is 0.00, so the trait that defines this profile currently changes nothing about what it does. |

One confirmed outright, one confirmed once the report explains it, one blocked on
JQ-329, and one genuine mismatch that is a symptom of (1) rather than a separate
problem. Re-run this table once JQ-329 and JQ-330 land — it is the cheapest check
that the authored descriptions still describe the thing.

**Status — re-measured against JQ-329's branch while it was in review.** Both
outstanding rows resolve, and the whole table should be regenerated here on merge:

| Profile | then | now | |
|---|---|---|---|
| `ember-adept` (*wary*) | 48% advance→enemy | **11%**, 62% advance→station | mismatch gone |
| `cinder-hound` (*aggressive*) | 24% attack | **40%** | still the type that fights most |
| `ember-sprite` (*keeps reach*) | unconfirmable | **11% attack**, 1% retreat | confirmed |

The wary mage used to close on enemies *more often than the aggressive hound*,
which was the sharpest single symptom of (1). It now closes less than the hound,
which is the ordering the descriptions claim.

One caution carried over from that re-run, because it nearly went into this
document as a fact: an earlier measurement showed the sprite retreating 5% of the
time and that was cited as confirming "keeps its reach". It was partly an
artifact — the gate was on useful range rather than on weapon reach, leaving a
band where a ranged unit could already shoot and was still offered a step, so
some of that 5% was fidgeting rather than spacing. With the gate on reach it
falls to 1% while attacks nearly triple. **A row marked confirmed on evidence
that is partly an artifact is worse than one marked unconfirmable.**

Reproduce the table with:

```bash
python -m app.scripts.decision_report --json --seconds 20
```


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

