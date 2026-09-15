"""Gauges filling, abilities firing, and the two things Artifice needs.

The energy-rule tests here are the other half of `test_energy.py`: that file
checks the arithmetic of a rule, this one checks that a gauge charged by each
of the two shipped rules actually reaches full and fires.
"""

from __future__ import annotations

import pytest

from app.sim.abilities import Ability, build_ability_catalog
from app.sim.casting import AimedCast, ability_ready
from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.effects import ORIGIN_SELF, AreaDamage, DamageProfile, DashToTarget, EnergyRefill
from app.sim.energy import DAMAGE_DEALT
from app.sim.schools import SchoolConfig
from app.sim.types import Vec2
from app.sim.units import UnitType, build_unit_type_catalog
from app.sim.world import Unit, is_resummonable, survives_round_end
from tests.sim.fixtures_abilities import MID, context, field, phase, unit

#: Every school trickles on a clock (§4.4), so a gauge gains this much each
#: tick before anything the unit actually did is counted. Spelled out rather
#: than folded into the expected totals below, which would make them read like
#: magic numbers.
TRICKLE_PER_TICK = 4 / DEFAULT_SIM_CONFIG.tick_rate

BLAST = Ability(
    id="blast",
    energy_cost=20,
    effects=(AreaDamage(radius=40, damage=DamageProfile(amount=7)),),
)
SELF_BLAST = Ability(
    id="self-blast",
    energy_cost=20,
    origin=ORIGIN_SELF,
    effects=(AreaDamage(radius=40, damage=DamageProfile(amount=7)),),
)


# --- the gauge -------------------------------------------------------------


def test_only_a_unit_with_an_ability_charges() -> None:
    plain = unit("plain", "north", MID)
    world, ctx = field(plain), context()

    phase("energy").run(world, ctx)

    assert plain.energy == 0


def test_a_fire_gauge_fills_off_damage_dealt() -> None:
    caster = unit("caster", "north", MID, ability_id="blast")
    world, ctx = field(caster), context(abilities=[BLAST])
    caster.energy_meters[DAMAGE_DEALT] = 11

    phase("energy").run(world, ctx)

    assert caster.energy == 11 + TRICKLE_PER_TICK


def test_an_artifice_gauge_fills_off_the_clock_with_nothing_happening() -> None:
    idler = unit("idler", "north", MID, schools=("artifice",), ability_id="blast")
    world, ctx = field(idler), context(abilities=[BLAST])

    for _ in range(ctx.config.tick_rate):
        phase("energy").run(world, ctx)

    assert idler.energy == pytest.approx(10)


def test_the_gauge_is_scaled_by_the_schools_energy_gain_multiplier() -> None:
    # A deep gauge, so the cap at full does not hide what the scaling did.
    deep = Ability(id="blast", energy_cost=500, effects=BLAST.effects)
    caster = unit("caster", "north", MID, ability_id="blast")
    world = field(caster)
    ctx = context(
        abilities=[deep],
        school_configs=[SchoolConfig(id="fire", multipliers={"energy_gain_multiplier": 3.0})],
    )
    caster.energy_meters[DAMAGE_DEALT] = 10

    phase("energy").run(world, ctx)

    assert caster.energy == (10 + TRICKLE_PER_TICK) * 3


def test_the_meters_are_drained_so_a_tick_is_never_paid_for_twice() -> None:
    caster = unit("caster", "north", MID, ability_id="blast")
    world, ctx = field(caster), context(abilities=[BLAST])
    caster.energy_meters[DAMAGE_DEALT] = 10

    phase("energy").run(world, ctx)
    phase("energy").run(world, ctx)

    # The 10 damage is paid once; the second tick adds only its trickle.
    assert caster.energy == pytest.approx(10 + 2 * TRICKLE_PER_TICK)


# --- the auto-cast ---------------------------------------------------------


def test_a_full_gauge_makes_the_ability_available_rather_than_firing_it() -> None:
    """The mechanic, stated: filling the bar arms the ability. Whether this
    tick is the moment to spend it is a decision, and it belongs to the
    behaviour layer — see `casting.py`."""
    caster = unit("caster", "north", MID, ability_id="blast")

    assert not ability_ready(caster, BLAST)

    caster.energy = BLAST.energy_cost

    assert ability_ready(caster, BLAST)


def test_a_gauge_that_reaches_full_stops_filling() -> None:
    """A held ability must not bank toward the next one, or holding would be
    quietly rewarded with a faster second cast."""
    caster = unit("caster", "north", MID, ability_id="blast")
    world, ctx = field(caster), context(abilities=[BLAST])
    caster.energy_meters[DAMAGE_DEALT] = 500

    phase("energy").run(world, ctx)

    assert caster.energy == BLAST.energy_cost


def test_a_ready_ability_is_held_while_the_policy_declines() -> None:
    """Declining is "not yet", not a refusal: the gauge stays full and the
    unit is asked again on the next tick."""

    class NeverNow:
        name = "neverNow"

        def aim(self, world, unit, ability, target):  # type: ignore[no-untyped-def]
            return None

    caster = unit("caster", "north", MID, ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 300))
    world = field(caster, victim)
    ctx = context(abilities=[BLAST], cast_policy=NeverNow())
    caster.energy = 20

    phase("abilities").run(world, ctx)
    phase("abilities").run(world, ctx)

    assert victim.hp == 100
    assert caster.energy == 20


def test_the_policy_decides_what_a_ready_ability_is_aimed_at() -> None:
    """The seam JQ-296/328 plugs into: the phase executes, the policy judges."""

    class AlwaysTheFarOne:
        name = "alwaysTheFarOne"

        def aim(self, world, unit, ability, target):  # type: ignore[no-untyped-def]
            far = max(
                (u for u in world.units if u.side != unit.side),
                key=lambda u: u.position.y,
            )
            return AimedCast(origin=far.position, target=far)

    caster = unit("caster", "north", MID, ability_id="blast")
    near = unit("near", "south", Vec2(187.5, 300))
    far = unit("far", "south", Vec2(187.5, 500))
    world = field(caster, near, far)
    ctx = context(abilities=[BLAST], cast_policy=AlwaysTheFarOne())
    caster.energy = 20

    phase("abilities").run(world, ctx)

    assert (near.hp, far.hp) == (100, 93)


def test_the_default_policy_holds_a_dash_against_something_already_in_reach() -> None:
    """A dash is for closing a gap. Spent on a target the unit could already
    hit it buys nothing, and the gauge could have carried it to the next
    fight — the cheap melee summon walking into your face is exactly the
    thing not to spend it on."""
    lunge = Ability(
        id="lunge",
        energy_cost=20,
        range=80,
        effects=(DashToTarget(max_distance=60), AreaDamage(radius=10, damage=DamageProfile(amount=7))),
    )
    hunter = unit("hunter", "north", MID, ability_id="lunge")
    prey = unit("prey", "south", Vec2(187.5, MID.y + 10))
    world, ctx = field(hunter, prey), context(abilities=[lunge])
    hunter.energy = 20

    phase("abilities").run(world, ctx)

    assert hunter.position == MID
    assert prey.hp == 100
    assert hunter.energy == 20


def test_the_default_policy_spends_a_dash_on_something_out_of_reach() -> None:
    lunge = Ability(
        id="lunge",
        energy_cost=20,
        range=80,
        effects=(DashToTarget(max_distance=60), AreaDamage(radius=10, damage=DamageProfile(amount=7))),
    )
    hunter = unit("hunter", "north", MID, ability_id="lunge")
    prey = unit("prey", "south", Vec2(187.5, MID.y + 50))
    world, ctx = field(hunter, prey), context(abilities=[lunge])
    hunter.energy = 20

    phase("abilities").run(world, ctx)

    assert hunter.position != MID
    assert prey.hp == 93


def test_a_full_gauge_casts_and_the_gauge_resets() -> None:
    caster = unit("caster", "north", MID, ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(caster, victim), context(abilities=[BLAST])
    caster.energy = 20

    phase("abilities").run(world, ctx)

    assert victim.hp == 93
    assert caster.energy == 0


def test_a_gauge_short_of_full_does_not_cast() -> None:
    caster = unit("caster", "north", MID, ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(caster, victim), context(abilities=[BLAST])
    caster.energy = 19.9

    phase("abilities").run(world, ctx)

    assert victim.hp == 100


def test_a_fire_gauge_auto_casts_once_enough_damage_has_been_dealt() -> None:
    """End to end under Fire's rule: charge, come up full, fire."""
    caster = unit("caster", "north", MID, ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(caster, victim), context(abilities=[BLAST])
    caster.energy_meters[DAMAGE_DEALT] = 20

    phase("energy").run(world, ctx)
    phase("abilities").run(world, ctx)

    assert victim.hp == 93
    assert caster.energy == 0


def test_an_artifice_gauge_auto_casts_once_its_timer_has_run() -> None:
    """The same, under the timer rule: two seconds at ten a second is twenty."""
    caster = unit("caster", "north", MID, schools=("artifice",), ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(caster, victim), context(abilities=[BLAST])

    for _ in range(2 * ctx.config.tick_rate):
        phase("energy").run(world, ctx)
    phase("abilities").run(world, ctx)

    assert victim.hp == 93
    assert caster.energy == 0


def test_a_cast_with_no_target_is_held_rather_than_wasted() -> None:
    caster = unit("caster", "north", MID, ability_id="blast")
    world, ctx = field(caster), context(abilities=[BLAST])
    caster.energy = 20

    phase("abilities").run(world, ctx)

    assert caster.energy == 20


def test_a_self_centred_cast_needs_no_target() -> None:
    caster = unit("caster", "north", MID, ability_id="self-blast")
    world, ctx = field(caster), context(abilities=[SELF_BLAST])
    caster.energy = 20

    phase("abilities").run(world, ctx)

    assert caster.energy == 0


def test_an_ability_can_reach_further_than_the_unit_swings() -> None:
    reaching = Ability(
        id="reach",
        energy_cost=20,
        range=200,
        effects=(AreaDamage(radius=10, damage=DamageProfile(amount=7)),),
    )
    caster = unit("caster", "north", MID, ability_id="reach")
    victim = unit("victim", "south", Vec2(187.5, 400))
    world, ctx = field(caster, victim), context(abilities=[reaching])
    caster.energy = 20

    phase("abilities").run(world, ctx)

    assert victim.hp == 93


def test_the_cast_is_emitted_with_the_card_that_fired_and_what_it_moved() -> None:
    caster = unit("caster", "north", MID, ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 300), hp=5)
    world, ctx = field(caster, victim), context(abilities=[BLAST])
    caster.energy = 20

    phase("abilities").run(world, ctx)

    casts = [event for event in ctx.emitter.events if event.type == "abilityCast"]
    assert len(casts) == 1
    assert casts[0].label == "blast"
    assert casts[0].actors.source is not None and casts[0].actors.source.unit_id == "caster"
    assert [ref.unit_id for ref in casts[0].swing.units_removed] == ["victim"]


def test_a_defeated_caster_does_not_get_a_last_cast_in() -> None:
    caster = unit("caster", "north", MID, ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(caster, victim), context(abilities=[BLAST])
    caster.energy, caster.hp = 20, 0

    phase("abilities").run(world, ctx)

    assert victim.hp == 100


def test_an_ability_refilling_an_ally_can_set_off_that_allys_cast() -> None:
    """Deterministic and intended: the chain runs in world order."""
    kindler = Ability(
        id="kindle", energy_cost=5, origin=ORIGIN_SELF, effects=(EnergyRefill(radius=60, amount=20),)
    )
    support = unit("support", "north", MID, ability_id="kindle")
    gunner = unit("gunner", "north", Vec2(187.5, 300), ability_id="blast")
    victim = unit("victim", "south", Vec2(187.5, 310))
    world, ctx = field(support, gunner, victim), context(abilities=[kindler, BLAST])
    support.energy = 5

    phase("abilities").run(world, ctx)

    assert victim.hp == 93


# --- emplacements ----------------------------------------------------------


def test_an_emplacement_must_be_a_summon_that_holds_position() -> None:
    with pytest.raises(ValueError, match="holds position"):
        build_unit_type_catalog(
            [
                UnitType(
                    id="wall",
                    kind="summon",
                    schools=("artifice",),
                    max_hp=200,
                    damage=0,
                    range=0,
                    speed=5,
                    attack_cooldown_seconds=1,
                    emplacement=True,
                )
            ]
        )


def test_an_emplacement_does_not_move() -> None:
    wall = unit("wall", "north", MID, speed=0, emplacement=True)
    world, ctx = field(wall), context()

    phase("movement").run(world, ctx)

    assert wall.position == MID


def test_an_emplacement_is_never_resummoned() -> None:
    wall = unit("wall", "north", MID, speed=0, emplacement=True)
    hound = unit("hound", "north", Vec2(100, 100))

    assert not is_resummonable(wall)
    assert is_resummonable(hound)


def test_an_emplacement_survives_round_end_while_its_mage_lives() -> None:
    mage = unit("mage", "north", MID, kind="mage")
    wall = unit("wall", "north", Vec2(100, 100), speed=0, emplacement=True)
    world = field(mage, wall)

    assert survives_round_end(wall, world)


def test_an_emplacement_does_not_survive_its_mage() -> None:
    mage = unit("mage", "north", MID, kind="mage")
    wall = unit("wall", "north", Vec2(100, 100), speed=0, emplacement=True)
    world = field(mage, wall)
    mage.hp = 0

    assert not survives_round_end(wall, world)


def test_an_ordinary_summon_does_not_survive_round_end() -> None:
    mage = unit("mage", "north", MID, kind="mage")
    hound = unit("hound", "north", Vec2(100, 100))
    world = field(mage, hound)

    assert not survives_round_end(hound, world)


# --- barricades ------------------------------------------------------------


def barricade(side: str, y: float) -> Unit:
    return unit(
        "wall",
        side,  # type: ignore[arg-type]
        Vec2(187.5, y),
        speed=0,
        emplacement=True,
        blocks_movement=True,
        block_radius=30,
    )


def test_a_barricade_stops_an_enemy_walking_through_it() -> None:
    """A south walker heads north up the lane, into a north wall. A 20-unit
    step would put it at 320, inside the disc; it is cut short at the edge."""
    wall = barricade("north", 300)
    walker = unit("walker", "south", Vec2(187.5, 340), speed=400)
    world, ctx = field(wall, walker), context()

    phase("movement").run(world, ctx)

    assert walker.position.y == 330


def test_a_barricade_lets_its_own_side_past() -> None:
    """The same geometry with the walker on the wall's own side: it walks on
    through, because walling your own troops in is nobody's mechanic."""
    wall = barricade("north", 340)
    friend = unit("friend", "north", Vec2(187.5, 300), speed=400)
    world, ctx = field(wall, friend), context()

    phase("movement").run(world, ctx)

    assert friend.position.y == 320


def test_a_barricade_must_declare_how_wide_it_is() -> None:
    with pytest.raises(ValueError, match="no block radius"):
        build_unit_type_catalog(
            [
                UnitType(
                    id="wall",
                    kind="summon",
                    schools=("artifice",),
                    max_hp=200,
                    damage=0,
                    range=0,
                    speed=0,
                    attack_cooldown_seconds=1,
                    blocks_movement=True,
                )
            ]
        )


def test_a_dead_barricade_blocks_nothing() -> None:
    wall = barricade("north", 300)
    walker = unit("walker", "south", Vec2(187.5, 340), speed=400)
    world, ctx = field(wall, walker), context()
    wall.hp = 0

    phase("movement").run(world, ctx)

    assert walker.position.y < 330


# --- the catalog -----------------------------------------------------------


def test_an_ability_with_no_effects_is_rejected() -> None:
    with pytest.raises(ValueError, match="no effects"):
        build_ability_catalog([Ability(id="nothing", energy_cost=10)])


def test_an_ability_that_is_full_at_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="full at zero"):
        build_ability_catalog([Ability(id="free", energy_cost=0, effects=BLAST.effects)])


def test_an_ability_defined_twice_is_rejected() -> None:
    with pytest.raises(ValueError, match="defined twice"):
        build_ability_catalog([BLAST, BLAST])


def test_an_unknown_cast_origin_is_rejected() -> None:
    with pytest.raises(ValueError, match="origin"):
        build_ability_catalog([Ability(id="odd", energy_cost=10, origin="sideways", effects=BLAST.effects)])


def test_two_overlapping_barricades_do_not_bounce_a_walker_into_one_of_them() -> None:
    """Deflecting per blocker in turn would let the second one's clamp push
    the unit back inside the first. The tightest cap on one direction cannot."""
    left = unit(
        "left", "north", Vec2(170, 300), speed=0, blocks_movement=True, block_radius=30, troop_id="north-t0"
    )
    right = unit(
        "right", "north", Vec2(205, 300), speed=0, blocks_movement=True, block_radius=30, troop_id="north-t0"
    )
    walker = unit("walker", "south", Vec2(187.5, 360), speed=600)
    world, ctx = field(left, right, walker), context()

    phase("movement").run(world, ctx)

    from app.sim.geometry import distance

    assert distance(walker.position, left.position) >= 30 - 1e-9
    assert distance(walker.position, right.position) >= 30 - 1e-9
