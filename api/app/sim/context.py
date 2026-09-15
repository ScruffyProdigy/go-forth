"""What a phase is handed each tick.

Everything a system needs and nothing it can use to reach outside the sim: no
clock, no filesystem, no logger. New slices add fields here rather than importing
modules of their own into the phases.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.sim.config import SimConfig, seconds_per_tick, validate_sim_config
from app.sim.events import EventEmitter, create_event_emitter
from app.sim.map import MapConfig
from app.sim.rng import Rng
from app.sim.schools import SideMultiplierTable
from app.sim.units import UnitType, UnitTypeCatalog, build_unit_type_catalog


@dataclass(frozen=True)
class TickContext:
    config: SimConfig
    map_config: MapConfig
    #: Resolved once at battle start; read by every system, written by none.
    #: Keyed by side first: resonance is a property of a player's roster, not of
    #: the field, so a system reads `multipliers[unit.side][school]`.
    multipliers: SideMultiplierTable
    #: The one emitter every system writes events through.
    emitter: EventEmitter
    rng: Rng
    #: The battle's cards. A resummon (§4.5) rebuilds a unit mid-battle, so the
    #: stat block has to outlive `create_world` — and it lives here rather than
    #: on `World` because the world is deep-copied every tick and this never
    #: changes.
    unit_types: UnitTypeCatalog
    #: Cached, because every phase that moves anything needs it.
    seconds_per_tick: float


def create_tick_context(
    *,
    config: SimConfig,
    map_config: MapConfig,
    multipliers: SideMultiplierTable,
    rng: Rng,
    unit_types: UnitTypeCatalog | Sequence[UnitType] = (),
    emitter: EventEmitter | None = None,
) -> TickContext:
    validate_sim_config(config)

    catalog = unit_types if isinstance(unit_types, Mapping) else build_unit_type_catalog(unit_types)

    return TickContext(
        config=config,
        map_config=map_config,
        multipliers=multipliers,
        emitter=emitter if emitter is not None else create_event_emitter(),
        rng=rng,
        unit_types=catalog,
        seconds_per_tick=seconds_per_tick(config),
    )
