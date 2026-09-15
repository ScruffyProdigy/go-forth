"""The per-tick phase order — declared here and nowhere else.

The loop walks this list. A later slice adds its phase to the list rather than
threading logic through `step_battle`, which is what keeps three parallel slices
out of the same function.

Where the remaining slices slot in:

===========  =====  ===============
Phase        Slice  Sits
===========  =====  ===============
`orders`     B      before movement
`decision`   328    after orders
`movement`   A
`energy`     C      before combat
`abilities`  C      before combat
`combat`     A
`scoring`    B      after combat
`resummon`   D      before removal
`removal`    A      last
===========  =====  ===============

`removal` stays last: a unit brought to zero must not act again, and every phase
that wants to see the dead — the troop-bond dissolve above all — has to run
before they are swept.
"""

from __future__ import annotations

from app.sim.phase import TickPhase
from app.sim.phases.combat import combat_phase
from app.sim.phases.decision import decision_phase
from app.sim.phases.movement import movement_phase
from app.sim.phases.removal import removal_phase

TICK_PHASES: tuple[TickPhase, ...] = (decision_phase, movement_phase, combat_phase, removal_phase)

__all__ = ["TICK_PHASES", "TickPhase"]
