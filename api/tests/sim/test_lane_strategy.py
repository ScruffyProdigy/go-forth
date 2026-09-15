"""The reason the map was reshaped: farming a safe zone must not beat fighting.

The three stacked bands had a dominant strategy. A band next to your own
deployment strip was uncontested by default, so it paid you for doing nothing,
and both players collecting that symmetrically decided nothing at all. Measured
then, at seed 7: a mirror ended 1795-1795 on every seed, committing everything to
the contested middle *lost* by 1633, and turtling at home won by 2139.

These are the guards that the reshape actually fixed it, rather than a claim in a
commit message. They run whole battles because that is the only level the
property exists at — no single phase is wrong when farming beats fighting.
"""

from __future__ import annotations

from app.sim.fixtures import PLACEHOLDER_UNIT_TYPES
from app.sim.map import TWO_LANE_MAP
from app.sim.orders import DEFEND_BASE, PUSH_ENEMY_BASE, Order, hold
from app.sim.run_battle import BattleResult, run_battle
from app.sim.types import Side
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup

SEED = 7
#: One entourage per troop, so both sides field the same army whatever they do
#: with it. Any difference in score is a difference in plan.
ENTOURAGES = [
    [RosterEntry("cinder-hound", 2)],
    [RosterEntry("ash-ram"), RosterEntry("ember-sprite")],
    [RosterEntry("ember-sprite", 2)],
]
ORDERS: dict[str, Order] = {
    "W": hold("W"),
    "E": hold("E"),
    "defend": DEFEND_BASE,
    "push": PUSH_ENEMY_BASE,
}


def army(side: Side, plan: list[str]) -> ArmySetup:
    return ArmySetup(
        side=side,
        troops=[
            TroopSetup(order=ORDERS[code], mages=[RosterEntry("ember-adept")], summons=summons)
            for code, summons in zip(plan, ENTOURAGES, strict=True)
        ],
    )


def battle(north: list[str], south: list[str]) -> BattleResult:
    return run_battle(
        TWO_LANE_MAP,
        [],
        BattleSetup(
            unit_types=PLACEHOLDER_UNIT_TYPES,
            armies=[army("north", north), army("south", south)],
        ),
        SEED,
    )


def test_keeping_every_mage_at_home_scores_nothing() -> None:
    """The old layout paid a turtling side 3534 for standing still. Nothing is
    uncontested any more, so standing still is worth exactly what it earns."""
    result = battle(["defend", "defend", "defend"], ["W", "E", "push"])

    assert result.final_state.zone_score["north"] == 0


def test_and_loses_to_a_side_that_goes_and_takes_the_lanes() -> None:
    result = battle(["defend", "defend", "defend"], ["W", "E", "push"])
    score = result.final_state.zone_score

    assert score["south"] > score["north"]


def test_a_round_where_neither_side_commits_a_mage_scores_for_nobody() -> None:
    """Push sends troops at the wall rather than onto a point. Two armies that
    both do it fight a whole battle for nothing, which is the scoring rule
    stated as plainly as it can be."""
    result = battle(["push", "push", "push"], ["push", "push", "push"])

    assert result.final_state.zone_score == {"north": 0, "south": 0}


def test_two_plans_that_both_contest_are_decided_by_the_fighting() -> None:
    """Not a tie, and not a blowout: the old middle band paid nobody while it was
    contested, so two sides that both fought scored 214 to 305 between them."""
    result = battle(["W", "W", "push"], ["W", "E", "push"])
    score = result.final_state.zone_score

    assert min(score.values()) > 0
    assert abs(score["north"] - score["south"]) < max(score.values()) / 2
