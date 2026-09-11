"""The tick loop — the sim's entry point.

Pure by construction: no I/O, no wall clock, no rendering imports. Everything it
needs arrives as an argument and everything it produces is returned, so the same
four inputs always give byte-identical state and events. `tests/test_purity.py`
asserts that by walking this module's import graph.

The loop itself does nothing but walk `TICK_PHASES` — see `phases/__init__.py`
for the order and for where the remaining slices attach.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig, max_ticks, validate_sim_config
from app.sim.context import TickContext, create_tick_context
from app.sim.events import BattleEvent
from app.sim.map import MapConfig
from app.sim.phases import TICK_PHASES
from app.sim.rng import create_rng
from app.sim.schools import (
    SchoolConfig,
    SchoolMultiplierTable,
    resolve_school_multipliers,
)
from app.sim.types import SIDES
from app.sim.world import BattleSetup, World, create_world

#: Why the battle stopped. Zone-score and base-destruction endings arrive with slice B.
BattleOutcome = Literal["annihilation", "timeUp"]


@dataclass(frozen=True)
class BattleTick:
    tick: int
    #: A snapshot, detached from the live world, so later ticks cannot rewrite it.
    state: World
    events: tuple[BattleEvent, ...]


@dataclass(frozen=True)
class BattleResult:
    #: The seed the battle ran on. Replaying it reproduces this result exactly.
    seed: int
    #: Tick by tick, starting with the opening state at tick 0.
    ticks: tuple[BattleTick, ...]
    #: Every event of the battle, in order.
    events: tuple[BattleEvent, ...]
    final_state: World
    outcome: BattleOutcome
    #: The map the battle was fought on, so a consumer need not be handed it twice.
    map: MapConfig
    config: SimConfig
    multipliers: SchoolMultiplierTable


def step_battle(world: World, ctx: TickContext) -> list[BattleEvent]:
    """Advances the world exactly one tick and returns that tick's events."""
    world.tick += 1

    for phase in TICK_PHASES:
        phase.run(world, ctx)

    world.rng_state = ctx.rng.state
    return ctx.emitter.drain()


def _side_is_wiped_out(world: World) -> bool:
    return any(not any(unit.side == side for unit in world.units) for side in SIDES)


def run_battle(
    map_config: MapConfig,
    school_configs: Sequence[SchoolConfig],
    battle_state: BattleSetup,
    seed: int,
    config: SimConfig = DEFAULT_SIM_CONFIG,
) -> BattleResult:
    """Runs a battle to its end.

    `seed` is the whole of the battle's randomness: same seed, same battle.
    """
    validate_sim_config(config)

    rng = create_rng(seed)
    multipliers = resolve_school_multipliers(list(school_configs))
    world = create_world(map_config, battle_state, rng)
    ctx = create_tick_context(config=config, map_config=map_config, multipliers=multipliers, rng=rng)

    ticks: list[BattleTick] = [BattleTick(tick=0, state=copy.deepcopy(world), events=())]
    events: list[BattleEvent] = []
    limit = max_ticks(config)
    outcome: BattleOutcome = "timeUp"

    while world.tick < limit:
        tick_events = step_battle(world, ctx)
        events.extend(tick_events)
        ticks.append(BattleTick(tick=world.tick, state=copy.deepcopy(world), events=tuple(tick_events)))

        if _side_is_wiped_out(world):
            outcome = "annihilation"
            break

    return BattleResult(
        seed=seed,
        ticks=tuple(ticks),
        events=tuple(events),
        final_state=world,
        outcome=outcome,
        map=map_config,
        config=config,
        multipliers=multipliers,
    )
