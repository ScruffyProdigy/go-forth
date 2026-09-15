"""Staging a scenario and playing it through the real tick loop.

The pipeline here is the actual one — `TICK_PHASES` via `step_battle`, the same
call `run_battle` makes — rather than a scenario-shaped imitation of it. A
harness that called `decide()` directly would test the decision loop and miss
everything about how decisions survive contact with movement, combat and the
orders phase rewriting `unit.destination` underneath them, which is where the
interesting failures live.

What it adds on top is a trace, and queries over it. A scenario should read as
"play this, then assert what these units did", not as bookkeeping.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.sim.ai.attach import attach_behavior
from app.sim.ai.casting import FollowsIntent
from app.sim.ai.inspect.record import DecisionTrace, TraceConfig, TraceRecord
from app.sim.ai.intent import ActionKind
from app.sim.ai.profiles import BehaviorLibrary
from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import create_tick_context
from app.sim.events import BattleEvent
from app.sim.map import TWO_LANE_MAP
from app.sim.orders import Order
from app.sim.rng import create_rng
from app.sim.run_battle import step_battle
from app.sim.schools import resolve_side_multipliers
from app.sim.types import TroopId, UnitId, Vec2
from app.sim.units import UnitType, build_unit_type_catalog
from app.sim.world import Unit, World
from tests.sim.ai.helpers import make_world

#: Fixed so a scenario is repeatable by construction. A scenario that needs a
#: different one passes it, and says in the test why the default was wrong.
SCENARIO_SEED = 20260915


@dataclass(frozen=True)
class ScenarioRun:
    """What a played scenario left behind, and convenient ways to ask about it."""

    world: World
    trace: DecisionTrace
    events: tuple[BattleEvent, ...]

    @property
    def records(self) -> tuple[TraceRecord, ...]:
        return self.trace.records

    def by_unit(self, unit_id: UnitId) -> tuple[TraceRecord, ...]:
        """Every decision that unit made, in tick order."""
        return tuple(record for record in self.records if record.unit_id == unit_id)

    def actions(self, unit_id: UnitId) -> tuple[ActionKind, ...]:
        return tuple(record.chosen.kind for record in self.by_unit(unit_id))

    def targets(self, unit_id: UnitId) -> tuple[UnitId | None, ...]:
        return tuple(record.chosen.target_id for record in self.by_unit(unit_id))

    def positions(self, unit_id: UnitId) -> tuple[Vec2, ...]:
        """Where the unit was standing each time it decided."""
        return tuple(record.chosen.destination or Vec2(0, 0) for record in self.by_unit(unit_id))

    def unit(self, unit_id: UnitId) -> Unit:
        return next(unit for unit in self.world.units if unit.id == unit_id)

    def alive(self, unit_id: UnitId) -> bool:
        return any(unit.id == unit_id and unit.hp > 0 for unit in self.world.units)


def play(
    units: Sequence[Unit],
    unit_types: Sequence[UnitType],
    library: BehaviorLibrary,
    *,
    ticks: int,
    orders: Mapping[TroopId, Order] | None = None,
    seed: int = SCENARIO_SEED,
    config: TraceConfig | None = None,
) -> ScenarioRun:
    """Stages a field, attaches behavior, and runs it for `ticks` ticks.

    Units are placed exactly where the caller put them — `create_world` would
    deploy them into formation behind their own line, which is right for a battle
    and useless for asking a question about two units standing ten units apart.
    """
    world = make_world(units, orders)
    catalog = build_unit_type_catalog(list(unit_types))
    attach_behavior(world.units, world.troops, library, catalog)

    trace = DecisionTrace(config or TraceConfig(max_records=100_000))
    ctx = create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(seed),
        unit_types=catalog,
        cast_policy=FollowsIntent(),
        trace=trace,
    )

    events: list[BattleEvent] = []
    for _ in range(ticks):
        events.extend(step_battle(world, ctx))

    return ScenarioRun(world=world, trace=trace, events=tuple(events))


def effective_weights(record: TraceRecord, factor: str) -> tuple[float, ...]:
    """What this factor was actually weighted at, across the candidates weighed.

    Since JQ-330 a personality's deltas are contextual, so the standing weights
    are identical whatever the mage is like and the effect is visible only here.
    One entry per candidate the record kept; `min` is "the most this unit was
    willing to discount the factor anywhere".
    """
    return tuple(
        contribution.weight
        for candidate in (record.chosen, *record.rivals)
        for contribution in candidate.contributions
        if contribution.factor == factor
    )


def influences_on(record: TraceRecord) -> tuple[tuple[str, str, str], ...]:
    """Every (tag, context, factor) the record says spoke, across its candidates."""
    return tuple(
        sorted(
            {
                (i.tag, i.context, i.factor)
                for candidate in (record.chosen, *record.rivals)
                for i in candidate.influences
            }
        )
    )


def assignments_of(run: ScenarioRun, troop_id: str) -> tuple[str, ...]:
    """Which units that troop's coordinator has given an assignment, by unit id."""
    troop = next(t for t in run.world.troops if t.id == troop_id)
    return tuple(a.unit_id for a in troop.coordination.assignments)


def weight(record: TraceRecord, factor: str) -> float:
    """One **standing** weight out of a record, by name rather than by position.

    Standing means "before this unit looked at a particular candidate". Since
    JQ-330 a personality's interesting deltas are contextual, so a tag can be
    entirely absent from this number and still decide the battle — use
    `effective_weights` to see what a candidate was actually scored on.
    """
    return next(value for name, value in record.weights if name == factor)


def tags(record: TraceRecord) -> tuple[str, ...]:
    """Every personality tag the record says was in play."""
    return tuple(personality.tag for personality in record.personalities)
