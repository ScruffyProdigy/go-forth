# Lanes and hotspots — design (JQ-376)

Ticket: [JQ-376](https://linear.app/joinquest/issue/JQ-376)
Supersedes part of [JQ-287](https://linear.app/joinquest/issue/JQ-287).
Design doc: §4.12 (map), §6 (battle phase), §4.3 (mage cap), §4.6 (troop bond).

## The flaw this fixes

The three stacked zone bands had a dominant strategy, and it was "never fight".

A band adjacent to your own deployment strip is uncontested by default — the
enemy has to cross the whole map to reach it — so it is free income. Free income
that both players collect symmetrically cancels out and decides nothing, and the
only band either side can actually contest pays nobody while it is contested.

Measured on the placeholder armies at seed 7, before the change:

| Orders | north | south | margin |
|---|---|---|---|
| Mirror (A/B/push vs C/B/push) | 1795 | 1795 | **0** |
| North commits all three troops to B | 162 | 1795 | **−1633** |
| South turtles at home | 3534 | 1395 | +2139 |
| Both sides fight only in B | 214 | 305 | −91 |

Row 2 is the indictment: contesting the middle lost by 1633. Row 4 is the
mechanism: when both sides genuinely fight for the same ground, nobody is paid at
all.

The geometry also made the orders asymmetric. Bands stacked along the attack axis
meant "Hold A" was *turtle* to one player and *deep strike* to the other — the
same word, opposite risk, decided by which end you happened to start at. That is
hard to teach in a three-tap plan phase.

## The shape

**Zones become lanes, divided west to east.** Two of them, running the depth
between the deployment strips, with a push corridor up the middle.

```
┌───────────────────────────┐
│       ENEMY BASE ▲        │   y = 20
├───────────────────────────┤
│    enemy deployment       │   40 – 100
├───────────┐   ┌───────────┤
│           │   │           │
│   ┌───┐   │   │   ┌───┐   │   lanes: y 100 – 469
│   │ W │   │   │   │ E │   │   W: x 0 – 160
│   └───┘   │   │   └───┘   │   E: x 215 – 375
│           │   │           │   hotspots: 60 × 60 at each lane's centre
├───────────┘   └───────────┤
│     your deployment       │   469 – 529
├───────────────────────────┤
│        YOUR BASE ▼        │   y = 549
└───────────────────────────┘
```

Both lane centres sit at y = 284.5 — exactly half way between the bases — so
neither lane is nearer to either player. There is no free farm left to collect.

**Scoring sits on a hotspot, not on the lane.** A lane is 160 × 369. If standing
anywhere in it counted, one survivor in a corner would deny the whole thing and
row 4 above would simply relocate. The hotspot is a 60 × 60 square at the lane's
centre — under a tenth of the lane's area, in the middle of the map, where the
fighting is.

**Only a mage holds it.** The mage is the slowest and most fragile unit in a
troop, and the one whose death dissolves it (§4.6). Requiring it on the point
means scoring costs real exposure, and it kills the degenerate line where a fast
disposable summon is sent to sit on the objective while the troop that matters
stays safe.

**Hold therefore anchors the formation on the mage rank.** Under Hold, the mage's
station *is* the hotspot and the summons form up past it; under Defend and Push
the formation is still built around the summon line. Getting into scoring
position and winning the ground in front of it become the same act.

**Two lanes, not three.** This is a decision about the plan rather than about the
map. You open at three mages (§4.3). Three troops into three lanes has an obvious
neutral answer — one each — and a flat decision. Three into two forces you to
double up somewhere and your opponent to guess where, and it keeps working as the
cap grows. Two lanes also give each one 160px rather than 106px, which is the
difference between a troop reading as a formation and reading as a queue (JQ-243
measured ~24px per column).

**Deployment bands are derived from the order too.** A troop told to hold West
starts in the part of the strip in front of the west lane, so it walks straight up
its own lane instead of setting off diagonally. Troops sharing an order share that
band side by side. This is what the JQ-287 acceptance criterion "starting on its
zone's side of the deployment strip" was reaching for — it only became
geometrically meaningful once lanes ran west to east.

## What it does to the numbers

Same armies, same seed, after the change:

Measured on merged `main` — so with JQ-289's resummoning in play, which is the
run that tests the claim rather than restating it. Mean over five seeds:

| Orders | north | south | margin |
|---|---|---|---|
| Mirror: both split W/E/push | 1162 | 977 | +185 |
| North doubles W, south splits | 1308 | 1332 | −24 |
| **North turtles at home** | **0** | **3308** | **−3308** |
| North contests both, south all-in W | 1652 | 1650 | +2 |
| Nobody holds anything (all push) | 0 | 0 | 0 |

Turtling went from winning by 2139 to losing by 3308. Contested plans produce
close, decided games rather than guaranteed ties. And a round where neither side
commits a mage to a point scores nothing for anybody, which is the rule stated
plainly.

Resummoning was the open risk: a cleared lane no longer stays cleared, because
surviving mages rebuild their screen on a timer, so the scoring window could in
principle have closed far enough that contesting stopped paying. It did not.
Turtling loses by the same 3308 on every seed, contested plans still land 24 and 2
points apart, and the mirror — which scored 270 to nil before rebuilding existed —
now has both sides earning, because a side that loses a point can take it back.
That is the shape you want: the rule survives the mechanic that was most likely to
undermine it.

**Those numbers are integration evidence, not the proof.** "Keeping your mages at
home earns nothing" is a consequence of two smaller rules that are each tested on
their own: a Defend station is clamped into its own deployment strip, and the map
validator rejects a strip that overlaps a zone. Together they make it a property
of the geometry rather than something a particular battle happened to produce.
The whole-battle tests in `test_lane_strategy.py` sit on top of that as evidence
the composition behaves as intended.

Checked by breaking each new guard and watching it fail before restoring it. Four
went red as they should; a fifth — moving Defend's objective onto a hotspot — left
every test green, and the probe turned out to be the thing at fault rather than
the tests: the station clamp makes that mutation behaviourally inert. Removing
the clamp is the mutation that has teeth, and it does go red.

## No walls

Lanes are regions, not corridors: nothing blocks movement between them. Lane
commitment already comes from the order — a troop told to hold West walks to West
and stays there — and terrain that blocked movement would mean pathfinding, which
the sim does not have and should not grow for this.

## What stays

Orders themselves, derived formations, the engagement standoff, base destruction,
carried base HP and the event envelope are all unchanged. `ZoneConfig` and
`zone_id` keep their names: the rendering contract is already in use by JQ-294 and
the behaviour layer by JQ-328, and renaming the type to "lane" is churn for no
gain.

## Known consequences, not yet resolved

**A mage will die on a hotspot.** The behaviour layer (JQ-328) has no retreat
verb — advance, attack and hold are the three it owns, and retreat is JQ-329's —
so a mage standing on a point under fire cannot choose to leave. Requiring the
mage to score therefore guarantees this failure mode rather than merely risking
it.

**It stacks with the troop bond rather than trading off against it.** Under slice
D (JQ-289) losing that mage loses the hotspot *and* every summon it was
sustaining, in the same tick, and a troop that loses its last mage has nothing
left to rebuild with. A single focused kill can swing a lane completely.

That may be the intended tension — committing a mage should be a real bet — but
it is a balance question for JQ-307 and a playtest, not something to soften
pre-emptively here.

**Clearing a lane is temporary by construction, and the scoring window is a
tuning number nobody has set yet.** A mage stops at its own weapon range of any
living enemy — 90 for an Ember Adept, against a 60-wide hotspot — so it cannot
walk onto a contested point at all. Scoring requires the lane to be *cleared*,
which is the intent. But under slice D the opponent's surviving mages rebuild
their dispelled summons at their own positions on a timer, so the window between
clearing a lane and a fresh body arriving within 90 of your mage is set by
`resummon_pace_seconds`. Whether a hotspot is ever held long enough to matter
turns on that one number. Raised by the JQ-289 agent while this was still being
written; it belongs next to the mage-death interaction above, because it is the
other half of the same mechanism.

A corollary worth recording before someone tries to tune around it: **this is
structural, not a threshold.** An Ember Adept's range is 90 and a hotspot is 60
across, so a mage halts further out than the entire width of the square it is
trying to enter — it must get 30 *past* the centre while stopping 90 short of the
nearest enemy. No hotspot smaller than roughly twice a mage's range can be entered
while an enemy lives, so enlarging the square does not soften the rule, it only
changes which lane geometry is legal.

**A true mirror is not a draw.** Identical armies under identical orders score
1162 to 977, a margin of about 3.5%. It has shrunk twice — 1340 to nil before
JQ-287's off-axis movement fix, 270 to nil before resummoning existed — and most
of what first looked like first-actor advantage turned out to be units frozen
outside their own weapon range. What is left is real though: damage resolves in
unit-list order, and a two-player game should not decide a mirror on list order
at all. Small enough to be a follow-up rather than a blocker; not small enough to
leave unrecorded.
