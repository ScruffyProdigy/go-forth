"""Deciding when to spend an ability, rather than firing the moment it is ready.

A full gauge makes an ability available (JQ-288); this slice decides whether now
is the moment. The principle throughout is the tactical one: a creature with a
feature that gives it an edge would rather use that feature than swing — but
only when the circumstances suit it, and a feature spent on the wrong moment is
worse than an ordinary attack, because the gauge does not come back.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.sim.abilities import Ability, build_ability_catalog
from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.casting import FollowsIntent
from app.sim.ai.factors import FACTORS, freeze_weights
from app.sim.ai.intent import Intent, UnitAi
from app.sim.ai.observe import Observation, observe
from app.sim.ai.scoring import score_candidate, score_candidates
from app.sim.casting import FirstUsefulMoment
from app.sim.config import DEFAULT_SIM_CONFIG, seconds_per_tick
from app.sim.effects import ORIGIN_SELF, AreaDamage, DamageProfile, DashToTarget, EnergyRefill
from app.sim.map import TWO_LANE_MAP
from app.sim.types import Vec2
from app.sim.units import UnitType
from app.sim.world import Unit, World
from tests.sim.ai.helpers import make_unit, make_world

MIDFIELD = Vec2(180, 300)
TICK = seconds_per_tick(DEFAULT_SIM_CONFIG)
EVEN = freeze_weights({factor: 1.0 for factor in FACTORS})

POUNCE = Ability(
    id="pounce",
    energy_cost=40,
    range=70,
    effects=(
        DashToTarget(max_distance=70, stop_short=10),
        AreaDamage(radius=20, damage=DamageProfile(amount=15)),
    ),
)
NOVA = Ability(
    id="nova",
    energy_cost=60,
    origin=ORIGIN_SELF,
    effects=(AreaDamage(radius=40, damage=DamageProfile(amount=14)),),
)
KINDLE = Ability(
    id="kindle", energy_cost=30, origin=ORIGIN_SELF, effects=(EnergyRefill(radius=60, amount=15),)
)
CATALOG = build_ability_catalog([POUNCE, NOVA, KINDLE])

#: A hound that pounces. Short reach, so closing is what its ability is for.
POUNCER = UnitType(
    id="pouncer",
    kind="summon",
    schools=("fire",),
    max_hp=70,
    damage=11,
    range=16,
    speed=62,
    attack_cooldown_seconds=0.9,
    ability_id="pounce",
)
#: Same card, an ability that lands on itself.
NOVA_MAGE = UnitType(
    id="nova-mage",
    kind="mage",
    schools=("fire",),
    max_hp=55,
    damage=7,
    range=90,
    speed=26,
    attack_cooldown_seconds=1.4,
    support_capacity=2,
    ability_id="nova",
)
#: A ranged enemy: the thing a dash is really for.
ARCHER = UnitType(
    id="archer",
    kind="summon",
    schools=("fire",),
    max_hp=40,
    damage=9,
    range=90,
    speed=44,
    attack_cooldown_seconds=1.2,
)
#: A melee enemy: it was walking into contact anyway.
BITER = UnitType(
    id="biter",
    kind="summon",
    schools=("fire",),
    max_hp=40,
    damage=9,
    range=16,
    speed=44,
    attack_cooldown_seconds=1.2,
)


def look(world: World, unit: Unit) -> Observation:
    return observe(world, unit, TWO_LANE_MAP, TICK, CATALOG)


def caster(energy: float, unit_type: UnitType = POUNCER) -> Unit:
    unit = make_unit("north-t0-u0", unit_type, "north", MIDFIELD)
    unit.ability_id = unit_type.ability_id
    unit.energy = energy
    return unit


def kinds(candidates: Sequence[Candidate]) -> list[str]:
    return [candidate.kind for candidate in candidates]


# --- legality ---------------------------------------------------------------


def test_a_gauge_short_of_full_offers_no_cast_at_all() -> None:
    """Legality, not preference — the loop never scores the impossible."""
    unit = caster(energy=POUNCE.energy_cost - 1)
    world = make_world([unit, make_unit("e", ARCHER, "south", Vec2(MIDFIELD.x + 50, MIDFIELD.y))])

    assert "cast" not in kinds(generate_candidates(look(world, unit)))


def test_a_full_gauge_offers_one_cast_per_legal_target() -> None:
    unit = caster(energy=POUNCE.energy_cost)
    near = make_unit("e-near", ARCHER, "south", Vec2(MIDFIELD.x + 50, MIDFIELD.y))
    far = make_unit("e-far", ARCHER, "south", Vec2(MIDFIELD.x + 200, MIDFIELD.y))
    world = make_world([unit, near, far])

    casts = [c for c in generate_candidates(look(world, unit)) if c.kind == "cast"]

    # `pounce` reaches 70; the far one is outside it.
    assert [c.target_id for c in casts] == ["e-near"]
    assert all(c.ability_id == "pounce" for c in casts)


def test_a_unit_with_no_ability_never_casts() -> None:
    unit = make_unit("north-t0-u0", BITER, "north", MIDFIELD)
    world = make_world([unit, make_unit("e", ARCHER, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))])

    assert "cast" not in kinds(generate_candidates(look(world, unit)))


def test_an_ability_that_lands_on_the_caster_offers_exactly_one_cast() -> None:
    unit = caster(energy=NOVA.energy_cost, unit_type=NOVA_MAGE)
    world = make_world([unit, make_unit("e", ARCHER, "south", Vec2(MIDFIELD.x + 20, MIDFIELD.y))])

    casts = [c for c in generate_candidates(look(world, unit)) if c.kind == "cast"]

    assert len(casts) == 1
    assert casts[0].target_id is None


# --- what the dash is actually worth ----------------------------------------


def test_pouncing_on_a_ranged_enemy_beats_pouncing_on_a_melee_one() -> None:
    """The dash's value is what it takes *from the target*, not what it saves you.

    Against something that fights at your own reach, closing buys a moment — it
    was walking into contact regardless. Against something that out-ranges you,
    the gap is that creature's entire advantage, and closing takes it away.

    Both enemies here are identical but for `range`, and neither profile nor
    ability data says anything about either of them.
    """
    unit = caster(energy=POUNCE.energy_cost)
    ranged = make_unit("e-archer", ARCHER, "south", Vec2(MIDFIELD.x + 50, MIDFIELD.y))
    melee = make_unit("e-biter", BITER, "south", Vec2(MIDFIELD.x + 50, MIDFIELD.y + 1))
    world = make_world([unit, ranged, melee])
    observation = look(world, unit)
    casts = {c.target_id: c for c in generate_candidates(observation) if c.kind == "cast"}

    on_ranged = score_candidate(observation, casts["e-archer"], EVEN)
    on_melee = score_candidate(observation, casts["e-biter"], EVEN)

    assert on_ranged.score > on_melee.score


def test_a_dash_at_something_already_in_reach_scores_below_just_hitting_it() -> None:
    """The circumstances are wrong, so the feature is worth keeping.

    The dash would move the unit nowhere and the gauge would be gone. An
    ordinary attack does the same work and leaves the ability for a gap that
    actually needs closing.
    """
    unit = caster(energy=POUNCE.energy_cost)
    world = make_world([unit, make_unit("e", ARCHER, "south", Vec2(MIDFIELD.x + 8, MIDFIELD.y))])
    observation = look(world, unit)
    scored = {
        s.candidate.kind: s for s in score_candidates(observation, generate_candidates(observation), EVEN)
    }

    assert scored["cast"].score < scored["attack"].score


def test_an_area_ability_is_worth_more_the_more_it_covers() -> None:
    def score_with(enemies: int) -> float:
        unit = caster(energy=NOVA.energy_cost, unit_type=NOVA_MAGE)
        crowd = [
            make_unit(f"e{i}", BITER, "south", Vec2(MIDFIELD.x + 10 + i, MIDFIELD.y)) for i in range(enemies)
        ]
        world = make_world([unit, *crowd])
        observation = look(world, unit)
        cast = next(c for c in generate_candidates(observation) if c.kind == "cast")
        return score_candidate(observation, cast, EVEN).score

    assert score_with(3) > score_with(1)


# --- execution: the policy honours the decision ------------------------------


def test_the_policy_casts_what_the_loop_committed_to() -> None:
    unit = caster(energy=POUNCE.energy_cost)
    chosen = make_unit("e-far", ARCHER, "south", Vec2(MIDFIELD.x + 60, MIDFIELD.y))
    nearer = make_unit("e-near", ARCHER, "south", Vec2(MIDFIELD.x + 20, MIDFIELD.y))
    world = make_world([unit, chosen, nearer])
    unit.ai = UnitAi(intent=Intent(kind="cast", target_id="e-far", ability_id="pounce"))

    aimed = FollowsIntent().aim(world, unit, POUNCE, nearer)

    assert aimed is not None
    assert aimed.target is chosen


def test_the_policy_holds_when_the_loop_chose_something_else() -> None:
    """Otherwise the gauge, not the decision, would be in charge."""
    unit = caster(energy=POUNCE.energy_cost)
    enemy = make_unit("e", ARCHER, "south", Vec2(MIDFIELD.x + 20, MIDFIELD.y))
    world = make_world([unit, enemy])
    unit.ai = UnitAi(intent=Intent(kind="attack", target_id="e"))

    assert FollowsIntent().aim(world, unit, POUNCE, enemy) is None


def test_the_policy_holds_when_the_committed_target_is_gone() -> None:
    """Rather than substituting one: the loop picked that unit for reasons."""
    unit = caster(energy=POUNCE.energy_cost)
    corpse = make_unit("e-dead", ARCHER, "south", Vec2(MIDFIELD.x + 20, MIDFIELD.y), hp=0)
    other = make_unit("e-live", ARCHER, "south", Vec2(MIDFIELD.x + 25, MIDFIELD.y))
    world = make_world([unit, corpse, other])
    unit.ai = UnitAi(intent=Intent(kind="cast", target_id="e-dead", ability_id="pounce"))

    assert FollowsIntent().aim(world, unit, POUNCE, other) is None


def test_a_unit_with_no_behaviour_falls_through_to_the_old_policy() -> None:
    """A battle shipping no library casts exactly as it did before this existed."""
    unit = caster(energy=POUNCE.energy_cost)
    enemy = make_unit("e", ARCHER, "south", Vec2(MIDFIELD.x + 40, MIDFIELD.y))
    world = make_world([unit, enemy])
    assert unit.ai is None

    ours = FollowsIntent().aim(world, unit, POUNCE, enemy)
    theirs = FirstUsefulMoment().aim(world, unit, POUNCE, enemy)

    assert ours == theirs
    assert ours is not None
