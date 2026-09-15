"""Which ending wins, and who wins it.

The three policies Ryan settled on 2026-09-15 are the spine of this file: a
score tie breaks on remaining base HP, a missed plan auto-locks the default
(`test_controller.py`), and two bases falling on one tick is a draw.

Endings are staged by putting the world into the state under test rather than by
finding a battle that happens to reach it. That is the only way to put two
endings on the *same tick*, which is exactly where the precedence rules live.
"""

from __future__ import annotations

from app.match import (
    SINGLE_ROUND_TEST_PROFILE,
    MatchController,
    terminal_outcome,
    time_up_outcome,
)
from app.match.outcome import MATCH_ENDING
from app.sim import World
from tests.match.helpers import in_battle, set_base_hp, set_score

PROFILE = SINGLE_ROUND_TEST_PROFILE


def world() -> tuple[MatchController, World]:
    match = in_battle()
    match.advance(5)
    assert match.runner is not None
    return match, match.runner.world


# --- base outcomes ---------------------------------------------------------


def test_a_fallen_base_ends_the_match_not_the_round() -> None:
    match, state = world()
    set_base_hp(match, "south", 0)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.reason == "baseDestroyed"
    assert ending.winner == "north"
    assert ending.decided_by == "baseFell"
    assert ending.ends_match
    assert ending.destroyed_bases == ("south",)


def test_a_base_outcome_reports_what_both_bases_have_left() -> None:
    """Ryan, 2026-09-13: base destruction must not read as merely one round
    lost, and the client needs the remaining HP to say how close it was."""
    match, state = world()
    set_base_hp(match, "south", 0)
    set_base_hp(match, "north", 640)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.base_hp["north"] == 640
    assert ending.base_hp["south"] == 0


def test_a_fallen_base_beats_a_score_threshold_crossed_on_the_same_tick() -> None:
    """Precedence, and the one that matters: the side whose base just fell does
    not get to win on points for the same tick."""
    match, state = world()
    set_score(match, "south", PROFILE.score_threshold + 100)
    set_base_hp(match, "south", 0)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.reason == "baseDestroyed"
    assert ending.winner == "north"


def test_two_bases_falling_on_one_tick_is_a_draw_under_its_own_reason() -> None:
    """Ryan, 2026-09-15: symmetric event, symmetric result. Two spells can land
    on one tick and nothing serialises them, so this is reachable."""
    match, state = world()
    set_base_hp(match, "north", 0)
    set_base_hp(match, "south", 0)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.reason == "mutualBaseDestroyed"
    assert ending.winner is None
    assert ending.decided_by == "none"
    assert ending.ends_match
    assert ending.destroyed_bases == ("north", "south")


def test_a_mutual_destruction_does_not_quietly_become_a_north_win() -> None:
    """`sim.run_battle._base_destroyed` walks SIDES and would name north. That
    is an accident of iteration order rather than a policy, and this is the test
    that keeps it from leaking out as one."""
    match, state = world()
    set_base_hp(match, "north", 0)
    set_base_hp(match, "south", 0)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None and ending.winner is None


def test_both_base_reasons_end_the_match() -> None:
    assert {"baseDestroyed", "mutualBaseDestroyed"} == MATCH_ENDING


# --- score outcomes --------------------------------------------------------


def test_reaching_the_threshold_takes_the_round_outright() -> None:
    match, state = world()
    set_score(match, "south", PROFILE.score_threshold)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.reason == "scoreThreshold"
    assert ending.winner == "south"
    assert ending.decided_by == "score"
    assert not ending.ends_match


def test_a_round_below_the_threshold_simply_continues() -> None:
    match, state = world()
    set_score(match, "south", PROFILE.score_threshold - 1)
    assert terminal_outcome(state, PROFILE) is None


def test_time_up_is_decided_on_zone_score() -> None:
    match, state = world()
    set_score(match, "north", 400)
    set_score(match, "south", 380)

    ending = time_up_outcome(state, PROFILE)
    assert ending.reason == "timeUp"
    assert ending.winner == "north"
    assert ending.decided_by == "score"


def test_an_exact_score_tie_breaks_on_remaining_base_hp() -> None:
    """Ryan, 2026-09-15. Rewards the chip damage a pure score comparison throws
    away."""
    match, state = world()
    set_score(match, "north", 400)
    set_score(match, "south", 400)
    set_base_hp(match, "north", 900)
    set_base_hp(match, "south", 700)

    ending = time_up_outcome(state, PROFILE)
    assert ending.winner == "north"
    assert ending.decided_by == "baseHp"


def test_a_tie_on_score_and_on_base_hp_is_reported_as_a_draw() -> None:
    """Never invent a winner. A draw is a real answer."""
    match, state = world()
    set_score(match, "north", 400)
    set_score(match, "south", 400)
    set_base_hp(match, "north", 800)
    set_base_hp(match, "south", 800)

    ending = time_up_outcome(state, PROFILE)
    assert ending.winner is None
    assert ending.decided_by == "none"


def test_a_threshold_reached_by_both_on_one_tick_goes_to_the_higher_score() -> None:
    match, state = world()
    set_score(match, "north", PROFILE.score_threshold + 5)
    set_score(match, "south", PROFILE.score_threshold)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.reason == "scoreThreshold"
    assert ending.winner == "north"


def test_a_threshold_reached_by_both_at_an_identical_score_falls_to_base_hp() -> None:
    match, state = world()
    set_score(match, "north", PROFILE.score_threshold)
    set_score(match, "south", PROFILE.score_threshold)
    set_base_hp(match, "north", 500)
    set_base_hp(match, "south", 900)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.winner == "south"
    assert ending.decided_by == "baseHp"


# --- annihilation ----------------------------------------------------------


def test_a_side_wiped_out_loses_the_round_to_the_side_still_standing() -> None:
    _, state = world()
    state.units = [unit for unit in state.units if unit.side == "north"]

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.reason == "annihilation"
    assert ending.winner == "north"
    assert ending.decided_by == "standing"
    assert not ending.ends_match


def test_both_sides_wiped_out_on_one_tick_is_a_draw() -> None:
    _, state = world()
    state.units = []

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.reason == "annihilation"
    assert ending.winner is None


# --- reporting -------------------------------------------------------------


def test_every_outcome_carries_the_profile_label() -> None:
    """JQ-308: the test-profile label survives into session and UI reporting, so
    nobody mistakes a configured demo for production Starter."""
    match, state = world()
    set_base_hp(match, "south", 0)

    ending = terminal_outcome(state, PROFILE)
    assert ending is not None
    assert ending.profile_label == "single-round-test"
