"""Placeholder armies for the headless demo and the determinism harness.

Names come from the design doc's provisional Fire roster (§7.4) so the printed
event stream reads like the game; the numbers are made up. Balance is not a v1
goal — these exist so there is something to run. JQ-288 says as much outright:
missing numbers are a configurable provisional value the implementer picks and
records, not a gate on the work. Every number below is one of those, and
JQ-185/307 replace them with the selected packages.

v1 is a Fire mirror (§7.4), and round 1 opens at the starting mage cap of three
(§4.3): three troops, one mage each, with their summons.

Each troop carries an order, because a troop without one cannot be built. The
two sides field **identical rosters under different orders** — north doubles up
on the west lane while south splits — which is the decision two lanes exist to
create, and which makes the demo produce a real score instead of the mirrored
tie the old stacked bands produced on every seed.

`PLACEHOLDER_UNIT_TYPES` carries no abilities, and the ability-bearing roster
below is a separate army. That split is a convenience rather than a rule: a
plain army with nothing but movement and auto-attacks is the fixture you want
when the thing under test is movement or auto-attacks, and it keeps the
headless demo's default run short. Either roster may grow an ability the day
someone needs one to.

It used to be a rule. This roster is what `tests/sim/golden_battles.json` was
captured from before the TypeScript sim was deleted, and giving these cards
gauges would have changed every one of those battles and retired the
port-fidelity check with them. That check had one job — catching a wrong
transliteration, which is still perfectly deterministic and so invisible to
every other test we have — and it did it. Slice B's derived formations moved
these units off their captured paths, so JQ-287 retired it, correctly. The RNG
vectors in `tests/sim/test_rng.py` are the part of that capture worth keeping:
mulberry32's sequence is what every saved seed and every replay rests on, and
pinning it constrains no gameplay.
"""

from __future__ import annotations

from app.sim.abilities import Ability
from app.sim.effects import (
    ORIGIN_SELF,
    AreaDamage,
    Burn,
    BurningGround,
    DamageProfile,
    DashToTarget,
    EnergyRefill,
    Knockback,
)
from app.sim.orders import PUSH_ENEMY_BASE, Order, hold
from app.sim.spells import Spell, SpellInjection
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


#: Round 1 orders. Identical rosters, different plans: north commits two troops
#: to the west lane and south takes one lane each, so west is a fight and east
#: is south's to hold until someone contests it.
OPENING_ORDERS: dict[Side, list[str]] = {
    "north": ["W", "W", "push"],
    "south": ["W", "E", "push"],
}


def _order(code: str) -> Order:
    return PUSH_ENEMY_BASE if code == "push" else hold(code)


def _fire_army(side: Side) -> ArmySetup:
    entourages = [
        [RosterEntry("cinder-hound", 2)],
        [RosterEntry("ash-ram"), RosterEntry("ember-sprite")],
        [RosterEntry("ember-sprite", 2)],
    ]

    return ArmySetup(
        side=side,
        troops=[
            TroopSetup(
                order=_order(code),
                mages=[RosterEntry("ember-adept")],
                summons=summons,
            )
            for code, summons in zip(OPENING_ORDERS[side], entourages, strict=True)
        ],
    )


def placeholder_battle() -> BattleSetup:
    """Two identical Fire armies under different plans — the v1 mirror match."""
    return BattleSetup(
        unit_types=PLACEHOLDER_UNIT_TYPES,
        armies=[_fire_army("north"), _fire_army("south")],
    )


# --- Slice C: the effect vocabulary, exercised ------------------------------
#
# One card per primitive, so the headless demo shows every one of them going
# off and a reader can see what the vocabulary actually buys. The costs below
# are provisional in exactly the sense JQ-288 describes: Fire charges one
# energy per point of damage dealt, so a 60-cost ability is "about four good
# swings", and an Artifice timer card at ten a second comes online at six.
#
# They were then nudged until every card on the demo roster actually gets its
# ability off inside a battle — a demo that never fires one of its primitives
# demonstrates nothing, and `test_ability_battle.py` holds that property. That
# is the whole of the balancing done here; JQ-185/307 pick the real numbers.

PLACEHOLDER_ABILITIES: list[Ability] = [
    Ability(
        id="cinder-nova",
        energy_cost=60,
        effects=(
            AreaDamage(radius=40, damage=DamageProfile(amount=14, bonus_vs_mage=1.5)),
            Burn(radius=40, damage_per_second=6, duration_seconds=3, spread_radius=22),
        ),
    ),
    Ability(
        id="pounce",
        # Reaches as far as it dashes. A dash ability left on the unit's own
        # weapon range can only ever acquire something already in reach, so
        # the dash has nothing to close and the card never fires — which is
        # exactly what happened before this line existed.
        range=70,
        # `stop_short` is deliberately inside the hound's own 16 range, and
        # JQ-287 confirmed it should stay that way. Their standoff rule — a
        # unit never *walks* into contact, so a front line holds instead of
        # collapsing into a scrum — is a rule about walking, not an invariant
        # over every way a position can change. A pounce that stopped politely
        # at weapon range would not be a pounce, and the invariant reading is
        # not available anyway: JQ-289's resummon places a unit at its mage,
        # which on a contested lane is inside enemy range the tick it appears.
        # Sprites overlapping at 12 units is a rendering input (JQ-243/294),
        # and a headless sim cannot see pixels. Do not "fix" this number.
        energy_cost=35,
        effects=(
            DashToTarget(max_distance=70, stop_short=12),
            AreaDamage(radius=18, damage=DamageProfile(amount=18, bonus_vs_mage=2.0)),
        ),
    ),
    Ability(
        id="kindle",
        energy_cost=60,
        origin=ORIGIN_SELF,
        effects=(EnergyRefill(radius=60, amount=15),),
    ),
    Ability(
        id="ram-charge",
        energy_cost=45,
        #: As above: the charge reaches as far as it travels.
        range=90,
        effects=(
            DashToTarget(max_distance=90, stop_short=10),
            Knockback(radius=30, distance=25),
            AreaDamage(radius=30, damage=DamageProfile(amount=20, bonus_vs_base=2.5)),
        ),
    ),
    Ability(
        id="molten-seep",
        energy_cost=60,
        origin=ORIGIN_SELF,
        effects=(BurningGround(radius=45, damage_per_second=9, duration_seconds=6),),
    ),
]

#: The same Fire cards as above, plus the two Artifice-shaped ones JQ-288 asks
#: for — an emplacement that holds ground, and the barricade primitive it is
#: built from. Artifice ships as content later; what matters here is that it
#: needs no code that is not already written.
ABILITY_UNIT_TYPES: list[UnitType] = [
    UnitType(
        id="ember-adept",
        kind="mage",
        schools=("fire",),
        max_hp=55,
        damage=7,
        range=90,
        speed=26,
        attack_cooldown_seconds=1.4,
        support_capacity=3,
        resummon_pace_seconds=8,
        ability_id="cinder-nova",
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
        ability_id="pounce",
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
        ability_id="kindle",
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
        ability_id="ram-charge",
    ),
    UnitType(
        id="slag-wall",
        kind="summon",
        # Dual Fire/Artifice, so the troop's Fire mage can support it and it
        # still charges off the Artifice timer — the "best rate per meter"
        # merge in `energy.py`, on a card rather than in a unit test.
        schools=("fire", "artifice"),
        max_hp=200,
        damage=0,
        range=0,
        speed=0,
        attack_cooldown_seconds=2,
        ability_id="molten-seep",
        emplacement=True,
        blocks_movement=True,
        block_radius=26,
    ),
]

PLACEHOLDER_SPELLS: list[Spell] = [
    Spell(
        id="meteor",
        effects=(
            AreaDamage(radius=55, damage=DamageProfile(amount=30, bonus_vs_base=1.5)),
            BurningGround(radius=55, damage_per_second=5, duration_seconds=4),
        ),
    ),
]


def _ability_army(side: Side) -> ArmySetup:
    # The same shape as `_fire_army`: hold the near zone, contest the middle,
    # send one troop at the wall.
    #
    # Which card goes in which troop is what makes the demo demonstrate
    # anything, and it is decided by the order rather than by taste. The
    # emplacement holds a lane, because a barricade that walks away from the
    # ground it is walling shows nothing. The hounds push, because Fire
    # charges off damage dealt and a melee summon parked on a zone nobody
    # attacks never charges at all — measured, not guessed: on the holding
    # troop their gauges ended the battle at a flat zero and `pounce` never
    # fired, at any cost.
    #
    # The ram pushes for the opposite reason, found when JQ-376 turned the
    # zones into lanes and put it into permanent contact on one. `ram-charge`
    # is a dash, and the default cast policy holds a dash while its target is
    # already inside weapon range — correctly, since the dash would buy
    # nothing. So the ram charged its gauge to 60 against a cost of 45 and
    # still never fired: it had energy and no gap to close. A card that needs
    # a gap belongs on a troop that is crossing ground, not holding it. No
    # cost was touched; the arrangement was the wrong thing, not the number.
    return ArmySetup(
        side=side,
        troops=[
            TroopSetup(
                order=hold("W"),
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("slag-wall"), RosterEntry("ember-sprite")],
            ),
            TroopSetup(
                order=hold("E"),
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("cinder-hound"), RosterEntry("ember-sprite")],
            ),
            TroopSetup(
                order=PUSH_ENEMY_BASE,
                mages=[RosterEntry("ember-adept")],
                summons=[RosterEntry("ash-ram"), RosterEntry("cinder-hound")],
            ),
        ],
    )


def ability_battle(spell_injections: list[SpellInjection] | None = None) -> BattleSetup:
    """The mirror match again, this time with gauges, abilities and a spell."""
    return BattleSetup(
        unit_types=ABILITY_UNIT_TYPES,
        armies=[_ability_army("north"), _ability_army("south")],
        abilities=PLACEHOLDER_ABILITIES,
        spells=PLACEHOLDER_SPELLS,
        spell_injections=list(spell_injections) if spell_injections else [],
    )
