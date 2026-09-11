"""Small unit types shared by the sim tests."""

from app.sim.units import UnitType

ADEPT = UnitType(
    id="ember-adept",
    kind="mage",
    schools=("fire",),
    max_hp=60,
    damage=10,
    range=90,
    speed=30,
    attack_cooldown_seconds=1,
    support_capacity=2,
)
HOUND = UnitType(
    id="cinder-hound",
    kind="summon",
    schools=("fire",),
    max_hp=40,
    damage=20,
    range=20,
    speed=60,
    attack_cooldown_seconds=1,
)
#: A mage that cannot fight back: makes "one side is wiped out" easy to stage.
WISP = UnitType(
    id="dying-wisp",
    kind="mage",
    schools=("fire",),
    max_hp=1,
    damage=0,
    range=0,
    speed=0,
    attack_cooldown_seconds=1,
    support_capacity=1,
)
