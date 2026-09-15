"""A hand-placed field, so a decision test can state exactly what it is testing.

`create_world` deploys into the strips at opposite ends of a 569-unit map, which
is the right opening for a battle and useless for asking "does a wounded hound
prefer to finish the mage or hold the line" — the answer is always "nobody is in
reach of anything". These build a world where units stand where the test puts
them.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.sim.ai.attach import attach_behavior
from app.sim.ai.objective import DEFAULT_FIXTURES, ObjectiveFixtures
from app.sim.ai.observe import Observation, observe
from app.sim.ai.profiles import BehaviorLibrary
from app.sim.config import DEFAULT_SIM_CONFIG, seconds_per_tick
from app.sim.context import TickContext, create_tick_context
from app.sim.map import THREE_ZONE_MAP
from app.sim.rng import create_rng
from app.sim.schools import resolve_school_multipliers
from app.sim.types import Side, Vec2
from app.sim.units import UnitType, build_unit_type_catalog
from app.sim.world import BaseState, Troop, Unit, World

SECONDS_PER_TICK = seconds_per_tick(DEFAULT_SIM_CONFIG)


def make_unit(
    unit_id: str,
    unit_type: UnitType,
    side: Side,
    position: Vec2,
    troop_id: str | None = None,
    hp: float | None = None,
) -> Unit:
    return Unit(
        id=unit_id,
        type_id=unit_type.id,
        kind=unit_type.kind,
        schools=unit_type.schools,
        side=side,
        troop_id=troop_id or f"{side}-t0",
        max_hp=unit_type.max_hp,
        damage=unit_type.damage,
        range=unit_type.range,
        speed=unit_type.speed,
        attack_cooldown_seconds=unit_type.attack_cooldown_seconds,
        hp=unit_type.max_hp if hp is None else hp,
        position=position,
    )


def make_world(units: Sequence[Unit]) -> World:
    troops: list[Troop] = []
    for unit in units:
        troop = next((t for t in troops if t.id == unit.troop_id), None)
        if troop is None:
            troop = Troop(id=unit.troop_id, side=unit.side)
            troops.append(troop)
        (troop.mage_ids if unit.kind == "mage" else troop.summon_ids).append(unit.id)

    return World(
        tick=0,
        rng_state=0,
        units=list(units),
        troops=troops,
        bases={
            side: BaseState(
                max_hp=THREE_ZONE_MAP.bases[side].max_hp,
                position=THREE_ZONE_MAP.bases[side].position,
                hp=THREE_ZONE_MAP.bases[side].max_hp,
            )
            for side in ("north", "south")
        },
        zone_score={"north": 0, "south": 0},
    )


def attach(world: World, library: BehaviorLibrary, unit_types: Sequence[UnitType]) -> None:
    attach_behavior(world.units, world.troops, library, build_unit_type_catalog(list(unit_types)))


def context(seed: int = 5) -> TickContext:
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=THREE_ZONE_MAP,
        multipliers=resolve_school_multipliers([]),
        rng=create_rng(seed),
    )


def look(world: World, unit: Unit, fixtures: ObjectiveFixtures = DEFAULT_FIXTURES) -> Observation:
    return observe(world, unit, THREE_ZONE_MAP, SECONDS_PER_TICK, fixtures)
