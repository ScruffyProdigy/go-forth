"""Spell injection: an effect fired at a location by an external trigger."""

from __future__ import annotations

import pytest

from app.sim.effects import AreaDamage, BurningGround, DamageProfile, DashToTarget
from app.sim.fixtures import ability_battle
from app.sim.map import THREE_ZONE_MAP
from app.sim.phase import TickPhase
from app.sim.phases import TICK_PHASES
from app.sim.run_battle import run_battle
from app.sim.spells import Spell, SpellInjection, build_spell_catalog, schedule_injections
from app.sim.types import Vec2
from tests.sim.fixtures_abilities import MID, context, field, unit

METEOR = Spell(id="meteor", effects=(AreaDamage(radius=40, damage=DamageProfile(amount=25)),))
EMBERFALL = Spell(
    id="emberfall", effects=(BurningGround(radius=40, damage_per_second=5, duration_seconds=2),)
)


def phase(name: str) -> TickPhase:
    return next(p for p in TICK_PHASES if p.name == name)


def at(tick: int, spell_id: str = "meteor", location: Vec2 = MID, side: str = "north") -> SpellInjection:
    return SpellInjection(tick=tick, spell_id=spell_id, location=location, side=side)  # type: ignore[arg-type]


def test_a_spell_lands_on_the_tick_it_was_injected_for() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context(spells=[METEOR])
    world.pending_spells = [at(3)]
    world.tick = 3

    phase("spells").run(world, ctx)

    assert victim.hp == 75


def test_a_spell_scheduled_for_later_does_not_land_early() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context(spells=[METEOR])
    world.pending_spells = [at(9)]
    world.tick = 3

    phase("spells").run(world, ctx)

    assert victim.hp == 100
    assert world.pending_spells == [at(9)]


def test_a_spell_lands_once_and_is_taken_off_the_schedule() -> None:
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context(spells=[METEOR])
    world.pending_spells = [at(3)]
    world.tick = 3

    phase("spells").run(world, ctx)
    world.tick = 4
    phase("spells").run(world, ctx)

    assert victim.hp == 75
    assert world.pending_spells == []


def test_a_spell_goes_through_the_same_effect_machinery_as_an_ability() -> None:
    world, ctx = field(unit("victim", "south", MID)), context(spells=[EMBERFALL])
    world.pending_spells = [at(1, "emberfall")]

    phase("spells").run(world, ctx)

    assert len(world.hazards) == 1


def test_a_spell_is_emitted_with_its_id_and_what_it_moved() -> None:
    victim = unit("victim", "south", MID, hp=5)
    world, ctx = field(victim), context(spells=[METEOR])
    world.pending_spells = [at(1)]

    phase("spells").run(world, ctx)

    spells = [event for event in ctx.emitter.events if event.type == "spell"]
    assert len(spells) == 1
    assert spells[0].label == "meteor"
    assert spells[0].position == MID
    assert [ref.unit_id for ref in spells[0].swing.units_removed] == ["victim"]


def test_a_spell_has_no_caster_so_it_names_none_as_its_source() -> None:
    world, ctx = field(unit("victim", "south", MID)), context(spells=[METEOR])
    world.pending_spells = [at(1)]

    phase("spells").run(world, ctx)

    assert ctx.emitter.events[-1].actors.source is None


def test_a_spell_only_hits_the_other_side() -> None:
    enemy = unit("enemy", "south", MID)
    friend = unit("friend", "north", MID)
    world, ctx = field(enemy, friend), context(spells=[METEOR])
    world.pending_spells = [at(1)]

    phase("spells").run(world, ctx)

    assert (enemy.hp, friend.hp) == (75, 100)


def test_an_effect_that_needs_a_caster_does_nothing_for_a_spell() -> None:
    dash = Spell(id="lunge", effects=(DashToTarget(max_distance=50),))
    victim = unit("victim", "south", MID)
    world, ctx = field(victim), context(spells=[dash])
    world.pending_spells = [at(1, "lunge")]

    phase("spells").run(world, ctx)

    assert victim.position == MID


def test_a_spell_charges_nobodys_gauge() -> None:
    """JQ-288: player spells do not gain school-resonance strength scaling, and
    they are not a unit's aggression either — nothing on the field is paid."""
    enemy = unit("enemy", "south", MID, ability_id="blast")
    friend = unit("friend", "north", Vec2(187.5, 320), ability_id="blast")
    world, ctx = field(enemy, friend), context(spells=[METEOR])
    world.pending_spells = [at(1)]

    phase("spells").run(world, ctx)

    assert friend.energy_meters["damageDealt"] == 0


def test_two_spells_on_one_tick_resolve_in_a_fixed_order() -> None:
    """Not whatever order the match layer happened to hand them over in."""
    forwards = schedule_injections(
        [at(4, "meteor"), at(4, "emberfall")], build_spell_catalog([METEOR, EMBERFALL])
    )
    backwards = schedule_injections(
        [at(4, "emberfall"), at(4, "meteor")], build_spell_catalog([METEOR, EMBERFALL])
    )

    assert forwards == backwards


def test_injections_are_ordered_by_tick() -> None:
    ordered = schedule_injections([at(9), at(2), at(5)], build_spell_catalog([METEOR]))

    assert [injection.tick for injection in ordered] == [2, 5, 9]


def test_an_injection_naming_a_spell_that_does_not_exist_is_rejected() -> None:
    with pytest.raises(ValueError, match="not in the spell catalog"):
        schedule_injections([at(1, "fireball")], build_spell_catalog([METEOR]))


def test_an_injection_before_the_first_tick_is_rejected() -> None:
    with pytest.raises(ValueError, match="tick 0 is the opening state"):
        schedule_injections([at(0)], build_spell_catalog([METEOR]))


def test_a_spell_with_no_effects_is_rejected() -> None:
    with pytest.raises(ValueError, match="no effects"):
        build_spell_catalog([Spell(id="nothing")])


def test_a_spell_injected_mid_battle_resolves_at_the_correct_tick() -> None:
    """The acceptance criterion, run through a whole battle rather than a
    staged field: the event lands on the tick the injection named."""
    injection = SpellInjection(tick=40, spell_id="meteor", location=Vec2(187.5, 290), side="north")
    result = run_battle(THREE_ZONE_MAP, [], ability_battle([injection]), 7)

    spells = [event for event in result.events if event.type == "spell"]
    assert [(event.tick, event.label) for event in spells] == [(40, "meteor")]
