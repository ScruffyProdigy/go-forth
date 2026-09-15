"""Burns and burning ground, ticking down after combat."""

from __future__ import annotations

import pytest

from app.sim.effects import AreaDamage, Burn, BurningGround, DamageProfile
from app.sim.resolution import Cast, apply_effects
from app.sim.statuses import BURNING_GROUND, BurnStatus, GroundHazard
from app.sim.types import Vec2
from tests.sim.fixtures_abilities import MID, context, field, phase, unit


def burning(world, ctx, effect: Burn):  # type: ignore[no-untyped-def]
    apply_effects((effect,), Cast(world=world, ctx=ctx, side="north", origin=MID))


# --- burn ------------------------------------------------------------------


def test_a_burn_bites_once_a_tick() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context()
    burning(world, ctx, Burn(radius=30, damage_per_second=20, duration_seconds=1))

    phase("statuses").run(world, ctx)

    assert victim.hp == 99


def test_a_burn_deals_its_per_second_rate_over_a_second_of_ticks() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context()
    burning(world, ctx, Burn(radius=30, damage_per_second=20, duration_seconds=1))

    for _ in range(ctx.config.tick_rate):
        phase("statuses").run(world, ctx)

    assert victim.hp == pytest.approx(80)


def test_a_burn_stops_when_its_duration_runs_out() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context()
    burning(world, ctx, Burn(radius=30, damage_per_second=20, duration_seconds=1))

    for _ in range(3 * ctx.config.tick_rate):
        phase("statuses").run(world, ctx)

    assert victim.hp == pytest.approx(80)
    assert victim.burn is None


def test_a_burn_lands_harder_on_a_mage_when_the_card_says_so() -> None:
    mage = unit("mage", "south", MID, kind="mage")
    world, ctx = field(mage), context()
    burning(world, ctx, Burn(radius=30, damage_per_second=20, duration_seconds=1, bonus_vs_mage=2.0))

    phase("statuses").run(world, ctx)

    assert mage.hp == 98


def test_a_burn_that_finishes_a_unit_reports_the_defeat() -> None:
    victim = unit("victim", "south", MID, hp=0.5)
    world, ctx = field(victim), context()
    burning(world, ctx, Burn(radius=30, damage_per_second=20, duration_seconds=1))

    phase("statuses").run(world, ctx)

    defeats = [event for event in ctx.emitter.events if event.type == "unitDefeated"]
    assert len(defeats) == 1
    assert defeats[0].swing.units_removed[0].unit_id == "victim"


def test_a_burn_names_whoever_lit_it_even_after_they_are_gone() -> None:
    arsonist = unit("arsonist", "north", Vec2(187.5, 280))
    victim = unit("victim", "south", MID, hp=0.5)
    world, ctx = field(arsonist, victim), context()
    apply_effects(
        (Burn(radius=30, damage_per_second=20, duration_seconds=1),),
        Cast(world=world, ctx=ctx, side="north", origin=MID, caster=arsonist),
    )
    world.units = [victim]

    phase("statuses").run(world, ctx)

    source = ctx.emitter.events[-1].actors.source
    assert source is not None and source.unit_id == "arsonist"


def test_a_burn_charges_nobodys_gauge_because_the_arsonist_may_be_dead() -> None:
    arsonist = unit("arsonist", "north", Vec2(187.5, 280), ability_id="blast")
    victim = unit("victim", "south", MID)
    world, ctx = field(arsonist, victim), context()
    apply_effects(
        (Burn(radius=30, damage_per_second=20, duration_seconds=1),),
        Cast(world=world, ctx=ctx, side="north", origin=MID, caster=arsonist),
    )
    arsonist.energy_meters["damageDealt"] = 0

    phase("statuses").run(world, ctx)

    assert arsonist.energy_meters["damageDealt"] == 0


def test_a_burn_does_feed_the_victims_damage_taken_meter() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context()
    burning(world, ctx, Burn(radius=30, damage_per_second=20, duration_seconds=1))

    phase("statuses").run(world, ctx)

    assert victim.energy_meters["damageTaken"] == 1


# --- burning ground --------------------------------------------------------


def ground(world, ctx, effect: BurningGround, side: str = "north") -> None:  # type: ignore[no-untyped-def]
    apply_effects((effect,), Cast(world=world, ctx=ctx, side=side, origin=MID))  # type: ignore[arg-type]


def test_burning_ground_damages_whoever_is_standing_in_it() -> None:
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(victim), context()
    ground(world, ctx, BurningGround(radius=30, damage_per_second=20, duration_seconds=2))

    phase("statuses").run(world, ctx)

    assert victim.hp == 99


def test_burning_ground_leaves_whoever_stepped_out_of_it_alone() -> None:
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(victim), context()
    ground(world, ctx, BurningGround(radius=30, damage_per_second=20, duration_seconds=2))
    victim.position = Vec2(187.5, 400)

    phase("statuses").run(world, ctx)

    assert victim.hp == 100


def test_burning_ground_catches_a_unit_that_walks_into_it_later() -> None:
    victim = unit("victim", "south", Vec2(187.5, 400))
    world, ctx = field(victim), context()
    ground(world, ctx, BurningGround(radius=30, damage_per_second=20, duration_seconds=2))

    phase("statuses").run(world, ctx)
    victim.position = Vec2(187.5, 300)
    phase("statuses").run(world, ctx)

    assert victim.hp == 99


def test_burning_ground_spares_the_side_that_laid_it() -> None:
    friend = unit("friend", "north", Vec2(187.5, 300))
    world, ctx = field(friend), context()
    ground(world, ctx, BurningGround(radius=30, damage_per_second=20, duration_seconds=2))

    phase("statuses").run(world, ctx)

    assert friend.hp == 100


def test_burning_ground_burns_out_and_is_swept_off_the_map() -> None:
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(victim), context()
    ground(world, ctx, BurningGround(radius=30, damage_per_second=20, duration_seconds=1))

    for _ in range(3 * ctx.config.tick_rate):
        phase("statuses").run(world, ctx)

    assert world.hazards == []
    assert victim.hp == pytest.approx(80)


def test_burning_ground_that_finishes_a_unit_reports_the_defeat() -> None:
    victim = unit("victim", "south", Vec2(187.5, 300), hp=0.5)
    world, ctx = field(victim), context()
    ground(world, ctx, BurningGround(radius=30, damage_per_second=20, duration_seconds=2))

    phase("statuses").run(world, ctx)

    defeats = [event for event in ctx.emitter.events if event.type == "unitDefeated"]
    assert len(defeats) == 1


def test_a_hazard_and_a_burn_both_bite_on_the_same_tick() -> None:
    victim = unit("victim", "south", Vec2(187.5, 300))
    world, ctx = field(victim), context()
    ground(world, ctx, BurningGround(radius=30, damage_per_second=20, duration_seconds=2))
    burning(world, ctx, Burn(radius=30, damage_per_second=20, duration_seconds=2))

    phase("statuses").run(world, ctx)

    assert victim.hp == 98


def test_the_status_types_are_what_the_world_actually_carries() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context()
    burning(world, ctx, Burn(radius=30, damage_per_second=6, duration_seconds=1))
    ground(world, ctx, BurningGround(radius=30, damage_per_second=6, duration_seconds=1))

    assert isinstance(victim.burn, BurnStatus)
    assert isinstance(world.hazards[0], GroundHazard)
    assert world.hazards[0].kind == BURNING_GROUND


def test_an_area_blast_and_a_burn_do_not_get_confused_for_each_other() -> None:
    """Area damage is immediate, burn is not. A card taking both should read
    as one blow now and a trickle after, not two blows now."""
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context()
    apply_effects(
        (
            AreaDamage(radius=30, damage=DamageProfile(amount=10)),
            Burn(radius=30, damage_per_second=20, duration_seconds=1),
        ),
        Cast(world=world, ctx=ctx, side="north", origin=MID),
    )

    assert victim.hp == 90
    phase("statuses").run(world, ctx)
    assert victim.hp == 89
