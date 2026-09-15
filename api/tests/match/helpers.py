"""Shared scaffolding for the match tests."""

from __future__ import annotations

from app.match import (
    OPENING_CATALOG,
    SINGLE_ROUND_TEST_PROFILE,
    MatchController,
    MatchProfile,
    PackageCatalog,
    new_match,
)
from app.sim import TWO_LANE_MAP, Side, UnitType

SEED = 20260915


def controller(
    profile: MatchProfile = SINGLE_ROUND_TEST_PROFILE,
    catalog: PackageCatalog = OPENING_CATALOG,
    seed: int = SEED,
) -> MatchController:
    return new_match(profile=profile, catalog=catalog, map_config=TWO_LANE_MAP, seed=seed)


def in_battle(**kwargs: object) -> MatchController:
    """A controller with both sides locked on their defaults, one tick in."""
    match: MatchController = controller(**kwargs)  # type: ignore[arg-type]
    for side in ("north", "south"):
        match.submit_plan(side, match.suggested(side))
    return match


def set_base_hp(match: MatchController, side: Side, hp: float) -> None:
    """Puts a base at a chosen HP mid-battle.

    Reaching into the world rather than playing a battle that happens to get
    there: the outcome policies under test are about *which* ending wins, and
    staging one by hand is the only way to put two of them on the same tick.
    """
    assert match.runner is not None
    match.runner.world.bases[side].hp = hp


def set_score(match: MatchController, side: Side, score: float) -> None:
    assert match.runner is not None
    match.runner.world.zone_score[side] = score


#: A mage that cannot support what its package fields, for the capacity check.
STRAINED_MAGE = UnitType(
    id="spent-adept",
    kind="mage",
    schools=("fire",),
    max_hp=55,
    damage=7,
    range=90,
    speed=26,
    attack_cooldown_seconds=1.4,
    support_capacity=1,
)

#: A summon no Fire mage can support, for the faction check.
STONE_SUMMON = UnitType(
    id="granite-ward",
    kind="summon",
    schools=("stone",),
    max_hp=90,
    damage=10,
    range=20,
    speed=30,
    attack_cooldown_seconds=1.2,
)
