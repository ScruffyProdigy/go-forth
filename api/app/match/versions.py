"""What a recorded run was played under.

A run record (`run_record.py`) is only reproducible against the rules and the
content it was played on. Both change — that is what the milestone is for — so
the record carries the versions rather than assuming whatever is checked out
today. A replay that finds a version it does not recognise says so, instead of
producing a different battle and calling it the same run.

Two numbers rather than one, because they move for different reasons and a
single "game version" would force a bump on every change to either:

* **`RULES_VERSION`** — how a round is decided. The phase machine, the ending
  precedence, energy accrual and spend, what a cast costs in ticks, the
  backstop. Anything that would make the same plans and the same casts resolve
  differently.
* **`CONTENT_VERSION`** — what is on the field. `fixtures.py`'s roster, the
  spell catalogue, the map. Anything that would make the same *ids* mean
  something else.

**Bump one when a replay of an existing record would diverge.** Not when a
comment changes, not when a payload gains a field — when the battle would come
out differently. The test that catches a missed bump is the reproduction test in
`tests/match/test_run_record.py`: it replays a record captured from a live
session, so a rules change that forgets to bump fails there rather than in a
diagnostic six weeks later.

`wire.WIRE_VERSION` is deliberately not one of these. It versions what crosses a
socket, which a replay never reads.
"""

from __future__ import annotations

#: JQ-308's round rules, plus JQ-310's server-assigned cast tick and order.
RULES_VERSION = 1

#: `match/fixtures.py` and the two-lane map as JQ-376 left them.
CONTENT_VERSION = 1
