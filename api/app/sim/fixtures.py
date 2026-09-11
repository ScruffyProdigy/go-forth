"""Placeholder armies for the headless demo and the determinism harness.

Names come from the design doc's provisional Fire roster (§7.4) so the printed
event stream reads like the game; the numbers are made up. Balance is not a v1
goal and certainly not slice A's — these exist so there is something to run.

v1 is a Fire mirror (§7.4), and round 1 opens at the starting mage cap of three
(§4.3): three troops, one mage each, with their summons.
"""

from __future__ import annotations

from app.sim.types import Side
from app.sim.units import UnitType
from app.sim.world import ArmySetup, BattleSetup, RosterEntry, TroopSetup

PLACEHOLDER_UNIT_TYPES: list[UnitType] = [
    UnitType(
        id="ember-adept",
        kind="mage",
        schools=("fire",),
        max_hp=55,
        damage=7,
        range=90,
        speed=26,
        attack_cooldown_seconds=1.4,
        support_capacity=2,
        resummon_pace_seconds=8,
    ),
    UnitType(
        id="cinder-hound",
        kind="summon",
        schools=("fire",),
        max_hp=70,
        damage=11,
        range=16,
        speed=62,
        attack_cooldown_seconds=0.9,
    ),
    UnitType(
        id="ember-sprite",
        kind="summon",
        schools=("fire",),
        max_hp=40,
        damage=9,
        range=70,
        speed=44,
        attack_cooldown_seconds=1.2,
    ),
    UnitType(
        id="ash-ram",
        kind="summon",
        schools=("fire",),
        max_hp=120,
        damage=16,
        range=18,
        speed=38,
        attack_cooldown_seconds=1.6,
    ),
]


def _fire_army(side: Side) -> ArmySetup:
    return ArmySetup(
        side=side,
        troops=[
            TroopSetup(
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("cinder-hound", 2)],
            ),
            TroopSetup(
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("ash-ram"), RosterEntry("ember-sprite")],
            ),
            TroopSetup(
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("ember-sprite", 2)],
            ),
        ],
    )


def placeholder_battle() -> BattleSetup:
    """Two identical Fire armies — the v1 mirror match."""
    return BattleSetup(
        unit_types=PLACEHOLDER_UNIT_TYPES,
        armies=[_fire_army("north"), _fire_army("south")],
    )
