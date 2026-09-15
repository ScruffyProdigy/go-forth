"""Resummoning and the troop bond (§4.5, §4.6).

The worlds here are built and then driven a phase at a time rather than through
`run_battle`, so a rebuild can be timed to the tick without a battle happening
around it. Units are parked far apart and given no reason to fight; what is being
measured is the clock, not the combat.
"""

from __future__ import annotations

import copy
import dataclasses

from app.sim.config import DEFAULT_SIM_CONFIG, to_ticks
from app.sim.context import TickContext, create_tick_context
from app.sim.fixtures import placeholder_battle
from app.sim.map import THREE_ZONE_MAP, MapConfig
from app.sim.phases import TICK_PHASES
from app.sim.rng import create_rng
from app.sim.run_battle import run_battle
from app.sim.schools import SchoolConfig, resolve_side_multipliers
from app.sim.types import Span, Vec2
from app.sim.units import UnitType
from app.sim.world import (
    ArmySetup,
    BattleSetup,
    DispelledSlot,
    RosterEntry,
    Troop,
    TroopSetup,
    Unit,
    World,
    create_world,
)
from tests.sim.fixtures_units import HOUND, KINDLER, WISP

CARDS = [KINDLER, HOUND, WISP]
PACE_TICKS = to_ticks(4, DEFAULT_SIM_CONFIG)

#: Every school pinned to identity, so a pace is the mage's own number and a
#: resonance change cannot quietly retune these tests. Resonance has its own file.
PINNED = [
    SchoolConfig(
        id=school,
        multipliers={
            "energy_gain_multiplier": 1,
            "resummon_pace_multiplier": 1,
            "stat_axis_multiplier": 1,
        },
    )
    for school in ("fire", "artifice")
]


def context(unit_types: list[UnitType] | None = None) -> TickContext:
    return create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=THREE_ZONE_MAP,
        multipliers=resolve_side_multipliers(PINNED),
        rng=create_rng(5),
        unit_types=unit_types if unit_types is not None else CARDS,
    )


def world_of(mages: int, summons: int, cards: list[UnitType] | None = None) -> World:
    """One troop a side, so a troop's own arithmetic is what is being measured."""
    setup = BattleSetup(
        unit_types=cards if cards is not None else CARDS,
        armies=[
            ArmySetup(
                side=side,
                troops=[
                    TroopSetup(
                        mages=[RosterEntry("kindler", mages)],
                        summons=[RosterEntry("cinder-hound", summons)] if summons else [],
                    )
                ],
            )
            for side in ("north", "south")
        ],
    )
    world = create_world(THREE_ZONE_MAP, setup, create_rng(5))
    for index, unit in enumerate(world.units):
        # Out of everyone's reach: nothing here is about fighting.
        unit.position = Vec2(index * 500, index * 500)
    return world


def troop_of(world: World, side: str) -> Troop:
    return next(troop for troop in world.troops if troop.side == side)


def units_of(world: World, troop: Troop) -> list[Unit]:
    return [unit for unit in world.units if unit.troop_id == troop.id]


def advance(world: World, ctx: TickContext, ticks: int) -> None:
    for _ in range(ticks):
        world.tick += 1
        for phase in TICK_PHASES:
            phase.run(world, ctx)


def summons_in(world: World, troop: Troop) -> list[Unit]:
    return [unit for unit in units_of(world, troop) if unit.kind == "summon"]


# --- the dispelled slot ------------------------------------------------------


def test_a_defeated_summon_becomes_a_dispelled_slot_on_its_troop() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    fallen = summons_in(world, troop)[0]
    fallen.hp = 0

    advance(world, ctx, 1)

    assert [slot.type_id for slot in troop.dispelled_slots] == [fallen.type_id]


def test_the_slot_stays_on_the_troop_that_lost_it() -> None:
    """Two troops fielding the same card never share a slot."""
    world, ctx = world_of(mages=1, summons=2), context()
    north, south = troop_of(world, "north"), troop_of(world, "south")
    summons_in(world, north)[0].hp = 0

    advance(world, ctx, 1)

    assert len(north.dispelled_slots) == 1
    assert south.dispelled_slots == []


def test_a_defeated_mage_leaves_no_slot() -> None:
    """A slot is a summon a mage may rebuild, not a vacancy of any kind."""
    world, ctx = world_of(mages=2, summons=1), context()
    troop = troop_of(world, "north")
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1)

    assert troop.dispelled_slots == []


# --- timing ------------------------------------------------------------------


def test_one_mage_refills_a_slot_after_its_resummon_pace() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    summons_in(world, troop)[0].hp = 0

    advance(world, ctx, 1)  # the defeat is swept and the slot opens
    advance(world, ctx, PACE_TICKS - 1)
    assert len(summons_in(world, troop)) == 1, "rebuilt before its pace was up"

    advance(world, ctx, 1)
    assert len(summons_in(world, troop)) == 2


def test_two_mages_rebuild_the_same_backlog_faster_than_one() -> None:
    """The design's whole reason for a per-mage pace (§4.5): redundancy is speed."""
    lonely, ctx_one = world_of(mages=1, summons=4), context()
    paired, ctx_two = world_of(mages=2, summons=4), context()

    for world in (lonely, paired):
        for summon in summons_in(world, troop_of(world, "north")):
            summon.hp = 0

    advance(lonely, ctx_one, 1 + PACE_TICKS)
    advance(paired, ctx_two, 1 + PACE_TICKS)

    assert len(summons_in(lonely, troop_of(lonely, "north"))) == 1
    assert len(summons_in(paired, troop_of(paired, "north"))) == 2


def test_the_resummon_clock_is_independent_of_the_attack_clock() -> None:
    """A mage rebuilds and casts on separate timers (§4.4) — being mid-cooldown
    does not pause a rebuild, and rebuilding does not reset the cooldown."""
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    mage = next(unit for unit in units_of(world, troop) if unit.kind == "mage")
    summons_in(world, troop)[0].hp = 0

    advance(world, ctx, 1)
    mage.cooldown_remaining = 999
    advance(world, ctx, PACE_TICKS)

    assert len(summons_in(world, troop)) == 2
    assert mage.cooldown_remaining == 999 - PACE_TICKS


def test_a_rebuilt_summon_appears_at_its_mage_s_position() -> None:
    """A troop rebuilds where it stands, which is what makes a zone sticky."""
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    mage = next(unit for unit in units_of(world, troop) if unit.kind == "mage")
    mage.speed = 0  # held still, so the position asserted is the one it rebuilt at
    mage.position = Vec2(123, 456)
    summons_in(world, troop)[0].hp = 0

    advance(world, ctx, 1 + PACE_TICKS)

    rebuilt = summons_in(world, troop)[-1]
    assert rebuilt.position == Vec2(123, 456)


def test_a_rebuilt_summon_takes_a_new_id() -> None:
    """A replay reading the stream would otherwise see one unit defeated twice."""
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    fallen = summons_in(world, troop)[0]
    fallen.hp = 0

    advance(world, ctx, 1 + PACE_TICKS)

    assert fallen.id not in [unit.id for unit in world.units]
    assert len({unit.id for unit in world.units}) == len(world.units)


def test_a_mage_with_no_pace_never_rebuilds() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    mage = next(unit for unit in units_of(world, troop) if unit.kind == "mage")
    mage.resummon_pace_seconds = None
    summons_in(world, troop)[0].hp = 0

    advance(world, ctx, 1 + PACE_TICKS * 4)

    assert len(summons_in(world, troop)) == 1
    assert len(troop.dispelled_slots) == 1


def test_a_slot_that_opens_late_still_costs_a_full_pace() -> None:
    """An idle mage does not bank time while it has nothing to rebuild."""
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")

    advance(world, ctx, PACE_TICKS * 3)
    summons_in(world, troop)[0].hp = 0
    advance(world, ctx, 1)

    advance(world, ctx, PACE_TICKS - 1)
    assert len(summons_in(world, troop)) == 1

    advance(world, ctx, 1)
    assert len(summons_in(world, troop)) == 2


# --- the capacity ceiling ----------------------------------------------------


def test_a_troop_rebuilds_only_up_to_its_combined_support_capacity() -> None:
    """One mage of capacity 2 holds two summons, however many slots it is owed."""
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    troop.dispelled_slots.extend(DispelledSlot(type_id="cinder-hound") for _ in range(3))

    advance(world, ctx, PACE_TICKS * 4)

    assert len(summons_in(world, troop)) == 2
    assert len(troop.dispelled_slots) == 3


def test_losing_a_mage_lowers_what_the_troop_can_rebuild() -> None:
    world, ctx = world_of(mages=2, summons=4), context()
    troop = troop_of(world, "north")
    for summon in summons_in(world, troop):
        summon.hp = 0
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1 + PACE_TICKS * 6)

    # One mage of capacity 2 is left, so two of the four come back.
    assert len(summons_in(world, troop)) == 2


def test_losing_a_mage_does_not_cull_summons_already_on_the_field() -> None:
    """Capacity is read when rebuilding, not enforced continuously — culling a
    living summon would duplicate the troop bond while being harsher than it."""
    world, ctx = world_of(mages=2, summons=4), context()
    troop = troop_of(world, "north")
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1 + PACE_TICKS * 2)

    assert len(summons_in(world, troop)) == 4


# --- events ------------------------------------------------------------------


def test_a_rebuild_is_emitted_through_the_core_s_emitter() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    mage = next(unit for unit in units_of(world, troop) if unit.kind == "mage")
    summons_in(world, troop)[0].hp = 0

    advance(world, ctx, 1 + PACE_TICKS)

    rebuilds = [event for event in ctx.emitter.events if event.type == "resummon"]
    assert len(rebuilds) == 1
    source = rebuilds[0].actors.source
    assert source is not None and source.unit_id == mage.id
    assert rebuilds[0].actors.targets[0].unit_id == summons_in(world, troop)[-1].id
    assert rebuilds[0].position == mage.position


def test_a_rebuild_removes_nothing_so_its_swing_is_zero() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    summons_in(world, troop)[0].hp = 0

    advance(world, ctx, 1 + PACE_TICKS)

    rebuild = next(event for event in ctx.emitter.events if event.type == "resummon")
    assert rebuild.swing.units_removed == ()


# --- the troop bond ----------------------------------------------------------


def test_the_last_mage_dying_dissolves_every_summon_in_its_troop() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1)

    assert summons_in(world, troop) == []
    assert troop.summon_ids == []


def test_the_dissolve_is_one_event_for_the_whole_troop() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    lost = [unit.id for unit in summons_in(world, troop)]
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1)

    dissolves = [event for event in ctx.emitter.events if event.type == "troopDissolve"]
    assert len(dissolves) == 1
    assert [unit.unit_id for unit in dissolves[0].swing.units_removed] == lost
    assert dissolves[0].actors.source is None, "nothing killed them; their support ended"


def test_a_troop_with_a_mage_left_does_not_dissolve() -> None:
    world, ctx = world_of(mages=2, summons=2), context()
    troop = troop_of(world, "north")
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1)

    assert len(summons_in(world, troop)) == 2
    assert [event for event in ctx.emitter.events if event.type == "troopDissolve"] == []


def test_a_same_school_mage_in_another_troop_does_not_prevent_the_dissolve() -> None:
    """The bond is local (§4.6): a mage in another troop is too far away to help,
    even one of the same school on the same side."""
    setup = BattleSetup(
        unit_types=CARDS,
        armies=[
            ArmySetup(
                side="north",
                troops=[
                    TroopSetup(
                        id="doomed",
                        mages=[RosterEntry("kindler")],
                        summons=[RosterEntry("cinder-hound", 2)],
                    ),
                    TroopSetup(
                        id="neighbour",
                        mages=[RosterEntry("kindler")],
                        summons=[RosterEntry("cinder-hound")],
                    ),
                ],
            ),
            ArmySetup(side="south", troops=[TroopSetup(mages=[RosterEntry("kindler")])]),
        ],
    )
    world = create_world(THREE_ZONE_MAP, setup, create_rng(5))
    for index, unit in enumerate(world.units):
        unit.position = Vec2(index * 500, index * 500)
    ctx = context()

    doomed = next(troop for troop in world.troops if troop.id == "doomed")
    neighbour = next(troop for troop in world.troops if troop.id == "neighbour")
    next(unit for unit in units_of(world, doomed) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1)

    assert summons_in(world, doomed) == []
    assert len(summons_in(world, neighbour)) == 1, "the neighbour kept its own summon"


def test_a_dissolved_troop_never_rebuilds() -> None:
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 1 + PACE_TICKS * 4)

    assert summons_in(world, troop) == []


def test_a_mageless_troop_with_nothing_left_emits_no_dissolve() -> None:
    world, ctx = world_of(mages=1, summons=0), context()
    troop = troop_of(world, "north")
    next(unit for unit in units_of(world, troop) if unit.kind == "mage").hp = 0

    advance(world, ctx, 2)

    assert [event for event in ctx.emitter.events if event.type == "troopDissolve"] == []


def test_a_dissolve_emits_no_defeat_for_the_summons_it_took() -> None:
    """Nothing killed them and nobody is credited (§4.6)."""
    world, ctx = world_of(mages=1, summons=2), context()
    troop = troop_of(world, "north")
    mage = next(unit for unit in units_of(world, troop) if unit.kind == "mage")
    mage.hp = 0

    advance(world, ctx, 1)

    defeated = [
        unit.unit_id
        for event in ctx.emitter.events
        if event.type == "unitDefeated"
        for unit in event.swing.units_removed
    ]
    assert defeated == []


# --- through the real loop ---------------------------------------------------


def narrow_map() -> MapConfig:
    """One column, so the armies walk into each other rather than past.

    The same trick `test_run_battle` uses. It also puts a troop in a single
    file, which is what lets the mage stand in front of its own summons: the
    deployment strip fills the front rank first and mages are placed first.
    """
    config = copy.deepcopy(THREE_ZONE_MAP)
    config.id = "test-lane"
    config.size_width = 40
    for zone in config.zones:
        zone.extent = Span(0, 40)
    for side in ("north", "south"):
        config.deployment[side].extent = Span(0, 40)
        config.bases[side].position = config.bases[side].position._replace(x=20)
    return config


NARROW_MAP = narrow_map()

#: A summon that holds its ground and outlives its mage. Without one the mage
#: is the last of its troop standing and there is nothing left to dissolve —
#: which is exactly what the placeholder mirror does, and why the bond needs a
#: staged battle to be shown end to end at all.
STATUE = dataclasses.replace(HOUND, id="cinder-statue", max_hp=400, speed=0, damage=0, range=0)

#: A glass mage in front of two statues, against a troop that can reach it.
GLASS_TROOP = BattleSetup(
    unit_types=[*CARDS, STATUE],
    armies=[
        ArmySetup(
            side="north",
            troops=[TroopSetup(mages=[RosterEntry("dying-wisp")], summons=[RosterEntry("cinder-statue", 2)])],
        ),
        ArmySetup(
            side="south",
            troops=[TroopSetup(mages=[RosterEntry("kindler")], summons=[RosterEntry("cinder-hound", 2)])],
        ),
    ],
)


def test_a_battle_dissolves_a_troop_that_loses_its_last_mage() -> None:
    result = run_battle(NARROW_MAP, PINNED, GLASS_TROOP, 1)

    dissolves = [event for event in result.events if event.type == "troopDissolve"]
    assert len(dissolves) == 1
    assert sorted(unit.unit_id for unit in dissolves[0].swing.units_removed) == ["north-t0-u1", "north-t0-u2"]
    assert not any(unit.troop_id == "north-t0" for unit in result.final_state.units)


def test_a_dissolve_and_a_defeat_on_the_same_tick_stay_separate_events() -> None:
    """The mage's defeat and the bond breaking are two things that happened."""
    result = run_battle(NARROW_MAP, PINNED, GLASS_TROOP, 1)

    dissolve = next(event for event in result.events if event.type == "troopDissolve")
    same_tick = [event.type for event in result.events if event.tick == dissolve.tick]

    assert "unitDefeated" in same_tick, "the mage died on the tick its troop dissolved"
    assert same_tick.count("troopDissolve") == 1


def test_a_dissolve_reports_no_units_defeated() -> None:
    """Nothing killed the summons, so nothing is credited with killing them."""
    result = run_battle(NARROW_MAP, PINNED, GLASS_TROOP, 1)

    defeated = [
        unit.unit_id
        for event in result.events
        if event.type == "unitDefeated"
        for unit in event.swing.units_removed
    ]
    assert "north-t0-u1" not in defeated
    assert "north-t0-u2" not in defeated


def test_the_shipped_placeholder_mirror_rebuilds_its_losses() -> None:
    """End to end on the real fixture: the mirror the headless demo runs."""
    result = run_battle(THREE_ZONE_MAP, [], placeholder_battle(), 20260911)

    rebuilds = [event for event in result.events if event.type == "resummon"]
    assert rebuilds, "three Fire mages a side should have rebuilt something in 90 s"
    for event in rebuilds:
        source = event.actors.source
        assert source is not None, "a rebuild always names the mage that made it"
        assert len(event.actors.targets) == 1
        assert event.actors.targets[0].troop_id == source.troop_id, "a mage rebuilds its own troop"
