"""Step one of the loop: what this unit can see, gathered once.

Every candidate is scored against the same observation, so the gathering happens
once per unit per tick rather than once per candidate — and, more importantly,
every factor is then judged against an identical picture of the field. A danger
score computed from a field that had already shifted would not be comparable
with the objective score computed before it.

Nothing here imports from `app.sim.phases`, which is why the liveness test is
spelled out rather than borrowed from `targeting.py`: importing that module pulls
in the whole phases package, the decision phase with it, and the decision phase
imports its way back to here. One inlined comparison is cheaper than a lazy
import, and this is the only place in `ai/` that wants one.

Lists come out sorted by unit id. They are built by filtering `world.units`,
which is already deterministic, but sorting makes the guarantee local: nothing
downstream has to know how the world orders its units to stay reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.capabilities import Capabilities, capabilities_of
from app.sim.ai.objective import Objective, objective_for
from app.sim.map import MapConfig
from app.sim.world import Unit, World


@dataclass(frozen=True)
class Observation:
    """One unit's view of the field, this tick."""

    unit: Unit
    capabilities: Capabilities
    objective: Objective
    #: Living enemies, sorted by id.
    enemies: tuple[Unit, ...]
    #: Living allies excluding this unit, sorted by id.
    allies: tuple[Unit, ...]
    #: How far this unit could move this tick. Zero for something rooted.
    step: float
    map_config: MapConfig


def observe(
    world: World,
    unit: Unit,
    map_config: MapConfig,
    seconds_per_tick: float,
) -> Observation:
    capabilities = capabilities_of(unit)

    return Observation(
        unit=unit,
        capabilities=capabilities,
        objective=objective_for(world, unit),
        enemies=tuple(
            sorted((u for u in world.units if u.hp > 0 and u.side != unit.side), key=lambda u: u.id)
        ),
        allies=tuple(
            sorted(
                (u for u in world.units if u.hp > 0 and u.side == unit.side and u.id != unit.id),
                key=lambda u: u.id,
            )
        ),
        step=capabilities.speed * seconds_per_tick,
        map_config=map_config,
    )
