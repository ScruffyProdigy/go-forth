"""The per-tick phase order — declared here and nowhere else.

The loop walks this list. A later slice adds its phase to the list rather than
threading logic through `step_battle`, which is what keeps three parallel slices
out of the same function.

Where the remaining slices slot in:

===========  =====  ===============
Phase        Slice  Sits
===========  =====  ===============
`orders`     B      before movement
`movement`   A
`energy`     C      before combat
`abilities`  C      before combat
`combat`     A
`scoring`    B      after combat
`resummon`   D
`removal`    A      last
===========  =====  ===============

`removal` stays last: a unit brought to zero must not act again, and every phase
that wants to see the dead has to run before they are swept.

`resummon` sits just before it, and the gap of one tick between the two is the
point. A summon defeated this tick becomes a dispelled slot during `removal`,
so the earliest any mage can begin rebuilding it is the tick after — a unit
never pops back on the same tick it fell. The troop-bond dissolve (§4.6) lives
inside `removal` rather than in a phase of its own for the same reason: it is
the moment a troop learns it has lost its last mage.

Those two constraints — `removal` last, `resummon` immediately before it — leave
`scoring` (slice B) with only one place to go, after `combat` and before
`resummon`. That is not a convention anyone picked, and it has a rule attached
that is easier to read here than to rediscover as a bug report: **a unit
resummoned on tick T does not hold ground on tick T**, because scoring has
already run by the time it appears. It is the mirror of the rule above, and
deliberately so — a summon leaves the field a tick before it can come back, and
earns nothing on the tick it returns.
"""

from __future__ import annotations

from app.sim.phase import TickPhase
from app.sim.phases.combat import combat_phase
from app.sim.phases.movement import movement_phase
from app.sim.phases.removal import removal_phase
from app.sim.phases.resummon import resummon_phase

TICK_PHASES: tuple[TickPhase, ...] = (movement_phase, combat_phase, resummon_phase, removal_phase)

__all__ = ["TICK_PHASES", "TickPhase"]
