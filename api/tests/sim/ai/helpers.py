"""A hand-placed field, so a decision test can state exactly what it is testing.

`create_world` deploys into formation behind each side's own line, which is the
right opening for a battle and useless for asking "does a wounded hound prefer to
finish the mage or hold the line" — the answer is always "nobody is in reach of
anything". These build a world where units stand where the test puts them.

A unit's `destination` defaults to its own position: standing on its post, with
no pull toward anywhere else. That is the neutral setting for a scoring test —
anything that wants an objective pull sets `destination` explicitly and says so.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.sim.ai.attach import attach_behavior
from app.sim.ai.observe import Observation, observe
from app.sim.ai.profiles import BehaviorLibrary
from app.sim.config import DEFAULT_SIM_CONFIG, seconds_per_tick
from app.sim.context import TickContext, create_tick_context
from app.sim.map import TWO_LANE_MAP
from app.sim.orders import PUSH_ENEMY_BASE, Order
from app.sim.rng import create_rng
from app.sim.schools import resolve_side_multipliers
from app.sim.types import Side, TroopId, Vec2
from app.sim.units import UnitType, build_unit_type_catalog
from app.sim.world import BaseState, Troop, Unit, World

SECONDS_PER_TICK = seconds_per_tick(DEFAULT_SIM_CONFIG)

#: What a troop is under unless a test says otherwise. Push rather than hold
#: because it is the order that permits everything — a test constraining
#: behaviour then does it on purpose rather than inheriting a restriction.
DEFAULT_ORDER = PUSH_ENEMY_BASE


def make_unit(
    unit_id: str,
    unit_type: UnitType,
    side: Side,
    position: Vec2,
    troop_id: str | None = None,
    hp: float | None = None,
    destination: Vec2 | None = None,
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
        formation_offset=Vec2(0, 0),
        destination=destination if destination is not None else position,
        support_capacity=unit_type.support_capacity,
        resummon_pace_seconds=unit_type.resummon_pace_seconds,
    )


def make_world(units: Sequence[Unit], orders: Mapping[TroopId, Order] | None = None) -> World:
    given = orders or {}
    troops: list[Troop] = []

    for unit in units:
        troop = next((t for t in troops if t.id == unit.troop_id), None)
        if troop is None:
            troop = Troop(id=unit.troop_id, side=unit.side, order=given.get(unit.troop_id, DEFAULT_ORDER))
            troops.append(troop)
        (troop.mage_ids if unit.kind == "mage" else troop.summon_ids).append(unit.id)

    return World(
        tick=0,
        rng_state=0,
        units=list(units),
        troops=troops,
        bases={
            side: BaseState(
                max_hp=TWO_LANE_MAP.bases[side].max_hp,
                position=TWO_LANE_MAP.bases[side].position,
                hp=TWO_LANE_MAP.bases[side].max_hp,
            )
            for side in ("north", "south")
        },
        zone_score={"north": 0, "south": 0},
        zone_holders={zone.id: None for zone in TWO_LANE_MAP.zones},
    )


def attach(world: World, library: BehaviorLibrary, unit_types: Sequence[UnitType]) -> None:
    attach_behavior(world.units, world.troops, library, build_unit_type_catalog(list(unit_types)))


def context(seed: int = 5) -> TickContext:
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(seed),
    )


def look(world: World, unit: Unit) -> Observation:
    return observe(world, unit, TWO_LANE_MAP, SECONDS_PER_TICK)
