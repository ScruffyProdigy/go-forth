"""The loop in a running battle: deciding, and the phases that carry it out."""

from __future__ import annotations

from app.sim.ai.factors import FACTORS
from app.sim.ai.fixtures import AGGRESSIVE, DUTIFUL, SAMPLE_TRAITS
from app.sim.ai.objective import ObjectiveFixtures
from app.sim.ai.profiles import BehaviorLibrary, CreatureProfile, UnitBehavior
from app.sim.fixtures import placeholder_battle
from app.sim.map import THREE_ZONE_MAP
from app.sim.phases import TICK_PHASES
from app.sim.phases.combat import combat_phase
from app.sim.phases.decision import decision_phase
from app.sim.phases.movement import movement_phase
from app.sim.rng import create_rng
from app.sim.types import Vec2
from app.sim.world import World, create_world
from tests.sim.ai.helpers import attach, context, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND

MIDFIELD = Vec2(180, 300)
STATION = Vec2(180, 400)
TYPES = [ADEPT, HOUND]


def library(*profiles: CreatureProfile, **rest: object) -> BehaviorLibrary:
    return BehaviorLibrary(traits=SAMPLE_TRAITS, profiles=profiles, **rest)  # type: ignore[arg-type]


def at_station(world: World) -> None:
    world.objectives = ObjectiveFixtures(stations={troop.id: STATION for troop in world.troops})


# --- the phase commits, it does not act -------------------------------------


def test_a_unit_with_no_behavior_data_is_left_completely_alone() -> None:
    """A battle that ships no library has to behave exactly as slice A did."""
    world = create_world(THREE_ZONE_MAP, placeholder_battle(), create_rng(1))
    assert world.units

    decision_phase.run(world, context())

    assert all(unit.ai is None for unit in world.units)
    assert all(unit.destination is None for unit in world.units)


def test_deciding_records_an_intent_rather_than_moving_or_damaging_anything() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    enemy = make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))
    world = make_world([hound, enemy])
    attach(world, library(CreatureProfile("cinder-hound", traits=(AGGRESSIVE,))), TYPES)

    decision_phase.run(world, context())

    assert hound.ai is not None and hound.ai.intent is not None
    assert hound.position == MIDFIELD
    assert enemy.hp == HOUND.max_hp


def test_the_intent_carries_the_factor_contributions_for_diagnostics() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    attach(world, library(CreatureProfile("cinder-hound")), TYPES)

    decision_phase.run(world, context())

    assert hound.ai is not None and hound.ai.intent is not None
    assert tuple(c.factor for c in hound.ai.intent.contributions) == FACTORS


# --- movement and combat execute the intent ---------------------------------


def test_movement_walks_to_the_destination_the_decision_committed_to() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    at_station(world)
    attach(world, library(CreatureProfile("cinder-hound", {"objective_progress": 2.0})), TYPES)
    ctx = context()

    decision_phase.run(world, ctx)
    movement_phase.run(world, ctx)

    assert hound.position.y > MIDFIELD.y
    assert hound.position.y < STATION.y


def test_a_unit_that_decided_to_advance_moves_even_with_an_enemy_in_reach() -> None:
    """Slice A froze anything in weapon range. Pressing on is now a decision.

    Whether it is a *good* decision is the weights' business — what matters here
    is that the loop is allowed to make it, rather than the movement phase
    silently overruling it the way the old range check would have.
    """
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound, make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))])
    at_station(world)
    attach(
        world,
        library(
            CreatureProfile(
                "cinder-hound",
                {"objective_progress": 4.0, "target_suitability": 0.0, "danger": 0.0, "ally_support": 0.0},
            )
        ),
        TYPES,
    )
    ctx = context()

    decision_phase.run(world, ctx)
    movement_phase.run(world, ctx)

    assert hound.ai is not None and hound.ai.intent is not None
    assert hound.ai.intent.kind == "advance"
    assert hound.position != MIDFIELD


def test_a_unit_that_decided_to_attack_stands_its_ground() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound, make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))])
    at_station(world)
    attach(
        world,
        library(
            CreatureProfile(
                "cinder-hound",
                {"objective_progress": 0.0, "target_suitability": 4.0, "danger": 0.0, "ally_support": 0.0},
            )
        ),
        TYPES,
    )
    ctx = context()

    decision_phase.run(world, ctx)
    movement_phase.run(world, ctx)

    assert hound.ai is not None and hound.ai.intent is not None
    assert hound.ai.intent.kind == "attack"
    assert hound.position == MIDFIELD


def test_combat_swings_at_the_chosen_target_rather_than_the_nearest_one() -> None:
    """Without this the evaluator's choice of target would be quietly discarded."""
    adept = make_unit("a", ADEPT, "north", MIDFIELD)
    nearest = make_unit("e-near", HOUND, "south", Vec2(MIDFIELD.x + 5, MIDFIELD.y))
    wounded = make_unit("e-far", HOUND, "south", Vec2(MIDFIELD.x + 50, MIDFIELD.y), hp=1)
    world = make_world([adept, nearest, wounded])
    at_station(world)
    attach(
        world,
        library(
            CreatureProfile(
                "ember-adept",
                {"objective_progress": 0.0, "target_suitability": 4.0, "danger": 0.0, "ally_support": 0.0},
            )
        ),
        TYPES,
    )
    ctx = context()

    decision_phase.run(world, ctx)
    combat_phase.run(world, ctx)

    assert adept.ai is not None and adept.ai.intent is not None
    assert adept.ai.intent.target_id == "e-far"
    assert wounded.hp == 0
    assert nearest.hp == HOUND.max_hp


def test_a_chosen_target_that_left_reach_falls_back_to_the_nearest() -> None:
    """A commitment is preferred, not obeyed off the end of the world.

    The wounded one is chosen for its suitability, then walks out of reach
    between the decision and the swing. Combat must fall back to the enemy still
    standing in front of the adept rather than swinging at nothing.
    """
    adept = make_unit("a", ADEPT, "north", MIDFIELD)
    chosen = make_unit("e-chosen", HOUND, "south", Vec2(MIDFIELD.x + 50, MIDFIELD.y), hp=1)
    bystander = make_unit("e-near", HOUND, "south", Vec2(MIDFIELD.x + 5, MIDFIELD.y))
    world = make_world([adept, chosen, bystander])
    at_station(world)
    attach(
        world,
        library(
            CreatureProfile(
                "ember-adept",
                {"objective_progress": 0.0, "target_suitability": 4.0, "danger": 0.0, "ally_support": 0.0},
            )
        ),
        TYPES,
    )
    ctx = context()
    decision_phase.run(world, ctx)
    assert adept.ai is not None and adept.ai.intent is not None
    assert adept.ai.intent.target_id == "e-chosen"

    # Out past the adept's 90-unit reach, after the decision was made.
    chosen.position = Vec2(MIDFIELD.x + 400, MIDFIELD.y)
    combat_phase.run(world, ctx)

    assert chosen.hp == 1
    assert bystander.hp < HOUND.max_hp


# --- the ticket's scenario: same stats, different data -----------------------


def test_identical_creatures_with_different_traits_prefer_different_actions() -> None:
    """The acceptance scenario, and the reason none of this branches on an id.

    Two cinder hounds. Same card, same stats, same position, same enemy in
    reach, same tick. One is aggressive and one is dutiful, and that is the only
    difference anywhere in the inputs — no subclass, no creature-id check, no
    second code path.
    """
    keen = make_unit("north-t0-u0", HOUND, "north", MIDFIELD)
    dutiful = make_unit("north-t0-u1", HOUND, "north", MIDFIELD)
    world = make_world([keen, dutiful, make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))])
    at_station(world)
    attach(
        world,
        library(
            CreatureProfile("cinder-hound"),
            unit_behaviors=(
                UnitBehavior("north-t0-u0", traits=(AGGRESSIVE,)),
                UnitBehavior("north-t0-u1", traits=(DUTIFUL,)),
            ),
        ),
        TYPES,
    )

    decision_phase.run(world, context())

    assert keen.ai is not None and keen.ai.intent is not None
    assert dutiful.ai is not None and dutiful.ai.intent is not None
    assert keen.ai.intent.kind == "attack"
    assert dutiful.ai.intent.kind == "advance"


def test_the_two_hounds_differ_only_in_their_trait_data() -> None:
    """Guards the test above: if the stats diverged it would prove nothing."""
    keen = make_unit("north-t0-u0", HOUND, "north", MIDFIELD)
    dutiful = make_unit("north-t0-u1", HOUND, "north", MIDFIELD)

    for attribute in ("type_id", "max_hp", "damage", "range", "speed", "hp", "position", "side", "troop_id"):
        assert getattr(keen, attribute) == getattr(dutiful, attribute)


def test_the_decision_phase_is_in_the_battle_s_phase_list() -> None:
    assert decision_phase in TICK_PHASES
