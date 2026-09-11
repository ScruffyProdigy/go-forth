# Plan-phase screen — design (JQ-293)

Ticket: [JQ-293](https://linear.app/joinquest/issue/JQ-293)
Design doc: §3.2 (plan phase), §4.3 (mage cap), §4.6–4.8 (bond, energy, spells),
§4.12 (map), §10 #31 #32 #36 (open decisions). Plates: JQ-243.

## Why this shape

Planning is roughly half the gameplay (decided 2026-09-11, along with dropping
the 30 s cap). §3.2 specs the phase as three pre-filled steps with no hard
timer, but it exists only as doc text — this is the screen that phase needs.

The build holds onto two framing points from that conversation:

* **A mage arrives with the summons it supports.** Picking a mage *is* picking a
  troop shape. "Choose mages" and "build troops" were decomposed by data model
  rather than by decision. Entourage customisation is a drill-down on a troop
  already chosen, never a prerequisite for choosing it.
* **The phase is the game's growth surface.** The step list is expected to grow.
  The bar for admitting a step: pre-fillable, acceptable in a single tap, and
  meaningful enough that someone opens it by round three.

## Constraint this lands under

The game does not exist yet. `api/` is `/healthz`; `client/` is a placeholder.
The plan→sim contract is explicitly still moving: orders, formations and
deployment placement are JQ-287, spell selection is JQ-297, and the JQ-286 agent
confirmed its slice defines neither.

So the screen is **fixture-driven**: real components, real reducer, real tests,
reading a typed local fixture behind a narrow seam. When JQ-287/JQ-297 land,
`fixtures/` is what gets replaced — not the screen.

## Decisions this settles

| Ref | Decision |
|---|---|
| §10 #31 | Troops precede spells (already settled). **On-screen: wizard, one step per screen, entered from a round hub.** |
| §10 #32 | **Both spell slots re-picked each round**, previous retained when still eligible, a slot flagged `NEEDS REPLACEMENT` when a troop edit invalidated it. Not the ticket's provisional anchor+flex — an anchor slot puts a match-long choice in round 1, which §3.2 rules out for the opener. |
| §10 #36 | **Playtest at one round** until the loop is liked, then **best 3 of 5**. Battle stays 60–90 s pending playtest data. |

**#36 has a consequence outside this screen.** Best 3 of 5 is a different win
model from §3.2's cumulative zone score across 5–7 rounds, and it interacts with
the zone-score target (§10 #7) and the mage-cap curve (§10 #40, which says cap
and match length must be decided together). Flagged, not resolved here.

For the screen it means one thing: **round count and mage cap come from the
fixture, never hardcoded.** A one-round playtest and a best-of-5 match are the
same screen with different numbers.

## The wizard/one-tap tension, resolved

"A no-change round is one tap to lock in" and "one step per screen" cannot both
be true — three steps is three Nexts. Resolution: a **round hub** in front of the
wizard.

* **Hub** — the board-position map with **resonance as the headline number**,
  the three steps as one-line summaries of their pre-filled state, and Lock In.
  A no-change round is one tap, from the screen that shows the whole plan.
* **Steps** — entered by tapping a row, each full-screen with Back/Next; Next off
  the last returns to the hub. The wizard is for deciding, not for confirming.

## Fold depth (three-valued, not two)

Per §3.2, a control appears when the decision it serves first exists:

* **absent** — the decision genuinely doesn't exist yet (no fielded mage grants a
  spell; only one troop, so orders carry no choice)
* **collapsed to one line** — it has a good default
* **expanded** — only on tap

Nothing a returning player would want is hidden. Absence is derived state, not a
tutorial flag.

## Modules

Each is independently testable; the pure ones have no React import.

| Module | Responsibility |
|---|---|
| `plan/types.ts` | `PlanState`, `Troop`, `MageOption`, `SpellOption`, `Order`, `ZoneId` |
| `plan/fixtures/` | A round-N `PlanState`. **The only thing JQ-287/JQ-297 replace.** |
| `plan/planReducer.ts` | Pure. Every edit is an action; its output is the future server payload |
| `plan/derive.ts` | Pure. Resonance, support capacity, spell eligibility, board placement, fold state |
| `plan/PlanScreen.tsx` | Step routing: `summary │ troops │ spells │ orders` + `troop-detail` |
| `plan/PlanMap.tsx` | One SVG at JQ-243 geometry; troops placed in the deployment strip by order |
| `plan/steps/*.tsx` | One component per step |

Splitting the reducer and derivations out is what lets the interesting rules —
the resonance curve, capacity, eligibility, fold state — be tested without
rendering anything, and it is the seam the server work plugs into later.

## The three steps

1. **Choose troops.** Each card is a mage *with its default entourage* (summon
   pips). Tap to field against the mage cap. The header carries live resonance
   and support capacity filling, with unsupported capacity called out. The
   entourage row opens the drill-down, pre-filled from last round (round 1: the
   Starter's suggested lineup).
2. **Choose spells.** Two slots, both re-picked, sticky. The menu is signature
   spells from fielded mages + eligible independents + basic fallbacks.
   Ineligible entries stay **visible and greyed with the reason** ("needs a
   fielded Evocation mage") — that is where JQ-292's gating shows up, and it
   teaches the mage→spell link without a tutorial.
3. **Give orders.** One row per troop; order by tap (Hold A/B/C, Defend base,
   Push enemy base). Changing an order moves that troop on the map immediately.

## Map

One SVG at the plate geometry: 375×667 floor, three zone bands, two bases,
a deployment strip per side. Troops are placed by their order, and read as a
mage (larger, haloed) with summon pips — the JQ-243 sizes, ~1.8× ratio.

This is deliberately **not** shared with JQ-294's battle renderer. The two draw
the same map in different states, and abstracting across them before JQ-294
exists would be guessing. Flagged in the PR as an extraction point.

## No hard timer

No countdown is rendered anywhere — asserted by a test, because a countdown is
the kind of thing that gets added back by reflex. Lock In moves to a `waiting`
state that shows **troops taking position** (the board animating to this round's
deployment) rather than an idle spinner. The backstop that stops a stalled match
is a constant, not a displayed number.

## Testing

vitest + RTL, already in the repo.

* Pure: resonance curve (1 weak → 4+ strong), support capacity and unsupported
  remainder, spell eligibility and invalidation flagging, fold state per step.
* Screen: a no-change round is **literally one tap** (render hub → click Lock In
  → locked plan equals the pre-fill); step absent vs. collapsed vs. expanded;
  a troop edit invalidating a spell slot flags it; no countdown is rendered.

## Out of scope

Battle rendering and the in-battle HUD (JQ-190, JQ-294); designing the spells
themselves (JQ-292); the server contract (JQ-287, JQ-297); anything reading
runtime config (JQ-285 — when session endpoints land they should read that
ticket's `window.__CONFIG__` global, not `import.meta.env`).

## Open, carried forward

* Does the plan phase show the opponent's last-known state? **Assumed yes** —
  last round's end state, greyed, since the player already saw it. No live info.
* Does "feels like 30 seconds" survive 90 seconds of wall clock? Playtest
  question — JQ-191.
