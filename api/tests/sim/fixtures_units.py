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
#: Quick and fragile, and it shoots. The creature that *can* give ground: faster
#: than the RAM below and slower than the HOUND above, which is what lets one
#: pair of tests show a kite working and the same kite failing with no flag
#: anywhere saying which is which (JQ-329).
SPRITE = UnitType(
    id="ember-sprite",
    kind="summon",
    schools=("fire",),
    max_hp=40,
    damage=9,
    range=70,
    speed=45,
    attack_cooldown_seconds=1,
)
#: Slow, tough, and it has to walk into contact. The thing a SPRITE outruns.
RAM = UnitType(
    id="ash-ram",
    kind="summon",
    schools=("fire",),
    max_hp=120,
    damage=16,
    range=18,
    speed=25,
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

#: A mage that rebuilds. Kept apart from ADEPT so the slice A tests keep running
#: against the sim they were written for — a mage with no pace never resummons.
KINDLER = UnitType(
    id="kindler",
    kind="mage",
    schools=("fire",),
    max_hp=60,
    damage=10,
    range=90,
    speed=30,
    attack_cooldown_seconds=1,
    support_capacity=2,
    resummon_pace_seconds=4,
)
#: A synthetic second school. v1 is a Fire mirror (§7.4), so without a card like
#: this every resonance test would read the same school's numbers and a lookup
#: that ignored the school entirely would pass.
ARTIFICER = UnitType(
    id="clockwork-artificer",
    kind="mage",
    schools=("artifice",),
    max_hp=60,
    damage=10,
    range=90,
    speed=30,
    attack_cooldown_seconds=1,
    support_capacity=2,
    resummon_pace_seconds=4,
)
COG_SENTRY = UnitType(
    id="cog-sentry",
    kind="summon",
    schools=("artifice",),
    max_hp=40,
    damage=20,
    range=20,
    speed=60,
    attack_cooldown_seconds=1,
)
#: A dual mage: counts for both of its schools (§4.1), and rebuilds on whichever
#: of them is stronger.
MACHINIST = UnitType(
    id="ember-machinist",
    kind="mage",
    schools=("fire", "artifice"),
    max_hp=60,
    damage=10,
    range=90,
    speed=30,
    attack_cooldown_seconds=1,
    support_capacity=2,
    resummon_pace_seconds=4,
)
#: A dual summon: carries both stat axes, each fed by its own school (§4.11).
FURNACE_GOLEM = UnitType(
    id="furnace-golem",
    kind="summon",
    schools=("fire", "artifice"),
    max_hp=120,
    damage=20,
    range=40,
    speed=30,
    attack_cooldown_seconds=1,
)
