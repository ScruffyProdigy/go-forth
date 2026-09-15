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

from app.sim.abilities import build_ability_catalog
from app.sim.ai.casting import FollowsIntent
from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig, max_ticks, validate_sim_config
from app.sim.context import TickContext, create_tick_context
from app.sim.energy import SchoolEnergyRuleTable, resolve_school_energy_rules
from app.sim.events import BattleEvent
from app.sim.map import MapConfig
from app.sim.phases import TICK_PHASES
from app.sim.resonance import SideResonanceCounts, count_resonance
from app.sim.rng import create_rng
from app.sim.schools import (
    SchoolConfig,
    SideMultiplierTable,
    resolve_side_multipliers,
)
from app.sim.spells import build_spell_catalog
from app.sim.types import SIDES, Side
from app.sim.units import build_unit_type_catalog
from app.sim.world import BattleSetup, World, create_world

#: Why the battle stopped.
#:
#: `timeUp` is the ordinary ending: the round is decided on zone score, which is
#: the match engine's business rather than the sim's (JQ-187). `baseDestroyed` is
#: the exception — it does not resolve a round, it ends the whole match, and it
#: takes precedence over everything else that happened on the same tick.
BattleOutcome = Literal["annihilation", "timeUp", "baseDestroyed"]


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
    multipliers: SideMultiplierTable
    #: What each side's resonance was for this battle (§4.11), so a match engine
    #: can carry the same numbers into the next round rather than re-deriving
    #: them from whatever that round happens to field.
    resonance: SideResonanceCounts
    #: The energy rule each school charged under. Same reason as `multipliers`:
    #: a consumer replaying the battle should not have to re-derive it.
    energy_rules: SchoolEnergyRuleTable
    #: Whose base fell, on a `baseDestroyed` outcome. That side loses the match
    #: outright — not the round. None on every other outcome.
    destroyed_base: Side | None = None

    @property
    def base_hp(self) -> dict[Side, float]:
        """What each base has left, to be carried into the next round as-is."""
        return {side: self.final_state.bases[side].hp for side in SIDES}


def step_battle(world: World, ctx: TickContext) -> list[BattleEvent]:
    """Advances the world exactly one tick and returns that tick's events."""
    world.tick += 1

    for phase in TICK_PHASES:
        phase.run(world, ctx)

    world.rng_state = ctx.rng.state
    return ctx.emitter.drain()


def _side_is_wiped_out(world: World) -> bool:
    return any(not any(unit.side == side for unit in world.units) for side in SIDES)


def _base_destroyed(world: World) -> Side | None:
    """Whose base has fallen, walking `SIDES` so the answer never depends on
    dict order. North is checked first; a tie is not a thing two separate
    attackers can produce in one tick, since damage resolves in list order."""
    for side in SIDES:
        if world.bases[side].hp <= 0:
            return side
    return None


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
    configs = list(school_configs)
    energy_rules = resolve_school_energy_rules(configs)
    world = create_world(map_config, battle_state, rng)

    # The mages a side selects for the round establish its resonance for the
    # whole round (Ryan, 2026-09-15): counted once off the opening world and
    # never again, so a mage falling at tick 400 costs you the mage and not the
    # resonance you brought. Resolved here rather than in a phase for that
    # reason. Nothing between `create_world` and here touches the rng, so the
    # battle's draws are unaffected by the order.
    established = count_resonance(world)
    multipliers = resolve_side_multipliers(configs, established)

    ctx = create_tick_context(
        config=config,
        map_config=map_config,
        multipliers=multipliers,
        rng=rng,
        resonance=established,
        unit_types=build_unit_type_catalog(battle_state.unit_types),
        energy_rules=energy_rules,
        abilities=build_ability_catalog(battle_state.abilities),
        # Honours a committed cast and holds otherwise, falling through to
        # the default for units with no behaviour data (JQ-328).
        cast_policy=FollowsIntent(),
        spells=build_spell_catalog(battle_state.spells),
    )

    ticks: list[BattleTick] = [BattleTick(tick=0, state=copy.deepcopy(world), events=())]
    events: list[BattleEvent] = []
    limit = max_ticks(config)
    outcome: BattleOutcome = "timeUp"
    destroyed_base: Side | None = None

    while world.tick < limit:
        tick_events = step_battle(world, ctx)
        events.extend(tick_events)
        ticks.append(BattleTick(tick=world.tick, state=copy.deepcopy(world), events=tuple(tick_events)))

        # A base falling ends the match, so it is settled before anything else
        # that happened on the same tick.
        destroyed_base = _base_destroyed(world)
        if destroyed_base is not None:
            outcome = "baseDestroyed"
            break

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
        resonance=established,
        destroyed_base=destroyed_base,
        energy_rules=energy_rules,
    )
