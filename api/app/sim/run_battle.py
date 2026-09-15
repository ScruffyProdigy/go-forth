"""The tick loop — the sim's entry point.

Pure by construction: no I/O, no wall clock, no rendering imports. Everything it
needs arrives as an argument and everything it produces is returned, so the same
four inputs always give byte-identical state and events. `tests/test_purity.py`
asserts that by walking this module's import graph.

The loop itself does nothing but walk `TICK_PHASES` — see `phases/__init__.py`
for the order and for where the remaining slices attach.

Two ways in, one loop. `run_battle` runs a battle to its end and hands back the
whole of it, which is what a headless demo and the determinism harness want.
`BattleRunner` is the same battle advanced a tick at a time, which is what a
live round wants: a match controller running on a real clock has to accept a
spell cast *during* the battle, and a function that has already returned cannot
be handed one. `run_battle` is written in terms of the runner, so there is one
loop rather than two that drift.
"""

from __future__ import annotations

import bisect
import copy
from collections.abc import Sequence
from dataclasses import dataclass, field
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
from app.sim.spells import SpellCatalog, SpellInjection, build_spell_catalog, injection_order
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
    attackers can produce in one tick, since damage resolves in list order.

    Two *spells* landing on one tick can, though — nothing serialises those
    against each other — so a caller that has to tell a double destruction from
    a single one reads the bases itself rather than this. The match layer does
    exactly that (JQ-308); within the sim, north-first is only ever asked to
    name a side for `destroyed_base`, and the loop stops either way.
    """
    for side in SIDES:
        if world.bases[side].hp <= 0:
            return side
    return None


@dataclass
class BattleRunner:
    """One battle, advanced a tick at a time.

    Holds exactly what `run_battle` used to hold in local variables, so that a
    caller running on a clock can sit between two ticks — which is the whole
    point: `inject` is only reachable from there.
    """

    seed: int
    world: World
    ctx: TickContext
    map: MapConfig
    config: SimConfig
    multipliers: SideMultiplierTable
    resonance: SideResonanceCounts
    energy_rules: SchoolEnergyRuleTable
    spells: SpellCatalog
    ticks: list[BattleTick] = field(default_factory=list)
    events: list[BattleEvent] = field(default_factory=list)
    outcome: BattleOutcome = "timeUp"
    destroyed_base: Side | None = None
    #: Set once a terminal condition has been seen, so `step` is a no-op after
    #: the battle has ended rather than quietly running on past its own result.
    stopped: bool = False

    @property
    def limit(self) -> int:
        """The tick the loop stops at, so a battle always terminates."""
        return max_ticks(self.config)

    @property
    def finished(self) -> bool:
        return self.stopped or self.world.tick >= self.limit

    def step(self) -> tuple[BattleEvent, ...]:
        """Advances one tick, or does nothing if the battle is already over."""
        if self.finished:
            return ()

        tick_events = step_battle(self.world, self.ctx)
        self.events.extend(tick_events)
        self.ticks.append(
            BattleTick(tick=self.world.tick, state=copy.deepcopy(self.world), events=tuple(tick_events))
        )

        # A base falling ends the match, so it is settled before anything else
        # that happened on the same tick.
        self.destroyed_base = _base_destroyed(self.world)
        if self.destroyed_base is not None:
            self.outcome = "baseDestroyed"
            self.stopped = True
        elif _side_is_wiped_out(self.world):
            self.outcome = "annihilation"
            self.stopped = True

        return tuple(tick_events)

    def run_to_end(self) -> None:
        while not self.finished:
            self.step()

    def inject(self, injection: SpellInjection) -> None:
        """Schedules a cast that was accepted after the battle had started.

        Kept in the same order `schedule_injections` puts the opening set in, so
        that a spell cast live and the same spell scheduled up front resolve
        identically. Landing it strictly in the future is not politeness: the
        spells phase for the current tick has already run, so a cast dated to it
        would be swept up by the *next* tick and silently land late.
        """
        if injection.spell_id not in self.spells:
            raise ValueError(f"spell {injection.spell_id} is injected but is not in the spell catalog")
        if injection.tick <= self.world.tick:
            raise ValueError(
                f"spell {injection.spell_id} is injected at tick {injection.tick}, "
                f"which is not still ahead of tick {self.world.tick}"
            )

        pending = self.world.pending_spells
        keys = [injection_order(existing) for existing in pending]
        pending.insert(bisect.bisect_right(keys, injection_order(injection)), injection)

    def result(self) -> BattleResult:
        return BattleResult(
            seed=self.seed,
            ticks=tuple(self.ticks),
            events=tuple(self.events),
            final_state=self.world,
            outcome=self.outcome,
            map=self.map,
            config=self.config,
            multipliers=self.multipliers,
            resonance=self.resonance,
            destroyed_base=self.destroyed_base,
            energy_rules=self.energy_rules,
        )


def create_runner(
    map_config: MapConfig,
    school_configs: Sequence[SchoolConfig],
    battle_state: BattleSetup,
    seed: int,
    config: SimConfig = DEFAULT_SIM_CONFIG,
) -> BattleRunner:
    """Builds a battle and stops at tick 0, before any phase has run."""
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
    spells = build_spell_catalog(battle_state.spells)

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
        spells=spells,
    )

    return BattleRunner(
        seed=seed,
        world=world,
        ctx=ctx,
        map=map_config,
        config=config,
        multipliers=multipliers,
        resonance=established,
        energy_rules=energy_rules,
        spells=spells,
        ticks=[BattleTick(tick=0, state=copy.deepcopy(world), events=())],
    )


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
    runner = create_runner(map_config, school_configs, battle_state, seed, config)
    runner.run_to_end()
    return runner.result()
