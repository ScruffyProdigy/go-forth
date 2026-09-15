"""The round lifecycle: hidden plans, lock and reveal, casting, and the end.

What this file is really testing is that the server is authoritative — that
every question a client could lie about is answered here, and that a refused
request costs the player nothing.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.match import (
    SINGLE_ROUND_TEST_PROFILE,
    CastRejected,
    MatchController,
    Plan,
    PlanRejected,
    TroopPlan,
    base_hp_snapshot,
)
from app.sim import PUSH_ENEMY_BASE, Vec2, hold
from tests.match.helpers import controller, in_battle, set_base_hp

PROFILE = SINGLE_ROUND_TEST_PROFILE
MIDFIELD = Vec2(187.5, 290)


def types_of(match: MatchController, side: str) -> list[str]:
    assert match.runner is not None
    return [unit.type_id for unit in match.runner.world.units if unit.side == side]


def event_types(match: MatchController) -> list[str]:
    return [event.type for event in match.events]


# --- the menu and the opening state ---------------------------------------


def test_a_fresh_match_opens_in_planning_at_full_base_hp() -> None:
    """JQ-308: a fresh run initializes a new match; it is not a healing round
    transition."""
    match = controller()
    assert match.phase == "planning"
    assert base_hp_snapshot(match) == {"north": 1000, "south": 1000}


def test_a_match_can_be_opened_on_base_hp_carried_in() -> None:
    """The input half of "carry base HP in controller inputs and outputs".
    JQ-187 owns the multi-round reset matrix; this is the seam it needs."""
    profile = dataclasses.replace(PROFILE, base_hp={"north": 620.0, "south": 1000.0})
    match = controller(profile=profile)
    assert base_hp_snapshot(match) == {"north": 620, "south": 1000}

    for side in ("north", "south"):
        match.submit_plan(side, match.suggested(side))
    assert match.runner is not None
    assert match.runner.world.bases["north"].hp == 620


def test_the_menu_offers_the_five_packages() -> None:
    assert len(controller().available_packages) == PROFILE.packages_available


# --- hidden simultaneous plans --------------------------------------------


def test_your_own_plan_is_visible_to_you_the_moment_you_lock_it() -> None:
    match = controller()
    plan = match.suggested("north")
    match.submit_plan("north", plan)
    assert match.plan_for("north", "north") == plan


def test_the_opponents_plan_is_hidden_until_both_are_locked() -> None:
    """Simultaneity is the point of the plan phase (§6.1): a plan you can see is
    a plan you can answer."""
    match = controller()
    match.submit_plan("north", match.suggested("north"))

    assert not match.revealed
    assert match.plan_for("south", "north") is None


def test_both_plans_become_visible_at_the_reveal() -> None:
    match = controller()
    for side in ("north", "south"):
        match.submit_plan(side, match.suggested(side))

    assert match.revealed
    assert match.plan_for("south", "north") is not None
    assert match.plan_for("north", "south") is not None


def test_the_reveal_starts_the_battle() -> None:
    match = in_battle()
    assert match.phase == "battle"
    assert match.runner is not None
    assert "plansRevealed" in event_types(match)


def test_a_locked_plan_cannot_be_resubmitted() -> None:
    match = controller()
    match.submit_plan("north", match.suggested("north"))
    with pytest.raises(PlanRejected) as raised:
        match.submit_plan("north", match.suggested("north"))
    assert raised.value.reason == "alreadyLocked"


def test_a_plan_is_not_accepted_once_the_battle_has_started() -> None:
    match = in_battle()
    with pytest.raises(PlanRejected) as raised:
        match.submit_plan("north", match.suggested("north"))
    assert raised.value.reason == "wrongPhase"


def test_an_illegal_plan_does_not_lock() -> None:
    """A rejection leaves the side exactly where it was — still able to plan."""
    match = controller()
    with pytest.raises(PlanRejected):
        match.submit_plan("north", Plan(troops=(), spell_ids=()))
    assert not match.locked("north")
    assert match.phase == "planning"


def test_the_plan_decides_what_is_on_the_field() -> None:
    match = controller()
    chosen = Plan(
        troops=(
            TroopPlan("sprite-pair", hold("W")),
            TroopPlan("ram-guard", hold("E")),
            TroopPlan("skirmish", PUSH_ENEMY_BASE),
        ),
        spell_ids=("ember-surge", "scorch-line"),
    )
    match.submit_plan("north", chosen)
    match.submit_plan("south", match.suggested("south"))

    fielded = types_of(match, "north")
    assert fielded.count("ember-adept") == 3
    assert fielded.count("ember-sprite") == 3
    assert fielded.count("ash-ram") == 1


# --- the missed-plan policy ------------------------------------------------


def test_the_backstop_does_not_fire_early() -> None:
    """Deliberately generous, and not a countdown to play against."""
    match = controller()
    match.advance_planning(PROFILE.plan_backstop_seconds - 1)
    assert match.phase == "planning"
    assert not match.locked("north")


def test_a_player_who_never_plans_is_locked_to_the_suggested_default() -> None:
    """Ryan, 2026-09-15: auto-lock rather than forfeit, so an idle player loses
    on the field rather than on a technicality."""
    match = controller()
    match.submit_plan("north", match.suggested("north"))
    match.advance_planning(PROFILE.plan_backstop_seconds)

    assert match.phase == "battle"
    assert match.lock_source("south") == "default"
    assert match.plan_for("south", "south") == match.suggested("south")


def test_a_server_supplied_plan_is_reported_as_one() -> None:
    """The policy is explicit, so the demo should be able to say it happened."""
    match = controller()
    match.advance_planning(PROFILE.plan_backstop_seconds)

    assert match.lock_source("north") == "default"
    assert match.lock_source("south") == "default"
    locks = [event for event in match.events if event.type == "planLocked"]
    assert [event.data["source"] for event in locks] == ["default", "default"]


def test_a_player_who_did_plan_keeps_their_own_plan_at_the_backstop() -> None:
    match = controller()
    chosen = Plan(
        troops=(
            TroopPlan("skirmish", PUSH_ENEMY_BASE),
            TroopPlan("ram-guard", hold("W")),
            TroopPlan("sprite-pair", hold("E")),
        ),
        spell_ids=("ember-surge", "scorch-line"),
    )
    match.submit_plan("north", chosen)
    match.advance_planning(PROFILE.plan_backstop_seconds)

    assert match.lock_source("north") == "player"
    assert match.plan_for("north", "north") == chosen


def test_a_double_no_show_still_produces_a_battle() -> None:
    match = controller()
    match.advance_planning(PROFILE.plan_backstop_seconds)
    assert match.phase == "battle"
    outcome = match.run_round()
    assert outcome.reason in {"timeUp", "scoreThreshold", "annihilation", "baseDestroyed"}


# --- casting ---------------------------------------------------------------


def test_an_accepted_cast_spends_its_cost_and_lands_next_tick() -> None:
    match = in_battle()
    match.advance(200)
    pool = match.energy("north")
    assert pool is not None
    before = pool.current

    injection = match.cast_spell("north", "meteor", MIDFIELD)
    assert injection.tick == match.tick + 1
    assert pool.current == before - match.cost_of("meteor")


def test_an_accepted_cast_actually_lands() -> None:
    """The cast reaching the sim, not just the ledger. A controller that took
    the energy and forgot to inject would pass every other test in this file."""
    match = in_battle()
    match.advance(200)
    assert match.runner is not None
    before = [event for event in match.runner.events if event.type == "spell"]

    match.cast_spell("north", "meteor", MIDFIELD)
    match.advance(3)

    after = [event for event in match.runner.events if event.type == "spell"]
    assert len(after) == len(before) + 1


def test_a_spell_outside_the_round_loadout_is_refused_without_spending() -> None:
    """`cinder-wall` is a real spell the default loadout did not take."""
    match = in_battle()
    match.advance(200)
    pool = match.energy("north")
    assert pool is not None
    before = pool.current

    assert match.try_cast("north", "cinder-wall", MIDFIELD) == "notInLoadout"
    assert pool.current == before


def test_an_invented_spell_is_refused_without_spending() -> None:
    match = in_battle()
    match.advance(200)
    pool = match.energy("north")
    assert pool is not None

    assert match.try_cast("north", "no-such-spell", MIDFIELD) == "notInLoadout"
    assert pool.spent == 0


def test_a_cast_off_the_map_is_refused_without_spending() -> None:
    match = in_battle()
    match.advance(200)
    pool = match.energy("north")
    assert pool is not None

    assert match.try_cast("north", "meteor", Vec2(-40, 290)) == "offMap"
    assert pool.spent == 0


def test_a_cast_the_side_cannot_afford_is_refused_without_spending() -> None:
    match = in_battle()
    pool = match.energy("north")
    assert pool is not None
    assert pool.current < match.cost_of("meteor")

    assert match.try_cast("north", "meteor", MIDFIELD) == "unaffordable"
    assert pool.spent == 0
    assert pool.current == PROFILE.spell_energy_start


def test_a_stale_cast_is_refused_without_spending() -> None:
    """What a lagging client sends: a cast composed against a tick the battle
    has already passed. Checked rather than trusted."""
    match = in_battle()
    match.advance(200)
    pool = match.energy("north")
    assert pool is not None

    assert match.try_cast("north", "meteor", MIDFIELD, at_tick=match.tick - 5) == "stale"
    assert pool.spent == 0


def test_a_cast_at_the_current_tick_is_accepted() -> None:
    match = in_battle()
    match.advance(200)
    assert match.try_cast("north", "meteor", MIDFIELD, at_tick=match.tick) is None


def test_a_cast_during_planning_is_refused() -> None:
    match = controller()
    with pytest.raises(CastRejected) as raised:
        match.cast_spell("north", "meteor", MIDFIELD)
    assert raised.value.reason == "wrongPhase"


def test_each_side_spends_from_its_own_pool() -> None:
    match = in_battle()
    match.advance(200)
    north, south = match.energy("north"), match.energy("south")
    assert north is not None and south is not None

    match.cast_spell("north", "meteor", MIDFIELD)
    assert north.spent == match.cost_of("meteor")
    assert south.spent == 0


def test_energy_generates_at_the_profiles_rate() -> None:
    match = in_battle()
    pool = match.energy("north")
    assert pool is not None

    match.advance(match.profile.sim.tick_rate)
    expected = PROFILE.spell_energy_start + PROFILE.spell_energy_per_second
    assert pool.current == pytest.approx(expected)


def test_energy_is_capped() -> None:
    match = in_battle()
    pool = match.energy("north")
    assert pool is not None

    match.advance(1000)
    assert pool.current == PROFILE.spell_energy_cap


def test_the_books_balance_across_a_round_of_casting() -> None:
    """JQ-308 asks for energy accounting to be tested. `current` is derived from
    the two ledgers, so this is an assertion that neither ledger was skipped."""
    match = in_battle()
    pool = match.energy("north")
    assert pool is not None

    casts = 0
    while match.phase == "battle" and match.tick < 1200:
        match.advance(50)
        if match.phase == "battle" and match.try_cast("north", "meteor", MIDFIELD) is None:
            casts += 1

    assert casts > 0
    assert pool.spent == casts * match.cost_of("meteor")
    assert pool.current == PROFILE.spell_energy_start + pool.generated - pool.spent


# --- the battle runs on its own clock --------------------------------------


def test_the_battle_advances_with_no_client_input_at_all() -> None:
    """ "The battle continues during disconnect" — true by construction, since
    `advance` consults nothing."""
    match = in_battle()
    match.advance(400)
    assert match.tick == 400
    assert match.phase in {"battle", "complete"}


def test_a_round_reaches_a_terminal_outcome_on_its_own() -> None:
    match = in_battle()
    outcome = match.run_round()
    assert match.phase == "complete"
    assert outcome.profile_label == "single-round-test"


# --- after the end ---------------------------------------------------------


def test_base_destruction_ends_the_run_on_the_tick_it_happens() -> None:
    """Not a tick later, and not at the backstop."""
    match = in_battle()
    match.advance(10)
    set_base_hp(match, "south", 0)
    ended_at = match.tick

    match.advance(1)
    assert match.phase == "complete"
    assert match.outcome is not None
    assert match.outcome.tick == ended_at + 1


def test_nothing_is_accepted_once_a_base_has_fallen() -> None:
    """No further plan phase, no accepted battle command."""
    match = in_battle()
    match.advance(10)
    set_base_hp(match, "south", 0)
    match.advance(1)
    assert match.outcome is not None and match.outcome.reason == "baseDestroyed"

    with pytest.raises(CastRejected) as cast:
        match.cast_spell("north", "meteor", MIDFIELD)
    assert cast.value.reason == "matchOver"

    with pytest.raises(PlanRejected) as plan:
        match.submit_plan("north", match.suggested("north"))
    assert plan.value.reason == "wrongPhase"


def test_a_finished_match_does_not_advance() -> None:
    """No second round, and no fabricated later availability."""
    match = in_battle()
    match.advance(10)
    set_base_hp(match, "south", 0)
    match.advance(1)

    ended_at = match.tick
    match.advance(500)
    assert match.tick == ended_at
    assert len([event for event in match.events if event.type == "matchEnded"]) == 1


def test_the_end_is_reported_as_a_round_ending_and_a_match_ending() -> None:
    match = in_battle()
    match.advance(10)
    set_base_hp(match, "south", 0)
    match.advance(1)

    assert event_types(match)[-3:] == ["roundEnded", "matchEnded", "phaseChanged"]
    ended = next(event for event in match.events if event.type == "matchEnded")
    assert ended.data["ends_match"] is True
    assert ended.data["destroyed_bases"] == ["south"]
    assert ended.data["base_hp"]["south"] == 0


def test_an_ordinary_round_ending_is_not_reported_as_a_base_defeat() -> None:
    """Ryan, 2026-09-13, read the other way round: the ordinary ending must be
    distinguishable too, or the distinction buys nothing."""
    match = in_battle()
    outcome = match.run_round()

    if outcome.reason in {"baseDestroyed", "mutualBaseDestroyed"}:
        pytest.skip("this seed ends on a base, which the base tests already cover")
    ended = next(event for event in match.events if event.type == "matchEnded")
    assert ended.data["ends_match"] is False
    assert ended.data["destroyed_bases"] == []


def test_a_fresh_match_is_a_fresh_match() -> None:
    """Not a healing round transition: a new controller opens at full HP and
    zero score, whatever the last one ended on."""
    first = in_battle()
    first.advance(10)
    set_base_hp(first, "south", 5)
    first.run_round()

    second = in_battle()
    assert base_hp_snapshot(second) == {"north": 1000, "south": 1000}
    assert second.runner is not None
    assert second.runner.world.zone_score == {"north": 0, "south": 0}


def test_base_hp_is_readable_mid_battle_not_only_at_the_end() -> None:
    """The output half of "carry base HP in controller inputs and outputs"."""
    match = in_battle()
    match.advance(10)
    set_base_hp(match, "south", 742)
    assert base_hp_snapshot(match)["south"] == 742
