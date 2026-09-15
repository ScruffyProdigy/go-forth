"""A bare two-unit field, for testing one effect at a time.

Deliberately not a battle: an effect primitive tested inside a running battle
is tested through movement, targeting and combat as well, and when it breaks
the failure names the wrong thing.
"""

from __future__ import annotations

from app.sim.abilities import Ability, build_ability_catalog
from app.sim.casting import CastPolicy
from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import TickContext, create_tick_context
from app.sim.energy import resolve_school_energy_rules
from app.sim.map import TWO_LANE_MAP
from app.sim.orders import PUSH_ENEMY_BASE
from app.sim.phase import TickPhase
from app.sim.phases import TICK_PHASES
from app.sim.rng import create_rng
from app.sim.schools import School, SchoolConfig, resolve_side_multipliers
from app.sim.spells import Spell, build_spell_catalog
from app.sim.types import Side, UnitId, Vec2, opposing
from app.sim.units import UnitKind
from app.sim.world import BaseState, Troop, Unit, World

#: The centre of the map — half its width, roughly half its height. Not a
#: zone: these tests assert relative distance (inside the blast, one hop away,
#: two hops) and absolute position is incidental, which is why none of them
#: reference zone geometry at all.
#:
#: JQ-376 reshapes the zones into two lanes with a push corridor between them,
#: and this point lands in that corridor — in no zone. That costs these tests
#: nothing, but once JQ-376 is in main the honest form of this fixture is
#: `hotspot_centre(config, zone)` with everything expressed as offsets from it.
#: Those helpers do not exist yet, so that is a rebase task, not this branch's.
MID = Vec2(187.5, 290)


def context(
    *,
    abilities: list[Ability] | None = None,
    spells: list[Spell] | None = None,
    school_configs: list[SchoolConfig] | None = None,
    cast_policy: CastPolicy | None = None,
) -> TickContext:
    configs = school_configs or []
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers(configs),
        energy_rules=resolve_school_energy_rules(configs),
        abilities=build_ability_catalog(abilities or []),
        spells=build_spell_catalog(spells or []),
        cast_policy=cast_policy,
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
        destination=destination if destination is not None else TWO_LANE_MAP.bases[opposing(side)].position,
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
                max_hp=TWO_LANE_MAP.bases[side].max_hp,
                position=TWO_LANE_MAP.bases[side].position,
                hp=TWO_LANE_MAP.bases[side].max_hp,
            )
            for side in ("north", "south")
        },
        zone_score={"north": 0, "south": 0},
        zone_holders={zone.id: None for zone in TWO_LANE_MAP.zones},
    )


def phase(name: str) -> TickPhase:
    """The phase called `name`, looked up out of `TICK_PHASES`.

    Looked up rather than imported directly, on purpose: `step_battle` walks
    that tuple and nothing else, so a merge that resolves it without slice C's
    phases should fail these tests rather than pass them against a loop that
    never runs the code under test.

    The raise spells out what happened because the obvious implementation —
    `next(p for p in TICK_PHASES if p.name == name)` — raises a bare
    `StopIteration` from inside a helper, which reads like a broken test
    rather than a dropped phase. That is the reading that gets tests "fixed"
    instead of merges.
    """
    for candidate in TICK_PHASES:
        if candidate.name == name:
            return candidate

    raise AssertionError(
        f"there is no {name!r} phase in TICK_PHASES, which holds "
        f"{[p.name for p in TICK_PHASES]}. If this turned up while resolving a "
        "merge, the resolution dropped a phase and the tick loop will not run "
        "it. Fix phases/__init__.py rather than this test."
    )
