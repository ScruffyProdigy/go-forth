"""Resonance — the endemic school limit (§4.11).

v1 is a mono-school Fire mirror, which means every one of these tests could pass
against a sim that ignored the school argument entirely and returned Fire's
numbers for everything. So a **synthetic second school** runs through the whole
file: Artifice mages and summons that no shipping roster contains, fielded at
counts that differ from Fire's, specifically so a per-school lookup that is not
really per-school fails here rather than in the first non-mirror match.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

import pytest

from app.sim.config import DEFAULT_SIM_CONFIG, to_ticks
from app.sim.context import TickContext, create_tick_context
from app.sim.map import TWO_LANE_MAP
from app.sim.orders import PUSH_ENEMY_BASE
from app.sim.phases.resummon import resummon_pace_ticks
from app.sim.resonance import STAT_AXES, SideResonanceCounts, count_resonance
from app.sim.rng import create_rng
from app.sim.run_battle import run_battle
from app.sim.schools import (
    DEFAULT_RESONANCE_CURVE,
    IDENTITY_MULTIPLIERS,
    SchoolConfig,
    resolve_school_multipliers,
    resolve_side_multipliers,
    resonance_step,
)
from app.sim.units import UnitType
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup, World, create_world
from tests.sim.fixtures_units import ARTIFICER, COG_SENTRY, FURNACE_GOLEM, HOUND, KINDLER, MACHINIST

CARDS = [KINDLER, HOUND, ARTIFICER, COG_SENTRY, MACHINIST, FURNACE_GOLEM]

WEAK = resonance_step(DEFAULT_RESONANCE_CURVE, 1)
PAR = resonance_step(DEFAULT_RESONANCE_CURVE, 3)
STRONG = resonance_step(DEFAULT_RESONANCE_CURVE, 4)


def troop(mage: str, mages: int = 1, summon: str | None = None, summons: int = 0) -> TroopSetup:
    return TroopSetup(
        order=PUSH_ENEMY_BASE,
        mages=[RosterEntry(mage, mages)],
        summons=[RosterEntry(summon, summons)] if summon and summons else [],
    )


def battle(
    north: list[TroopSetup],
    south: list[TroopSetup],
    cards: list[UnitType] | None = None,
) -> BattleSetup:
    return BattleSetup(
        unit_types=cards if cards is not None else CARDS,
        armies=[ArmySetup(side="north", troops=north), ArmySetup(side="south", troops=south)],
    )


def world_of(setup: BattleSetup) -> World:
    return create_world(TWO_LANE_MAP, setup, create_rng(5))


# --- counting ----------------------------------------------------------------


def test_counts_the_mages_of_each_school_a_side_deployed() -> None:
    counts = count_resonance(world_of(battle([troop("kindler", 3)], [troop("kindler")])))

    assert counts["north"]["fire"] == 3
    assert counts["south"]["fire"] == 1


def test_counts_each_side_on_its_own_roster() -> None:
    """Resonance is a property of a player's roster, not of the field — a Fire
    mirror at three a side is "Fire 3" for each player, never "Fire 6"."""
    counts = count_resonance(world_of(battle([troop("kindler", 3)], [troop("kindler", 3)])))

    assert counts["north"]["fire"] == 3
    assert counts["south"]["fire"] == 3


def test_counts_a_second_school_separately() -> None:
    setup = battle([troop("kindler", 2), troop("clockwork-artificer", 4)], [troop("kindler")])
    counts = count_resonance(world_of(setup))

    assert counts["north"]["fire"] == 2
    assert counts["north"]["artifice"] == 4


def test_a_dual_school_mage_counts_for_both_of_its_schools() -> None:
    counts = count_resonance(world_of(battle([troop("ember-machinist")], [troop("kindler")])))

    assert counts["north"]["fire"] == 1
    assert counts["north"]["artifice"] == 1


def test_summons_do_not_count_toward_resonance() -> None:
    """A school's strength is the mages backing it."""
    setup = battle([troop("kindler", 1, "cinder-hound", 4)], [troop("kindler")])
    counts = count_resonance(world_of(setup))

    assert counts["north"]["fire"] == 1


def test_a_school_nobody_fielded_counts_zero() -> None:
    counts = count_resonance(world_of(battle([troop("kindler")], [troop("kindler")])))

    assert counts["north"]["artifice"] == 0
    assert counts["north"]["necromancy"] == 0


# --- the curve ---------------------------------------------------------------


def test_the_curve_runs_weak_below_par_par_then_strong() -> None:
    steps = [resonance_step(DEFAULT_RESONANCE_CURVE, count) for count in (1, 2, 3, 4)]
    gains = [step.energy_gain_multiplier for step in steps]
    axes = [step.stat_axis_multiplier for step in steps]
    paces = [step.resummon_pace_multiplier for step in steps]

    assert gains == sorted(gains), "energy gain must rise with resonance"
    assert axes == sorted(axes), "the stat axis must rise with resonance"
    assert paces == sorted(paces, reverse=True), "seconds per resummon must fall as resonance rises"


def test_three_mages_is_par_and_scales_nothing() -> None:
    """ "Par" is the definition of unscaled — and what keeps the golden vectors,
    captured from a three-Fire-mage battle, meaningful."""
    assert PAR == IDENTITY_MULTIPLIERS


def test_a_school_nobody_fielded_sits_at_identity_rather_than_a_penalty() -> None:
    """§7.3: a dual card's second axis is inactive when that school is absent,
    not a handicap."""
    assert resonance_step(DEFAULT_RESONANCE_CURVE, 0) == IDENTITY_MULTIPLIERS


def test_counts_past_the_end_of_the_curve_read_its_last_step() -> None:
    assert resonance_step(DEFAULT_RESONANCE_CURVE, 9) == STRONG


def test_a_school_may_bring_its_own_curve() -> None:
    curve = (IDENTITY_MULTIPLIERS, resonance_step(DEFAULT_RESONANCE_CURVE, 4))
    table = resolve_school_multipliers([SchoolConfig(id="artifice", resonance=curve)], {"artifice": 1})

    assert table["artifice"] == STRONG
    assert table["fire"] == IDENTITY_MULTIPLIERS


def test_a_pinned_multiplier_overrides_the_curve() -> None:
    table = resolve_school_multipliers(
        [SchoolConfig(id="fire", multipliers={"stat_axis_multiplier": 3})],
        {"fire": 1},
    )

    assert table["fire"].stat_axis_multiplier == 3
    assert table["fire"].energy_gain_multiplier == WEAK.energy_gain_multiplier


def test_rejects_a_negative_resonance_count() -> None:
    with pytest.raises(ValueError, match="negative"):
        resonance_step(DEFAULT_RESONANCE_CURVE, -1)


def test_rejects_an_empty_curve() -> None:
    with pytest.raises(ValueError, match="at least one step"):
        resonance_step((), 1)


# --- the table ---------------------------------------------------------------


def test_the_table_gives_each_side_its_own_numbers() -> None:
    table = resolve_side_multipliers([], {"north": {"fire": 4}, "south": {"fire": 1}})

    assert table["north"]["fire"] == STRONG
    assert table["south"]["fire"] == WEAK


def test_a_side_s_schools_are_scaled_independently_of_each_other() -> None:
    table = resolve_side_multipliers([], {"north": {"fire": 1, "artifice": 4}})

    assert table["north"]["fire"] == WEAK
    assert table["north"]["artifice"] == STRONG


def test_the_table_cannot_be_rewritten_mid_battle() -> None:
    table = resolve_side_multipliers([], {"north": {"fire": 1}})

    with pytest.raises(TypeError):
        table["north"] = table["south"]  # type: ignore[index]


# --- applied: resummon pace --------------------------------------------------


def context_for(setup: BattleSetup) -> tuple[World, TickContext]:
    world = world_of(setup)
    resonance = count_resonance(world)
    ctx = create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([], resonance),
        rng=create_rng(5),
        resonance=resonance,
        unit_types=CARDS,
    )
    return world, ctx


def test_a_strong_school_rebuilds_faster_than_a_weak_one() -> None:
    strong, strong_ctx = context_for(battle([troop("kindler", 4)], [troop("kindler")]))
    weak, weak_ctx = context_for(battle([troop("kindler")], [troop("kindler")]))

    fast = resummon_pace_ticks(next(u for u in strong.units if u.side == "north"), strong_ctx)
    slow = resummon_pace_ticks(next(u for u in weak.units if u.side == "north"), weak_ctx)

    assert fast is not None and slow is not None
    assert fast < slow
    assert fast == to_ticks(4 * STRONG.resummon_pace_multiplier, DEFAULT_SIM_CONFIG)
    assert slow == to_ticks(4 * WEAK.resummon_pace_multiplier, DEFAULT_SIM_CONFIG)


def test_each_side_rebuilds_on_its_own_resonance() -> None:
    world, ctx = context_for(battle([troop("kindler", 4)], [troop("kindler")]))

    north = resummon_pace_ticks(next(u for u in world.units if u.side == "north"), ctx)
    south = resummon_pace_ticks(next(u for u in world.units if u.side == "south"), ctx)

    assert north is not None and south is not None and north < south


def test_a_dual_mage_rebuilds_on_its_stronger_school() -> None:
    """One weak half should not drag down the other (§4.11)."""
    setup = battle([troop("ember-machinist"), troop("clockwork-artificer", 3)], [troop("kindler")])
    world, ctx = context_for(setup)

    machinist = next(u for u in world.units if u.type_id == "ember-machinist")
    # Fire 1 (weak) but Artifice 4 — the machinist itself plus three artificers.
    expected = to_ticks(4 * STRONG.resummon_pace_multiplier, DEFAULT_SIM_CONFIG)
    assert resummon_pace_ticks(machinist, ctx) == expected


# --- the stat axis is declared, not applied -----------------------------------


def test_the_axis_table_records_which_stat_each_school_is_about() -> None:
    """§4.11's table, as design data for the effects that will read it."""
    assert STAT_AXES["fire"] == ("speed", "damage")
    assert STAT_AXES["artifice"] == ("range",)


def test_resonance_does_not_silently_rescale_the_units_on_the_field() -> None:
    """Ryan's call, 2026-09-15: resonance is a requirement or a per-effect
    scaling, never a flat multiplier on everything a school touches.

    A blanket multiplier is unreadable to a player — nothing on screen says why
    this Ember Adept hits for 8.8 — and it silently reaches every future effect.
    So a unit fields the stat block on its card, whatever its school's resonance.
    """
    weak = run_battle(TWO_LANE_MAP, [], battle([troop("kindler")], [troop("kindler", 4)]), 1)
    strong = run_battle(TWO_LANE_MAP, [], battle([troop("kindler", 4)], [troop("kindler")]), 1)

    for result in (weak, strong):
        for unit in result.ticks[0].state.units:
            if unit.type_id == "kindler":
                assert unit.damage == KINDLER.damage
                assert unit.speed == KINDLER.speed


def test_the_record_still_carries_the_axis_for_effects_to_scale_on() -> None:
    """Dropping the blanket application does not drop the number."""
    table = resolve_side_multipliers([], {"north": {"fire": 1}, "south": {"fire": 4}})

    assert table["north"]["fire"].stat_axis_multiplier == WEAK.stat_axis_multiplier
    assert table["south"]["fire"].stat_axis_multiplier == STRONG.stat_axis_multiplier


def test_a_dual_school_unit_has_an_axis_per_school_each_on_its_own_count() -> None:
    """The shape Ryan described: a two-school creature that gets faster from one
    of its schools and hits harder from the other, each on that school's own
    resonance rather than on a single blended number."""
    setup = battle([troop("ember-machinist"), troop("clockwork-artificer", 3)], [troop("kindler", 3)])
    result = run_battle(TWO_LANE_MAP, [], setup, 1)
    table = result.multipliers["north"]

    # Fire 1 from the machinist itself; Artifice 4 with the three artificers.
    assert result.resonance["north"]["fire"] == 1
    assert result.resonance["north"]["artifice"] == 4
    assert table["fire"].stat_axis_multiplier == WEAK.stat_axis_multiplier
    assert table["artifice"].stat_axis_multiplier == STRONG.stat_axis_multiplier
    assert STAT_AXES["fire"] == ("speed", "damage")
    assert STAT_AXES["artifice"] == ("range",)


def test_the_count_is_on_the_context_for_an_effect_to_require_or_scale_on() -> None:
    """A requirement is a comparison, not a scaling — "selectable at Fire 3"
    needs the number, which is why the context carries it (JQ-288, JQ-297)."""
    _, ctx = context_for(battle([troop("kindler", 3)], [troop("clockwork-artificer")]))

    assert ctx.resonance["north"]["fire"] == 3
    assert ctx.resonance["south"]["fire"] == 0
    assert ctx.resonance["south"]["artifice"] == 1
    assert ctx.resonance["north"]["fire"] >= 3, "a Fire-3 requirement is met here"


# --- once per battle ---------------------------------------------------------


def test_resonance_is_counted_exactly_once_for_a_whole_battle(monkeypatch: pytest.MonkeyPatch) -> None:
    """No passives, no per-tick recomputation (§4.11) — the number is what you
    deployed, which is what makes it a planning decision rather than a battle one."""
    # Reached through importlib rather than as an attribute: `app.sim.__init__`
    # rebinds the name `run_battle` on the package to the *function*, so
    # `app.sim.run_battle.count_resonance` finds nothing.
    module = importlib.import_module("app.sim.run_battle")
    calls = []
    original: Callable[[World], SideResonanceCounts] = module.count_resonance

    def spy(world: World) -> SideResonanceCounts:
        calls.append(world.tick)
        return original(world)

    monkeypatch.setattr(module, "count_resonance", spy)
    result = run_battle(TWO_LANE_MAP, [], battle([troop("kindler", 3)], [troop("kindler", 3)]), 1)

    assert calls == [0], "counted somewhere other than exactly once, on the opening world"
    assert result.final_state.tick > 1, "the battle has to have actually run for that to mean anything"


def test_a_mage_dying_does_not_weaken_its_school() -> None:
    setup = battle([troop("kindler", 3)], [troop("kindler", 3)])
    result = run_battle(TWO_LANE_MAP, [], setup, 1)

    assert result.multipliers["north"]["fire"] == PAR
    assert count_resonance(result.ticks[0].state)["north"]["fire"] == 3
