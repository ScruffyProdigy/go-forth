"""The explicit round fixtures the opening demo is played on.

JQ-309's scheduling note is the licence for every number here: *"If a numeric
value is missing, the implementer supplies a configurable provisional value,
records it, and proceeds."* These are those values, recorded. JQ-185/292/297/307
replace them with selected packages; nothing below is a balance claim.

They are **fixtures and not a catalogue**: one file, read once at round start,
with no database behind it. That is what lets the whole contract and session
surface be tested with no Postgres, which is what CI actually has.

The roster is built from `sim/fixtures.py`'s ability roster rather than
duplicating stat blocks. The plan layer adds what the sim has no opinion about —
display names, tags, support costs, and what a spell says on its card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.sim.fixtures import ABILITY_UNIT_TYPES, PLACEHOLDER_ABILITIES, PLACEHOLDER_SPELLS
from app.sim.map import TWO_LANE_MAP, MapConfig
from app.sim.spells import Spell
from app.sim.units import UnitType

#: Mages on the field in round 1 (design doc §4.3, the starting mage cap).
MAGE_CAP = 3

#: What a seat opens the round with. Provisional: enough for one cast of the one
#: spell in the fixture, so the demo can show a cast without waiting out a gauge.
STARTING_ENERGY = 40.0

#: Base magnitude of a spell before any fielded mage raises it, and what each
#: fielded mage carrying a tag the spell reads adds. These mirror the numbers
#: JQ-311's client fixture invented, so the two agree until JQ-297 replaces both.
BASE_MAGNITUDE = 30.0
PER_CONTRIBUTOR = 11.0


@dataclass(frozen=True, slots=True)
class MageOption:
    """A mage as the plan screen offers it."""

    id: str
    name: str
    schools: tuple[str, ...]
    #: Disciplines, roles and personality (§4.8). Distinct from school
    #: membership, and what player spells read.
    tags: tuple[str, ...]
    support_capacity: int
    #: Picking a mage is picking a troop shape — this is the shape (§3.2).
    default_entourage: tuple[str, ...]
    signature_spell_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "schools": list(self.schools),
            "tags": list(self.tags),
            "supportCapacity": self.support_capacity,
            "defaultEntourage": list(self.default_entourage),
        }
        if self.signature_spell_id is not None:
            payload["signatureSpellId"] = self.signature_spell_id
        return payload


@dataclass(frozen=True, slots=True)
class SummonOption:
    id: str
    name: str
    role: str
    schools: tuple[str, ...]
    #: A large summon fills more than one point of a mage's capacity (§10 #18).
    capacity_cost: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "schools": list(self.schools),
            "capacityCost": self.capacity_cost,
        }


@dataclass(frozen=True, slots=True)
class SpellOption:
    """A player spell, as the menu offers it before resolution."""

    id: str
    name: str
    cost: float
    text: str
    #: What must be true before this can be equipped. A spell reading a tag
    #: needs a *fielded* mage carrying it — a mage on the bench grants nothing,
    #: which is the whole reason troops are chosen before spells (§10 #31).
    requires: dict[str, Any] = field(default_factory=lambda: {"kind": "always"})
    #: The tags whose count among fielded mages sets this spell's numbers (§4.8).
    reads: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cost": self.cost,
            "text": self.text,
            "requires": dict(self.requires),
            "reads": list(self.reads),
        }


#: Display names and tags for the sim's ability roster. Keyed here rather than
#: on `UnitType` because the sim has no business knowing what a card is called.
MAGES: tuple[MageOption, ...] = (
    MageOption(
        id="ember-adept",
        name="Ember Adept",
        schools=("fire",),
        tags=("pyromancer", "aggressive"),
        support_capacity=3,
        default_entourage=("cinder-hound", "ember-sprite"),
        signature_spell_id="meteor",
    ),
)

SUMMONS: tuple[SummonOption, ...] = (
    SummonOption("cinder-hound", "Cinder Hound", role="cavalry", schools=("fire",)),
    SummonOption("ember-sprite", "Ember Sprite", role="support", schools=("fire",)),
    SummonOption("ash-ram", "Ash Ram", role="siege", schools=("fire",), capacity_cost=2),
    SummonOption("slag-wall", "Slag Wall", role="melee", schools=("fire", "artifice"), capacity_cost=2),
)

#: How many copies of each summon a side owns this round. A multiset: duplicates
#: and arbitrary counts are legal (JQ-286 AC).
SUMMON_COUNTS: dict[str, int] = {
    "cinder-hound": 4,
    "ember-sprite": 3,
    "ash-ram": 2,
    "slag-wall": 1,
}

SPELLS: tuple[SpellOption, ...] = (
    SpellOption(
        id="meteor",
        name="Meteor",
        cost=35.0,
        text="A burst of fire, and ground that keeps burning.",
        requires={"kind": "signature", "mageId": "ember-adept"},
        reads=("pyromancer",),
    ),
)

#: The two spell slots a seat takes into a round. `None` is a legal slot — a
#: player may take one spell, or none.
SPELL_SLOTS: int = 2


def unit_types() -> list[UnitType]:
    """The stat blocks a round's battle is built from."""
    return list(ABILITY_UNIT_TYPES)


def abilities() -> list[Any]:
    return list(PLACEHOLDER_ABILITIES)


def sim_spells() -> list[Spell]:
    """The sim-side spell catalogue: ids and effects, no names and no costs."""
    return list(PLACEHOLDER_SPELLS)


def map_config() -> MapConfig:
    return TWO_LANE_MAP


def mage_by_id(mage_id: str) -> MageOption | None:
    for mage in MAGES:
        if mage.id == mage_id:
            return mage
    return None


def summon_by_id(summon_id: str) -> SummonOption | None:
    for summon in SUMMONS:
        if summon.id == summon_id:
            return summon
    return None


def spell_by_id(spell_id: str) -> SpellOption | None:
    for spell in SPELLS:
        if spell.id == spell_id:
            return spell
    return None


def roster_json() -> dict[str, Any]:
    """The roster both seats plan from. A mirror: the demo is a Fire mirror (§7.4)."""
    return {
        "mages": [mage.to_json() for mage in MAGES],
        "summonCounts": dict(sorted(SUMMON_COUNTS.items())),
        "summons": {summon.id: summon.to_json() for summon in sorted(SUMMONS, key=lambda s: s.id)},
        "spells": [spell.to_json() for spell in SPELLS],
    }


def opening_plan_json(round_number: int, map_config_: MapConfig) -> dict[str, Any]:
    """The plan a seat is handed at the start of a round.

    A **legal suggested default**, not an empty screen: JQ-308's lifecycle rule
    is that a player who does nothing still fields an army, so the opening plan
    is one that would be accepted as-is. Three troops under three different
    orders — hold each lane, push the enemy base — because a default that
    stacked all three on one lane would make the demo's first battle a rout and
    teach a first-time player the wrong thing about orders.
    """
    lanes = [zone.id for zone in map_config_.zones]
    orders: list[dict[str, Any]] = [{"kind": "holdZone", "zoneId": lane} for lane in lanes]
    orders.append({"kind": "pushEnemyBase"})

    troops = []
    for index in range(MAGE_CAP):
        mage = MAGES[index % len(MAGES)]
        troops.append(
            {
                "mageId": mage.id,
                "summonIds": list(mage.default_entourage),
                "order": orders[index % len(orders)],
            }
        )

    return {
        "round": round_number,
        "mageCap": MAGE_CAP,
        "roster": roster_json(),
        "troops": troops,
        "spellSlots": ["meteor", None],
        "energy": STARTING_ENERGY,
    }
