"""The troop coordinator: who is asked to answer what, and when it is let go."""

from __future__ import annotations

from collections.abc import Sequence

from app.sim.ai.coordination import (
    BASE_COMMITMENT_SECONDS,
    BASE_DEFENDERS,
    BASE_GUARD_RADIUS,
    MAX_DEFENDERS,
    baseline_profile,
    compose_profile,
    coordinate,
    nominated_target_ids,
    profile_for,
)
from app.sim.ai.fixtures import (
    METHODICAL,
    OPPORTUNISTIC,
    PROTECTIVE,
    SAMPLE_PERSONALITIES,
    placeholder_behavior,
    strength_library,
)
from app.sim.ai.profiles import BehaviorLibrary, MagePersonality, PersonalityRef
from app.sim.fixtures import placeholder_battle
from app.sim.map import TWO_LANE_MAP
from app.sim.run_battle import run_battle
from app.sim.types import Vec2
from app.sim.units import UnitType
from app.sim.world import Troop, Unit, World
from tests.sim.ai.helpers import SECONDS_PER_TICK, attach, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND

#: A long-ranged, rooted enemy: it can threaten a mage from outside every
#: summon's reach without moving, which is what makes "who goes" a real question.
SIEGE = UnitType(
    id="slag-mortar",
    kind="summon",
    schools=("fire",),
    max_hp=80,
    damage=15,
    range=100,
    speed=0,
    attack_cooldown_seconds=2,
)
#: A summon that holds ground and cannot be sent anywhere.
EMPLACEMENT = UnitType(
    id="slag-wall",
    kind="summon",
    schools=("fire",),
    max_hp=200,
    damage=6,
    range=20,
    speed=0,
    attack_cooldown_seconds=2,
    emplacement=True,
)
#: And one that can go, but has nothing to do when it arrives.
HARMLESS = UnitType(
    id="ash-mote",
    kind="summon",
    schools=("fire",),
    max_hp=30,
    damage=0,
    range=0,
    speed=60,
    attack_cooldown_seconds=2,
)

TYPES = [ADEPT, HOUND, SIEGE, EMPLACEMENT, HARMLESS]

MAGE_AT = Vec2(180, 400)
BASELINE_COMMITMENT_TICKS = round(BASE_COMMITMENT_SECONDS / SECONDS_PER_TICK)


def guarded(*, threats: int = 1, summons: int = 2) -> list[Unit]:
    """A troop with its mage under fire from `threats` rooted mortars.

    Every summon is nearer the mage than the mortars are, and no mortar is in
    any summon's reach, so answering one means somebody walking — which is the
    arrangement where an allocation matters at all.
    """
    units = [make_unit("m", ADEPT, "north", MAGE_AT)]
    units += [
        make_unit(f"s{i}", HOUND, "north", Vec2(MAGE_AT.x + 20 * i, MAGE_AT.y - 20)) for i in range(summons)
    ]
    units += [
        make_unit(f"e{i}", SIEGE, "south", Vec2(MAGE_AT.x - 40 * i, MAGE_AT.y - 80)) for i in range(threats)
    ]
    return units


def troop_of(world: World) -> Troop:
    return next(troop for troop in world.troops if troop.id == "north-t0")


def guarded_world(units: Sequence[Unit] | None = None, library: BehaviorLibrary | None = None) -> World:
    world = make_world(list(units) if units is not None else guarded())
    attach(world, library if library is not None else strength_library("m", PROTECTIVE), TYPES)
    return world


def run(world: World, tick: int = 0) -> Troop:
    troop = troop_of(world)
    coordinate(world, troop, tick, SECONDS_PER_TICK)
    return troop


def unit(world: World, unit_id: str) -> Unit:
    return next(u for u in world.units if u.id == unit_id)


# --- composing the habits ---------------------------------------------------


def test_a_troop_with_no_personalities_coordinates_at_the_baseline() -> None:
    assert compose_profile((), SECONDS_PER_TICK) == baseline_profile(SECONDS_PER_TICK)


def test_protective_widens_the_guard_and_buys_a_second_defender() -> None:
    profile = profile_for(troop_of(guarded_world()), guarded_world(), SECONDS_PER_TICK)

    assert profile.guard_radius > BASE_GUARD_RADIUS
    assert profile.defenders == int(BASE_DEFENDERS) + 1


def test_methodical_holds_a_decision_longer_and_opportunistic_shorter() -> None:
    """The one dial a personality has on *time*, and it points both ways."""
    patient = profile_for(
        troop_of(world := guarded_world(library=strength_library("m", METHODICAL))),
        world,
        SECONDS_PER_TICK,
    )
    restless = profile_for(
        troop_of(world := guarded_world(library=strength_library("m", OPPORTUNISTIC))),
        world,
        SECONDS_PER_TICK,
    )

    assert patient.commitment_ticks > BASELINE_COMMITMENT_TICKS > restless.commitment_ticks


def test_strength_scales_a_coordination_habit_like_it_scales_a_weight() -> None:
    half = profile_for(
        troop_of(world := guarded_world(library=strength_library("m", PROTECTIVE, strength=0.5))),
        world,
        SECONDS_PER_TICK,
    )
    full = profile_for(troop_of(world := guarded_world()), world, SECONDS_PER_TICK)

    assert BASE_GUARD_RADIUS < half.guard_radius < full.guard_radius


def test_a_tag_dialled_to_zero_leads_exactly_like_no_tag_at_all() -> None:
    world = guarded_world(library=strength_library("m", PROTECTIVE, strength=0.0))

    assert profile_for(troop_of(world), world, SECONDS_PER_TICK) == baseline_profile(SECONDS_PER_TICK)


def test_stacked_enthusiasm_saturates_rather_than_running_away() -> None:
    world = guarded_world(library=strength_library("m", PROTECTIVE, strength=2.0))

    assert profile_for(troop_of(world), world, SECONDS_PER_TICK).defenders <= MAX_DEFENDERS


# --- allocating -------------------------------------------------------------


def test_one_defender_suffices_and_it_is_the_nearest_one() -> None:
    troop = run(guarded_world(guarded(summons=3)))

    assert [(a.unit_id, a.target_id, a.protecting_id) for a in troop.coordination.assignments] == [
        ("s0", "e0", "m")
    ]


def test_the_ally_being_defended_is_never_asked_to_defend_itself() -> None:
    """It is already fighting for its life. An assignment would add nothing."""
    troop = run(guarded_world(guarded(summons=1)))

    assert [a.unit_id for a in troop.coordination.assignments] == ["s0"]


def test_leadership_cannot_commandeer_the_whole_troop() -> None:
    """Three threats, four living members, and at most half of them commit."""
    troop = run(guarded_world(guarded(threats=3, summons=3)))

    assert len(troop.coordination.assignments) == 2


def test_an_immobile_summon_is_never_sent_after_something_out_of_its_reach() -> None:
    """The capability rule at its sharpest: a wall is not asked to walk."""
    units = guarded(summons=0)
    units.append(make_unit("wall", EMPLACEMENT, "north", Vec2(MAGE_AT.x, MAGE_AT.y - 20)))

    troop = run(guarded_world(units))

    assert troop.coordination.assignments == ()


def test_a_summon_with_no_damage_is_never_assigned() -> None:
    """Being able to *go* is not the same as being able to do anything there."""
    units = guarded(summons=0)
    units.append(make_unit("mote", HARMLESS, "north", Vec2(MAGE_AT.x, MAGE_AT.y - 20)))

    troop = run(guarded_world(units))

    assert troop.coordination.assignments == ()


def test_assignments_come_out_sorted_by_unit_id() -> None:
    troop = run(guarded_world(guarded(threats=3, summons=3)))

    ids = [a.unit_id for a in troop.coordination.assignments]
    assert ids == sorted(ids)


def test_the_coordinator_never_touches_a_destination() -> None:
    """Stations belong to the orders phase, and through it to the player."""
    world = guarded_world(guarded(summons=3))
    before = {u.id: u.destination for u in world.units}

    run(world)

    assert {u.id: u.destination for u in world.units} == before


def test_nominated_targets_are_deduplicated_and_sorted() -> None:
    troop = run(guarded_world(guarded(threats=3, summons=3)))

    nominated = nominated_target_ids(troop)
    assert nominated == tuple(sorted(set(nominated)))
    assert set(nominated) == {a.target_id for a in troop.coordination.assignments}


# --- releasing --------------------------------------------------------------


def test_an_assignment_is_released_when_its_target_dies() -> None:
    world = guarded_world(guarded(summons=3))
    run(world)
    assert world.troops and troop_of(world).coordination.assignments

    unit(world, "e0").hp = 0
    troop = run(world, tick=1)

    assert troop.coordination.assignments == ()


def test_an_assignment_is_released_when_the_ally_it_protects_dies() -> None:
    """And with the mage gone the troop has dissolved, so nothing replaces it."""
    world = guarded_world(guarded(summons=3))
    run(world)

    unit(world, "m").hp = 0
    troop = run(world, tick=1)

    assert troop.coordination.assignments == ()


def test_an_assignment_is_released_when_the_defender_dies() -> None:
    world = guarded_world(guarded(summons=3))
    run(world)

    unit(world, "s0").hp = 0
    troop = run(world, tick=1)

    assert [a.unit_id for a in troop.coordination.assignments] == ["s1"]


def test_an_assignment_is_released_when_the_threat_walks_away() -> None:
    """Live-state reaction: the premise is gone, so the commitment goes with it."""
    world = guarded_world(guarded(summons=3))
    run(world)

    unit(world, "e0").position = Vec2(MAGE_AT.x, MAGE_AT.y - 320)
    troop = run(world, tick=1)

    assert troop.coordination.assignments == ()


def test_a_troop_that_has_lost_its_last_mage_coordinates_nothing() -> None:
    """JQ-289's dissolve. What a mage was providing stops when the mage does."""
    world = guarded_world(guarded(summons=3))
    run(world)

    unit(world, "m").hp = 0
    troop = run(world, tick=1)

    assert troop.coordination.assignments == ()


# --- committing -------------------------------------------------------------


def test_a_defender_is_not_swapped_out_for_a_closer_one_mid_approach() -> None:
    """Without this, nobody ever arrives: the nearest unit changes every tick."""
    world = guarded_world(guarded(summons=3), library=strength_library("m", METHODICAL))
    run(world)
    assigned = troop_of(world).coordination.assignments[0].unit_id

    # Somebody else is now much closer to the threat than the defender is.
    other = next(u for u in world.units if u.id.startswith("s") and u.id != assigned)
    other.position = Vec2(MAGE_AT.x, MAGE_AT.y - 70)

    troop = run(world, tick=1)

    assert [a.unit_id for a in troop.coordination.assignments] == [assigned]


def test_the_commitment_is_re_judged_once_its_window_has_passed() -> None:
    world = guarded_world(guarded(summons=3), library=strength_library("m", METHODICAL))
    run(world)
    assigned = troop_of(world).coordination.assignments[0].unit_id

    other = next(u for u in world.units if u.id.startswith("s") and u.id != assigned)
    other.position = Vec2(MAGE_AT.x, MAGE_AT.y - 70)

    window = profile_for(troop_of(world), world, SECONDS_PER_TICK).commitment_ticks
    troop = run(world, tick=window)

    assert [a.unit_id for a in troop.coordination.assignments] == [other.id]


def test_two_mages_asking_for_the_same_habit_compose_rather_than_collide() -> None:
    """Summation, not precedence — the same rule the weights follow."""
    units = guarded(summons=2)
    units.append(make_unit("m2", ADEPT, "north", Vec2(MAGE_AT.x + 30, MAGE_AT.y)))
    library = BehaviorLibrary(
        personalities=SAMPLE_PERSONALITIES,
        mage_personalities=(
            MagePersonality("m", (PersonalityRef(PROTECTIVE, strength=0.5),)),
            MagePersonality("m2", (PersonalityRef(PROTECTIVE, strength=0.5),)),
        ),
    )
    world = guarded_world(units, library)

    doubled = profile_for(troop_of(world), world, SECONDS_PER_TICK)
    single = profile_for(
        troop_of(world := guarded_world(library=strength_library("m", PROTECTIVE, strength=0.5))),
        world,
        SECONDS_PER_TICK,
    )

    assert doubled.guard_radius > single.guard_radius


# --- in a running battle ----------------------------------------------------


def test_a_real_battle_allocates_defenders_and_keeps_them_in_the_snapshot() -> None:
    """The coordinator is not only reachable from a unit test.

    Assignments are commitment state, so a replay that could not see them would
    not be a replay. This asserts both halves at once: the placeholder armies
    really do produce allocations over ninety seconds, and the per-tick snapshot
    carries them rather than only the live world holding them.
    """
    battle = placeholder_battle()
    battle.behavior = placeholder_behavior()

    result = run_battle(TWO_LANE_MAP, [], battle, 7)

    assignments = [
        assignment
        for entry in result.ticks
        for troop in entry.state.troops
        for assignment in troop.coordination.assignments
    ]
    assert assignments
    assert all(a.unit_id != a.protecting_id for a in assignments)


def test_a_battle_that_ships_no_behavior_data_coordinates_nothing() -> None:
    """The same fallback every other part of the behavior layer keeps."""
    result = run_battle(TWO_LANE_MAP, [], placeholder_battle(), 7)

    assert not any(troop.coordination.assignments for entry in result.ticks for troop in entry.state.troops)
