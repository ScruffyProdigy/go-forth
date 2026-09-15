"""A bare two-unit field, for testing one effect at a time.

Deliberately not a battle: an effect primitive tested inside a running battle
is tested through movement, targeting and combat as well, and when it breaks
the failure names the wrong thing.
"""

from __future__ import annotations

from app.sim.abilities import Ability, build_ability_catalog
from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import TickContext, create_tick_context
from app.sim.energy import resolve_school_energy_rules
from app.sim.map import THREE_ZONE_MAP
from app.sim.orders import PUSH_ENEMY_BASE
from app.sim.rng import create_rng
from app.sim.schools import School, SchoolConfig, resolve_side_multipliers
from app.sim.spells import Spell, build_spell_catalog
from app.sim.types import Side, UnitId, Vec2, opposing
from app.sim.units import UnitKind
from app.sim.world import BaseState, Troop, Unit, World

MID = Vec2(187.5, 290)


def context(
    *,
    abilities: list[Ability] | None = None,
    spells: list[Spell] | None = None,
    school_configs: list[SchoolConfig] | None = None,
) -> TickContext:
    configs = school_configs or []
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=THREE_ZONE_MAP,
        multipliers=resolve_side_multipliers(configs),
        energy_rules=resolve_school_energy_rules(configs),
        abilities=build_ability_catalog(abilities or []),
        spells=build_spell_catalog(spells or []),
        rng=create_rng(5),
    )


def unit(
    unit_id: UnitId,
    side: Side,
    position: Vec2,
    *,
    kind: UnitKind = "summon",
    hp: float = 100,
    schools: tuple[School, ...] = ("fire",),
    ability_id: str | None = None,
    troop_id: str | None = None,
    speed: float = 30,
    damage: float = 0,
    emplacement: bool = False,
    blocks_movement: bool = False,
    block_radius: float = 0,
    destination: Vec2 | None = None,
) -> Unit:
    return Unit(
        id=unit_id,
        type_id=unit_id,
        kind=kind,
        schools=schools,
        side=side,
        troop_id=troop_id or f"{side}-t0",
        max_hp=hp,
        damage=damage,
        range=20,
        speed=speed,
        attack_cooldown_seconds=1,
        hp=hp,
        position=position,
        # Slice B's placement inputs. These tests stage positions by hand and
        # never run the orders phase, so the destination defaults to what slice
        # A's movement used before orders existed — the enemy base — and a test
        # about standing still passes the unit's own position instead.
        formation_offset=Vec2(0, 0),
        destination=destination if destination is not None else THREE_ZONE_MAP.bases[opposing(side)].position,
        ability_id=ability_id,
        emplacement=emplacement,
        blocks_movement=blocks_movement,
        block_radius=block_radius,
    )


def field(*units: Unit) -> World:
    """A world holding exactly the units given, and nothing else going on."""
    troop_ids = []
    for member in units:
        if member.troop_id not in troop_ids:
            troop_ids.append(member.troop_id)

    troops = []
    for troop_id in troop_ids:
        members = [m for m in units if m.troop_id == troop_id]
        troops.append(
            Troop(
                id=troop_id,
                side=members[0].side,
                order=PUSH_ENEMY_BASE,
                mage_ids=[m.id for m in members if m.kind == "mage"],
                summon_ids=[m.id for m in members if m.kind == "summon"],
            )
        )

    return World(
        tick=1,
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
        zone_holders={zone.id: None for zone in THREE_ZONE_MAP.zones},
    )
