"""What a phase is handed each tick.

Everything a system needs and nothing it can use to reach outside the sim: no
clock, no filesystem, no logger. New slices add fields here rather than importing
modules of their own into the phases.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.config import SimConfig, seconds_per_tick, validate_sim_config
from app.sim.events import EventEmitter, create_event_emitter
from app.sim.map import MapConfig
from app.sim.rng import Rng
from app.sim.schools import SchoolMultiplierTable


@dataclass(frozen=True)
class TickContext:
    config: SimConfig
    map_config: MapConfig
    #: Resolved once at battle start; read by every system, written by none.
    multipliers: SchoolMultiplierTable
    #: The one emitter every system writes events through.
    emitter: EventEmitter
    rng: Rng
    #: Cached, because every phase that moves anything needs it.
    seconds_per_tick: float


def create_tick_context(
    *,
    config: SimConfig,
    map_config: MapConfig,
    multipliers: SchoolMultiplierTable,
    rng: Rng,
    emitter: EventEmitter | None = None,
) -> TickContext:
    validate_sim_config(config)

    return TickContext(
        config=config,
        map_config=map_config,
        multipliers=multipliers,
        emitter=emitter if emitter is not None else create_event_emitter(),
        rng=rng,
        seconds_per_tick=seconds_per_tick(config),
    )
