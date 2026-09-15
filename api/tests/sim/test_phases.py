"""The per-tick phases and the order they run in."""

from __future__ import annotations

from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import TickContext, create_tick_context
from app.sim.formation import station
from app.sim.map import THREE_ZONE_MAP
from app.sim.orders import PUSH_ENEMY_BASE
from app.sim.phase import TickPhase
from app.sim.phases import TICK_PHASES
from app.sim.rng import create_rng
from app.sim.schools import resolve_side_multipliers
from app.sim.types import SIDES, Side, Vec2
from app.sim.world import (
    ArmySetup,
    BattleSetup,
    RosterEntry,
    TroopSetup,
    Unit,
    World,
    create_world,
)
from tests.sim.fixtures_units import ADEPT, HOUND

DUEL = BattleSetup(
    unit_types=[ADEPT, HOUND],
    armies=[
        ArmySetup(
            side=side,
            troops=[
                TroopSetup(
                    order=PUSH_ENEMY_BASE,
                    mages=[RosterEntry("ember-adept")],
                    summons=[RosterEntry("cinder-hound")],
                )
            ],
        )
        for side in SIDES
    ],
)


def context() -> TickContext:
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=THREE_ZONE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(5),
        unit_types=[ADEPT, HOUND],
    )


def duel() -> World:
    return create_world(THREE_ZONE_MAP, DUEL, create_rng(5))


def unit_of(world: World, side: Side, type_id: str) -> Unit:
    return next(u for u in world.units if u.side == side and u.type_id == type_id)


def phase(name: str) -> TickPhase:
    return next(p for p in TICK_PHASES if p.name == name)


def test_the_phase_order_is_declared_in_one_place() -> None:
    assert [p.name for p in TICK_PHASES] == [
        "orders",
        "movement",
        "combat",
        "scoring",
        "resummon",
        "removal",
    ]


def test_combat_runs_after_movement_so_a_unit_that_closed_can_swing() -> None:
    names = [p.name for p in TICK_PHASES]

    assert names.index("combat") > names.index("movement")


def test_the_dead_are_swept_last_so_a_defeated_unit_cannot_act() -> None:
    names = [p.name for p in TICK_PHASES]

    assert names.index("removal") == len(names) - 1


def test_orders_run_before_anything_moves() -> None:
    names = [p.name for p in TICK_PHASES]

    assert names.index("orders") == 0


def test_zones_are_scored_after_combat_so_a_zone_flips_the_tick_its_holder_falls() -> None:
    names = [p.name for p in TICK_PHASES]

    assert names.index("combat") < names.index("scoring") < names.index("removal")


def test_movement_advances_a_unit_toward_the_enemy_base() -> None:
    world, ctx = duel(), context()
    hunter = unit_of(world, "north", "cinder-hound")
    before = hunter.position.y

    phase("movement").run(world, ctx)

    assert hunter.position.y > before


def test_movement_advances_by_speed_times_the_tick_length() -> None:
    world, ctx = duel(), context()
    hunter = unit_of(world, "north", "cinder-hound")
    before = hunter.position

    phase("movement").run(world, ctx)

    travelled = ((hunter.position.x - before.x) ** 2 + (hunter.position.y - before.y) ** 2) ** 0.5
    assert abs(travelled - hunter.speed / DEFAULT_SIM_CONFIG.tick_rate) < 1e-9


def test_movement_stops_at_weapon_range_rather_than_overlapping() -> None:
    world, ctx = duel(), context()
    north = unit_of(world, "north", "cinder-hound")
    south = unit_of(world, "south", "cinder-hound")
    north.position = Vec2(100, 300)
    south.position = Vec2(100, 300 + north.range)

    phase("movement").run(world, ctx)

    assert north.position == Vec2(100, 300)


def engaged() -> tuple[World, Unit, Unit]:
    world = duel()
    attacker = unit_of(world, "north", "cinder-hound")
    defender = unit_of(world, "south", "cinder-hound")
    for unit in world.units:
        unit.position = Vec2(-1000, -1000)
    attacker.position = Vec2(100, 300)
    defender.position = Vec2(100, 310)
    return world, attacker, defender


def test_combat_damages_an_enemy_inside_range() -> None:
    world, _, defender = engaged()

    phase("combat").run(world, context())

    assert defender.hp == defender.max_hp - 20


def test_combat_leaves_an_enemy_outside_range_alone() -> None:
    world, attacker, defender = engaged()
    defender.position = Vec2(100, 300 + attacker.range + 1)

    phase("combat").run(world, context())

    assert defender.hp == defender.max_hp


def test_combat_waits_out_the_cooldown_before_swinging_again() -> None:
    world, _, defender = engaged()
    ctx = context()

    phase("combat").run(world, ctx)
    phase("combat").run(world, ctx)

    assert defender.hp == defender.max_hp - 20


def test_combat_swings_again_once_the_cooldown_has_run_down() -> None:
    world, _, defender = engaged()
    ctx = context()

    for _ in range(DEFAULT_SIM_CONFIG.tick_rate + 1):
        phase("combat").run(world, ctx)

    assert defender.hp == defender.max_hp - 40


def test_combat_emits_unit_defeated_when_a_unit_is_brought_to_zero() -> None:
    world, _, defender = engaged()
    ctx = context()
    defender.hp = 5

    phase("combat").run(world, ctx)

    defeats = [e for e in ctx.emitter.events if e.type == "unitDefeated"]
    assert len(defeats) == 1
    assert defeats[0].swing.units_removed[0].unit_id == defender.id


def test_combat_names_the_killer_on_the_defeat_it_caused() -> None:
    world, attacker, defender = engaged()
    ctx = context()
    defender.hp = 5

    phase("combat").run(world, ctx)

    source = ctx.emitter.events[0].actors.source
    assert source is not None and source.unit_id == attacker.id


def test_combat_does_not_let_a_unit_already_at_zero_swing_back() -> None:
    world, attacker, defender = engaged()
    attacker.hp = 0

    phase("combat").run(world, context())

    assert defender.hp == defender.max_hp


def test_removal_takes_a_unit_at_zero_hp_off_the_field() -> None:
    world = duel()
    fallen = unit_of(world, "south", "cinder-hound")
    fallen.hp = 0

    phase("removal").run(world, context())

    assert fallen.id not in [u.id for u in world.units]


def test_removal_takes_it_out_of_its_troop() -> None:
    world = duel()
    fallen = unit_of(world, "south", "cinder-hound")
    fallen.hp = 0

    phase("removal").run(world, context())

    troop = next(t for t in world.troops if t.id == fallen.troop_id)
    assert fallen.id not in troop.summon_ids


def test_removal_leaves_the_living_alone() -> None:
    world = duel()
    before = len(world.units)

    phase("removal").run(world, context())

    assert len(world.units) == before


def test_orders_give_every_unit_a_station_derived_from_its_troops_order() -> None:
    world, ctx = duel(), context()
    hunter = unit_of(world, "north", "cinder-hound")
    hunter.destination = Vec2(0, 0)

    phase("orders").run(world, ctx)

    assert hunter.destination == station(PUSH_ENEMY_BASE, "north", hunter.formation_offset, THREE_ZONE_MAP)


def test_a_unit_pulled_off_its_station_is_sent_back_to_it_next_tick() -> None:
    """The seam bounded diversions hang off (JQ-296): a behaviour layer overwrites
    a destination for as long as it wants the unit elsewhere, and returning to
    post costs it nothing but letting go."""
    world, ctx = duel(), context()
    hunter = unit_of(world, "north", "cinder-hound")
    assigned = hunter.destination

    hunter.destination = Vec2(10, 10)
    phase("orders").run(world, ctx)

    assert hunter.destination == assigned
