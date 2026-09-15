"""The per-tick phase order — declared here and nowhere else.

The loop walks this list. A later slice adds its phase to the list rather than
threading logic through `step_battle`, which is what keeps three parallel slices
out of the same function.

Where the remaining slices slot in:

===========  =====  ==================
Phase        Slice  Sits
===========  =====  ==================
`orders`     B
`decision`   JQ-328 after orders
`movement`   A
`energy`     C      before combat
`abilities`  C      before combat
`combat`     A
`scoring`    B
`resummon`   D      before removal
`removal`    A      last
===========  =====  ==================

`orders` runs first: every unit's assigned station is fresh before anything has
moved, which is the point a behaviour layer wants to make its decisions at.

`scoring` runs after combat and before removal, so a zone taken by killing its
last defender flips on the tick that defender falls.

`removal` stays last: a unit brought to zero must not act again, and every phase
that wants to see the dead — the troop-bond dissolve above all — has to run
before they are swept.
"""

from __future__ import annotations

from app.sim.phase import TickPhase
from app.sim.phases.combat import combat_phase
from app.sim.phases.movement import movement_phase
from app.sim.phases.orders import orders_phase
from app.sim.phases.removal import removal_phase
from app.sim.phases.scoring import scoring_phase

TICK_PHASES: tuple[TickPhase, ...] = (
    orders_phase,
    movement_phase,
    combat_phase,
    scoring_phase,
    removal_phase,
)

__all__ = ["TICK_PHASES", "TickPhase"]
