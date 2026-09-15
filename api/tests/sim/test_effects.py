"""Every effect primitive, one at a time.

JQ-288 asks for exactly this — "every effect primitive in isolation" — because
the vocabulary is a contract. A roster that reduces to these primitives is only
safe to write if each one does what its name says on its own, without a battle
around it arranging for it to look right.
"""

from __future__ import annotations

import pytest

from app.sim.effects import (
    AreaDamage,
    Burn,
    BurningGround,
    DamageProfile,
    DashToTarget,
    EnergyRefill,
    Knockback,
)
from app.sim.geometry import distance
from app.sim.resolution import Cast, apply_effects
from app.sim.types import Vec2, opposing
from tests.sim.fixtures_abilities import MID, context, field, unit


def cast_at(world, origin: Vec2 = MID, **kwargs):  # type: ignore[no-untyped-def]
    return Cast(world=world, ctx=kwargs.pop("ctx", context()), side="north", origin=origin, **kwargs)


# --- dash-to-target --------------------------------------------------------


def test_dash_closes_on_the_target() -> None:
    hunter = unit("hunter", "north", Vec2(100, 200))
    prey = unit("prey", "south", Vec2(100, 300))
    world = field(hunter, prey)

    apply_effects((DashToTarget(max_distance=70),), cast_at(world, caster=hunter, target=prey))

    assert hunter.position == Vec2(100, 270)


def test_dash_stops_short_so_it_lands_in_reach_rather_than_inside() -> None:
    hunter = unit("hunter", "north", Vec2(100, 200))
    prey = unit("prey", "south", Vec2(100, 240))
    world = field(hunter, prey)

    apply_effects((DashToTarget(max_distance=70, stop_short=15),), cast_at(world, caster=hunter, target=prey))

    assert distance(hunter.position, prey.position) == pytest.approx(15)


def test_dash_never_overshoots_its_target() -> None:
    hunter = unit("hunter", "north", Vec2(100, 200))
    prey = unit("prey", "south", Vec2(100, 210))
    world = field(hunter, prey)

    apply_effects((DashToTarget(max_distance=500),), cast_at(world, caster=hunter, target=prey))

    assert hunter.position == Vec2(100, 210)


def test_dash_does_nothing_without_a_caster_because_a_spell_has_none() -> None:
    prey = unit("prey", "south", Vec2(100, 300))
    world = field(prey)

    apply_effects((DashToTarget(max_distance=70),), cast_at(world, target=prey))

    assert prey.position == Vec2(100, 300)


def test_an_emplacement_does_not_dash_because_it_holds_position() -> None:
    wall = unit("wall", "north", Vec2(100, 200), speed=0, emplacement=True)
    prey = unit("prey", "south", Vec2(100, 300))
    world = field(wall, prey)

    apply_effects((DashToTarget(max_distance=70),), cast_at(world, caster=wall, target=prey))

    assert wall.position == Vec2(100, 200)


# --- area damage, and the two bonuses that ride on it ----------------------


def test_area_damage_hits_every_enemy_inside_the_radius() -> None:
    near = unit("near", "south", Vec2(187.5, 300))
    far = unit("far", "south", Vec2(187.5, 400))
    world = field(near, far)

    apply_effects((AreaDamage(radius=30, damage=DamageProfile(amount=12)),), cast_at(world))

    assert (near.hp, far.hp) == (88, 100)


def test_area_damage_leaves_the_casters_own_side_alone() -> None:
    friend = unit("friend", "north", Vec2(187.5, 295))
    world = field(friend)

    apply_effects((AreaDamage(radius=30, damage=DamageProfile(amount=12)),), cast_at(world))

    assert friend.hp == 100


def test_bonus_vs_mage_lands_harder_on_a_mage_than_on_a_summon() -> None:
    mage = unit("mage", "south", Vec2(187.5, 295), kind="mage")
    summon = unit("summon", "south", Vec2(187.5, 300))
    world = field(mage, summon)

    apply_effects(
        (AreaDamage(radius=30, damage=DamageProfile(amount=10, bonus_vs_mage=2.5)),), cast_at(world)
    )

    assert (mage.hp, summon.hp) == (75, 90)


def test_bonus_vs_base_lands_harder_on_a_base_than_the_blow_itself() -> None:
    world = field(unit("anyone", "south", Vec2(0, 0)))
    base = world.bases[opposing("north")]
    origin = base.position

    apply_effects(
        (AreaDamage(radius=30, damage=DamageProfile(amount=10, bonus_vs_base=3.0)),),
        cast_at(world, origin=origin),
    )

    assert base.hp == base.max_hp - 30


def test_a_blast_out_of_reach_of_the_base_leaves_it_alone() -> None:
    world = field(unit("anyone", "south", Vec2(0, 0)))
    base = world.bases["south"]

    apply_effects((AreaDamage(radius=30, damage=DamageProfile(amount=10)),), cast_at(world))

    assert base.hp == base.max_hp


def test_a_card_can_opt_out_of_hitting_the_base_at_all() -> None:
    world = field(unit("anyone", "south", Vec2(0, 0)))
    base = world.bases["south"]

    apply_effects(
        (AreaDamage(radius=30, damage=DamageProfile(amount=10), hits_base=False),),
        cast_at(world, origin=base.position),
    )

    assert base.hp == base.max_hp


def test_base_damage_is_reported_as_a_negative_swing() -> None:
    world = field(unit("anyone", "south", Vec2(0, 0)))
    base = world.bases["south"]

    outcome = apply_effects(
        (AreaDamage(radius=30, damage=DamageProfile(amount=10)),),
        cast_at(world, origin=base.position),
    )

    assert outcome.base_hp == {"south": -10}


def test_a_blast_that_finishes_a_unit_reports_it_and_emits_the_defeat() -> None:
    ctx = context()
    victim = unit("victim", "south", Vec2(187.5, 295), hp=5)
    world = field(victim)

    outcome = apply_effects(
        (AreaDamage(radius=30, damage=DamageProfile(amount=10)),), cast_at(world, ctx=ctx)
    )

    assert [ref.unit_id for ref in outcome.units_removed] == ["victim"]
    assert [event.type for event in ctx.emitter.events] == ["unitDefeated"]


# --- burn ------------------------------------------------------------------


def test_burn_leaves_a_status_rather_than_damaging_on_the_spot() -> None:
    victim = unit("victim", "south", Vec2(187.5, 295))
    world = field(victim)

    apply_effects((Burn(radius=30, damage_per_second=6, duration_seconds=3),), cast_at(world))

    assert victim.hp == 100
    assert victim.burn is not None and victim.burn.ticks_remaining == 60


def test_burn_spreads_one_hop_to_a_neighbour_of_the_unit_it_caught() -> None:
    caught = unit("caught", "south", Vec2(187.5, 295))
    neighbour = unit("neighbour", "south", Vec2(187.5, 310))
    world = field(caught, neighbour)

    apply_effects(
        (Burn(radius=10, damage_per_second=6, duration_seconds=3, spread_radius=20),), cast_at(world)
    )

    assert caught.burn is not None
    assert neighbour.burn is not None


def test_burn_spreads_exactly_one_hop_and_no_further() -> None:
    """A line of three: the blast catches the first, the first passes it to the
    second, and the third — adjacent to the second but not to the first — is
    untouched. A burn must not walk a packed rank end to end."""
    caught = unit("caught", "south", Vec2(187.5, 295))
    one_hop = unit("one-hop", "south", Vec2(187.5, 310))
    two_hops = unit("two-hops", "south", Vec2(187.5, 325))
    world = field(caught, one_hop, two_hops)

    apply_effects(
        (Burn(radius=10, damage_per_second=6, duration_seconds=3, spread_radius=20),), cast_at(world)
    )

    assert caught.burn is not None
    assert one_hop.burn is not None
    assert two_hops.burn is None


def test_a_burn_with_no_spread_radius_stays_where_it_landed() -> None:
    caught = unit("caught", "south", Vec2(187.5, 295))
    neighbour = unit("neighbour", "south", Vec2(187.5, 310))
    world = field(caught, neighbour)

    apply_effects((Burn(radius=10, damage_per_second=6, duration_seconds=3),), cast_at(world))

    assert caught.burn is not None
    assert neighbour.burn is None


def test_burn_does_not_spread_to_the_casters_own_side() -> None:
    caught = unit("caught", "south", Vec2(187.5, 295))
    friend = unit("friend", "north", Vec2(187.5, 305))
    world = field(caught, friend)

    apply_effects(
        (Burn(radius=10, damage_per_second=6, duration_seconds=3, spread_radius=20),), cast_at(world)
    )

    assert friend.burn is None


def test_a_second_burn_refreshes_rather_than_stacking() -> None:
    victim = unit("victim", "south", Vec2(187.5, 295))
    world = field(victim)
    weak = Burn(radius=30, damage_per_second=4, duration_seconds=1)
    strong = Burn(radius=30, damage_per_second=9, duration_seconds=5)

    apply_effects((strong,), cast_at(world))
    apply_effects((weak,), cast_at(world))

    assert victim.burn is not None
    assert victim.burn.damage_per_tick == pytest.approx(9 / 20)
    assert victim.burn.ticks_remaining == 100


# --- burning ground --------------------------------------------------------


def test_burning_ground_leaves_a_hazard_on_the_map() -> None:
    world = field(unit("victim", "south", Vec2(187.5, 295)))

    apply_effects((BurningGround(radius=40, damage_per_second=9, duration_seconds=6),), cast_at(world))

    assert len(world.hazards) == 1
    hazard = world.hazards[0]
    assert (hazard.center, hazard.radius, hazard.ticks_remaining) == (MID, 40, 120)


def test_two_burning_grounds_get_distinct_ids_without_touching_the_rng() -> None:
    ctx = context()
    world = field(unit("victim", "south", Vec2(187.5, 295)))
    ground = BurningGround(radius=40, damage_per_second=9, duration_seconds=6)
    before = ctx.rng.state

    apply_effects((ground,), cast_at(world, ctx=ctx))
    apply_effects((ground,), cast_at(world, ctx=ctx))

    assert [hazard.id for hazard in world.hazards] == ["hz0", "hz1"]
    # Minting an id off the RNG would shift every later draw in the battle.
    assert ctx.rng.state == before


# --- knockback -------------------------------------------------------------


def test_knockback_shoves_an_enemy_directly_away_from_the_origin() -> None:
    victim = unit("victim", "south", Vec2(187.5, 300))
    world = field(victim)

    apply_effects((Knockback(radius=30, distance=25),), cast_at(world))

    assert victim.position == Vec2(187.5, 325)


def test_knockback_leaves_an_emplacement_where_it_stands() -> None:
    wall = unit("wall", "south", Vec2(187.5, 300), speed=0, emplacement=True)
    world = field(wall)

    apply_effects((Knockback(radius=30, distance=25),), cast_at(world))

    assert wall.position == Vec2(187.5, 300)


def test_knockback_keeps_a_unit_on_the_map() -> None:
    victim = unit("victim", "south", Vec2(187.5, 560))
    world = field(victim)

    apply_effects((Knockback(radius=500, distance=100),), cast_at(world, origin=Vec2(187.5, 100)))

    assert victim.position.y == 569


def test_a_unit_standing_exactly_on_the_origin_is_not_shoved_at_random() -> None:
    victim = unit("victim", "south", MID)
    world = field(victim)

    apply_effects((Knockback(radius=30, distance=25),), cast_at(world))

    assert victim.position == MID


# --- energy refill ---------------------------------------------------------


def test_energy_refill_tops_up_nearby_allies() -> None:
    caster = unit("caster", "north", MID, ability_id="kindle")
    ally = unit("ally", "north", Vec2(187.5, 320), ability_id="pounce")
    world = field(caster, ally)

    apply_effects((EnergyRefill(radius=40, amount=20),), cast_at(world, caster=caster))

    assert ally.energy == 20


def test_energy_refill_excludes_the_caster_so_a_card_cannot_loop_on_itself() -> None:
    caster = unit("caster", "north", MID, ability_id="kindle")
    world = field(caster)

    apply_effects((EnergyRefill(radius=40, amount=20),), cast_at(world, caster=caster))

    assert caster.energy == 0


def test_energy_refill_can_be_declared_to_include_the_caster() -> None:
    caster = unit("caster", "north", MID, ability_id="kindle")
    world = field(caster)

    apply_effects((EnergyRefill(radius=40, amount=20, include_self=True),), cast_at(world, caster=caster))

    assert caster.energy == 20


def test_energy_refill_skips_an_ally_with_no_ability_to_spend_it_on() -> None:
    caster = unit("caster", "north", MID, ability_id="kindle")
    plain = unit("plain", "north", Vec2(187.5, 320))
    world = field(caster, plain)

    apply_effects((EnergyRefill(radius=40, amount=20),), cast_at(world, caster=caster))

    assert plain.energy == 0


def test_energy_refill_does_not_charge_the_enemy() -> None:
    caster = unit("caster", "north", MID, ability_id="kindle")
    enemy = unit("enemy", "south", Vec2(187.5, 320), ability_id="pounce")
    world = field(caster, enemy)

    apply_effects((EnergyRefill(radius=40, amount=20),), cast_at(world, caster=caster))

    assert enemy.energy == 0


# --- composition -----------------------------------------------------------


def test_effects_resolve_in_the_order_the_card_declares_them() -> None:
    """Dash then blast lands the blast where the dash ended, and that is the
    difference between a charge and a retreating shot."""
    hunter = unit("hunter", "north", Vec2(187.5, 200), ability_id="charge")
    prey = unit("prey", "south", Vec2(187.5, 300))
    world = field(hunter, prey)
    cast = Cast(
        world=world,
        ctx=context(),
        side="north",
        origin=hunter.position,
        caster=hunter,
        target=prey,
        follows_caster=True,
    )

    apply_effects(
        (
            DashToTarget(max_distance=100, stop_short=10),
            AreaDamage(radius=15, damage=DamageProfile(amount=10)),
        ),
        cast,
    )

    assert prey.hp == 90


def test_an_unknown_effect_is_rejected_rather_than_silently_skipped() -> None:
    world = field(unit("victim", "south", MID))

    with pytest.raises(ValueError, match="not a known effect primitive"):
        apply_effects(("definitely not an effect",), cast_at(world))  # type: ignore[arg-type]
