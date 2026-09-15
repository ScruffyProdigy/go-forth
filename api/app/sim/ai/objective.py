"""Reading the order/objective contract JQ-287 owns, without owning any of it.

JQ-287 defines orders, derives each unit's station from its troop's order, and
restricts base attacks to troops pushing the enemy base. This ticket consumes
that; it does not get a vote in it. So everything here is read-only, and the two
facts it reads are deliberately the narrowest pair that makes a decision:

* **where this unit is supposed to be standing** — its station, which the orders
  phase writes to `unit.destination` every tick, before this one runs. Because
  it is rewritten every tick, a diversion the decision loop commits to is undone
  by default on the next tick: "go back to your post" costs nothing to implement.
* **whether this unit may take the enemy base as an objective** — true only for
  a troop ordered to push it.

Both come from JQ-287's own functions rather than from anything reconstructed
here. An earlier version of this module read the order structurally, through a
`getattr` and a string compare, because slice B had not landed and importing a
module that does not exist would have broken the purity test's import walk. That
is gone: the contract is real now, so it is called rather than imitated.

Base *damage* is JQ-287's. `may_attack_base` gates only whether the enemy base is
allowed to be a destination worth scoring.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.map import MapConfig
from app.sim.orders import may_attack_base
from app.sim.types import Vec2, opposing
from app.sim.world import Unit, World, order_of


@dataclass(frozen=True)
class Objective:
    """The two objective facts a decision needs."""

    #: Where this unit is supposed to be standing, this tick.
    station: Vec2
    #: Whether the enemy base is a legal objective for this unit's troop.
    may_attack_base: bool


def enemy_base_position(map_config: MapConfig, unit: Unit) -> Vec2:
    return map_config.bases[opposing(unit.side)].position


def objective_for(world: World, unit: Unit) -> Objective:
    """This unit's station and base permission, both straight from JQ-287."""
    return Objective(
        station=unit.destination,
        may_attack_base=may_attack_base(order_of(world, unit)),
    )
