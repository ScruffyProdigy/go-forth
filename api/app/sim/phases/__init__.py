"""The per-tick phase order — declared here and nowhere else.

The loop walks this list. A later slice adds its phase to the list rather than
threading logic through `step_battle`, which is what keeps four parallel slices
out of the same function.

Where the slices slot in:

============  ======  ========================
Phase         Ticket  Sits
============  ======  ========================
`orders`      JQ-287  first
`decision`    JQ-328  after orders
`movement`    JQ-286
`energy`      JQ-288  before abilities
`spells`      JQ-288  before abilities
`abilities`   JQ-288  before combat
`combat`      JQ-286
`statuses`    JQ-288  immediately after combat
`scoring`     JQ-287  after statuses
`resummon`    JQ-289  before removal
`removal`     JQ-286  last
============  ======  ========================

`orders` runs first: every unit's assigned station is fresh before anything has
moved, which is the point a behaviour layer wants to make its decisions at.

`energy` runs before `abilities` and both before `combat`, so a gauge is
charged, then spent, then the weapons swing. That puts a one-tick lag between
dealing damage and being paid energy for it — see `phases/energy.py`.

`spells` lands before `abilities` because an injected spell is an outside
event: it happens *to* the tick, and the units then act on the field it left.

`statuses` sits immediately after `combat`, ahead of `scoring`. Burn and
burning-ground damage is damage, so it has to land before anything else reads
the field: a unit a burn finishes should stop holding ground on the same tick
a weapon kill would. Deferring it past `scoring` would make how long a corpse
keeps earning depend on which of the two killed it, which is not a thing a
designer could explain or tune.

`scoring` runs after combat and before removal, so a zone taken by killing its
last defender flips on the tick that defender falls.

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
from app.sim.phases.abilities import abilities_phase
from app.sim.phases.combat import combat_phase
from app.sim.phases.energy import energy_phase
from app.sim.phases.movement import movement_phase
from app.sim.phases.orders import orders_phase
from app.sim.phases.removal import removal_phase
from app.sim.phases.resummon import resummon_phase
from app.sim.phases.scoring import scoring_phase
from app.sim.phases.spells import spells_phase
from app.sim.phases.statuses import statuses_phase

TICK_PHASES: tuple[TickPhase, ...] = (
    orders_phase,
    movement_phase,
    energy_phase,
    spells_phase,
    abilities_phase,
    combat_phase,
    statuses_phase,
    scoring_phase,
    resummon_phase,
    removal_phase,
)

__all__ = ["TICK_PHASES", "TickPhase"]
