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

### 1. `danger` is inert at the opening-demo roster (JQ-329 owns this)

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

### 2. Aggressive creatures saturate the danger weight floor

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

### 3. `hold` and `advance` on the station tie more often than expected

With danger inert and ally support saturated, a unit already at its post often
scores `hold` and `advance`-on-station within a rounding error of each other, and
the tie is broken by declared candidate order rather than by anything meaningful.
It is reproducible and harmless today. It is the kind of thing that becomes
visible as jitter once units have somewhere more interesting to be, so it is
worth a second look during JQ-329's positioning work.

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

Reproduce the table with:

```bash
python -m app.scripts.decision_report --json --seconds 20
```
