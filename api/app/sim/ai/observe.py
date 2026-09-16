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

from app.sim.abilities import Ability, AbilityCatalog
from app.sim.ai.capabilities import Capabilities, capabilities_of
from app.sim.ai.intent import Assignment, Commitment, Intent
from app.sim.ai.objective import Objective, objective_for
from app.sim.map import MapConfig
from app.sim.types import UnitId
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
    #: How far this unit could move this tick, at full speed. An intent that
    #: walks slower scales this; see `intent.movement_scale`.
    step: float
    #: This unit's ability, resolved from the catalog, or None if it has none.
    #: Whether the gauge is full enough to spend it is read off the unit.
    ability: Ability | None
    map_config: MapConfig
    #: `world.tick`. Bounded pursuit needs to know how long it has been chasing,
    #: and a decision may not read a clock — see `CONVENTIONS.md` on determinism.
    tick: int = 0
    #: The tick length, so a bound written in seconds can be compared against a
    #: span measured in ticks without either end having to know the tick rate.
    seconds_per_tick: float = 0.0
    #: What this unit's troop has asked it to answer, if anything (JQ-330).
    #: A suggestion carried into scoring as the `assigned` context, never an
    #: instruction: the unit still weighs it against everything else it could do.
    #:
    #: JQ-329 reads the same record for positioning, through the two properties
    #: below. It was originally two fields of its own — a tuple of nominated
    #: target ids and a protected ally — built before this type existed; they
    #: collapsed into this one on merge, which is what both halves had agreed.
    assignment: Assignment | None = None
    #: The chase this unit is already running, if any. Read from `unit.ai`.
    commitment: Commitment | None = None
    #: Ticks left before this unit may be drawn off its post again. Above zero
    #: only just after a chase ended on one of its bounds; see `ai/pursuit.py`.
    recovery_remaining: int = 0
    #: What this unit committed to last tick, if anything. Read so that a
    #: decision can prefer to carry on doing what it was doing; see
    #: `decide._prefer_incumbent` for why that is not merely a nicety.
    previous: Intent | None = None

    @property
    def nominated_target_ids(self) -> tuple[UnitId, ...]:
        """The enemies this unit has been asked to answer — its own, and only its own.

        Derived rather than stored, and **never the troop's whole list.** The
        coordinator exports one for diagnostics; feeding it here would hand every
        member of a troop a position on every threat, which is precisely the
        convergence the coordinator exists to prevent. One assignment per unit,
        so this is at most one id — and a one-element tuple needs no sorting,
        which is why the sort that used to live here is gone with the field.
        """
        return (self.assignment.target_id,) if self.assignment is not None else ()

    @property
    def protecting_id(self) -> UnitId | None:
        """The ally the assigned threat is being answered on behalf of.

        `positioning.protected_by` would rather be told this than infer it: its
        fallback picks the ally nearest the threat, which is wrong exactly when
        the threat happens to be standing beside a different one.
        """
        return self.assignment.protecting_id if self.assignment is not None else None


def observe(
    world: World,
    unit: Unit,
    map_config: MapConfig,
    seconds_per_tick: float,
    abilities: AbilityCatalog | None = None,
    assignment: Assignment | None = None,
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
        ability=(abilities or {}).get(unit.ability_id) if unit.ability_id else None,
        map_config=map_config,
        tick=world.tick,
        seconds_per_tick=seconds_per_tick,
        assignment=assignment,
        commitment=unit.ai.commitment if unit.ai is not None else None,
        recovery_remaining=unit.ai.recovery_remaining if unit.ai is not None else 0,
        previous=unit.ai.intent if unit.ai is not None else None,
    )
