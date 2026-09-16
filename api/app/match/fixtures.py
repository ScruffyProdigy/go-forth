"""The explicit round fixtures the opening demo is played on.

JQ-309's scheduling note is the licence for every number here: *"If a numeric
value is missing, the implementer supplies a configurable provisional value,
records it, and proceeds."* These are those values, recorded. JQ-185/292/307
replace them with selected packages; nothing below is a balance claim.

They are **fixtures and not a catalogue**: one file, read once at round start,
with no database behind it. That is what lets the whole contract and session
surface be tested with no Postgres, which is what CI actually has.

The roster is built from `sim/fixtures.py`'s ability roster rather than
duplicating stat blocks. The plan layer adds what the sim has no opinion about —
display names, mage tags, support costs, and the spell definitions themselves.

Spells are `sim/spellbook.SpellDefinition`s since JQ-297, so what a spell costs
and does is stated once here and resolved once by `sim/loadout.py`. The
magnitudes the plan layer used to invent are gone with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.sim.effects import AreaDamage, BurningGround, DamageProfile, Knockback
from app.sim.fixtures import ABILITY_UNIT_TYPES, PLACEHOLDER_ABILITIES
from app.sim.loadout import DEFAULT_LOADOUT_RULES, LoadoutRules, definition_to_json
from app.sim.map import TWO_LANE_MAP, MapConfig
from app.sim.spellbook import (
    AlwaysAvailable,
    EffectScaling,
    IndependentAccess,
    SignatureOf,
    SpellDefinition,
    SpellDefinitionCatalog,
    build_definition_catalog,
)
from app.sim.units import UnitType

#: Mages on the field in round 1 (design doc §4.3, the starting mage cap).
MAGE_CAP = 3

#: What a seat opens the round with. Provisional: enough for one cast of the one
#: spell in the fixture, so the demo can show a cast without waiting out a gauge.
STARTING_ENERGY = 40.0

#: The spell policy this playtest runs under. An experiment, not a settled rule
#: of the game — see `sim/loadout.LoadoutRules`.
LOADOUT_RULES: LoadoutRules = DEFAULT_LOADOUT_RULES


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
    """A player spell as the menu offers it, wrapping its stable definition.

    A thin shell over `sim/spellbook.SpellDefinition` rather than a second copy
    of it. Before JQ-297 this carried its own `requires` dict and `reads` tuple
    and the plan layer re-derived a magnitude from them; both are now read off
    the definition, so there is exactly one statement of what a spell costs,
    what it does, and who may equip it.
    """

    definition: SpellDefinition

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def cost(self) -> float:
        return self.definition.cost

    def to_json(self) -> dict[str, Any]:
        """The card, as the roster sends it.

        The whole definition travels — access rule, base effects and per-effect
        curves. Not because the client is trusted with it (the server resolves
        the authoritative numbers either way), but because JQ-297 requires the
        client's local preview to be *the same calculation*, and a preview that
        was posted the answer instead of the inputs could not be conformance
        tested against the server at all.
        """
        return definition_to_json(self.definition)


#: Display names and tags for the sim's ability roster. Keyed here rather than
#: on `UnitType` because the sim has no business knowing what a card is called.
#: One mage card, because the sim ships one (`sim/fixtures.ABILITY_UNIT_TYPES`).
#: Filling the roster out is JQ-185/307's five Fire packages, not this ticket's:
#: a mage here with no `UnitType` behind it could be planned with and could not
#: be fielded. The tags are JQ-292's vocabulary rather than the ad-hoc
#: `pyromancer`/`aggressive` pair they replace.
MAGES: tuple[MageOption, ...] = (
    MageOption(
        id="ember-adept",
        name="Ember Adept",
        schools=("fire",),
        tags=("evocation", "reckless"),
        support_capacity=3,
        default_entourage=("cinder-hound", "ember-sprite"),
        signature_spell_id="fireball",
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

#: The provisional spell set the opening demo plans with.
#:
#: Three spells for three reasons, one per access rule JQ-292 defines, so that
#: the demo exercises each and the screen has something to show for each:
#:
#: * `fireball` is a **signature** — on the menu because an Ember Adept is
#:   fielded, and off it the moment none is. It is also the two-tag example
#:   JQ-292 asks to see: damage rises with `evocation`, radius with `reckless`,
#:   independently and each with its own cap.
#: * `ember-spark` is a **basic fallback**. Always there, scales with nothing,
#:   and is what an army with no mage still has to cast.
#: * `smoke-veil` is an **independent** roster spell. Gated twice — the side has
#:   to own it *and* field a `warding` mage — and with no warding mage in the
#:   one-card roster it stays greyed with its reason, which is the state the
#:   plan screen most needs to be able to draw.
#:
#: Every number is provisional under JQ-309's scheduling note, recorded here and
#: tuned from played battles. Caps are set so three mages — the round's cap —
#: land exactly on them: the late-cap value is reachable in a real plan rather
#: than only in a test.
SPELL_DEFINITIONS: tuple[SpellDefinition, ...] = (
    SpellDefinition(
        id="fireball",
        name="Fireball",
        cost=35.0,
        text="A burst of fire, and ground that keeps burning.",
        access=SignatureOf("ember-adept"),
        effects=(
            AreaDamage(radius=45, damage=DamageProfile(amount=28, bonus_vs_base=1.5)),
            BurningGround(radius=45, damage_per_second=5, duration_seconds=4),
        ),
        scaling=(
            EffectScaling(effect_index=0, field="damage.amount", tag="evocation", per_mage=8, cap=24),
            EffectScaling(effect_index=0, field="radius", tag="reckless", per_mage=6, cap=12),
            # A third curve, on a *different* effect, from a tag already read by
            # the first. Legal and deliberate: one number takes one curve, and
            # the burning ground's damage is not the blast's damage.
            EffectScaling(effect_index=1, field="damage_per_second", tag="evocation", per_mage=1.5, cap=4.5),
        ),
    ),
    SpellDefinition(
        id="ember-spark",
        name="Ember Spark",
        cost=12.0,
        text="A cheap jolt of flame.",
        access=AlwaysAvailable(),
        effects=(AreaDamage(radius=25, damage=DamageProfile(amount=12)),),
    ),
    SpellDefinition(
        id="smoke-veil",
        name="Smoke Veil",
        cost=20.0,
        text="A shove of hot smoke that scatters what is standing in it.",
        access=IndependentAccess(requires_tag="warding", minimum=1),
        effects=(Knockback(radius=40, distance=25),),
        scaling=(
            # Threshold 1: the first warding mage unlocks the spell and adds
            # nothing. The second is what starts moving the number, so "on the
            # menu" and "actually better" are separate states a playtest can see.
            EffectScaling(effect_index=0, field="distance", tag="warding", per_mage=5, cap=15, threshold=1),
        ),
    ),
)

SPELLS: tuple[SpellOption, ...] = tuple(SpellOption(definition) for definition in SPELL_DEFINITIONS)

#: The independent spells this side owns. Explicit data, per JQ-292: a spell
#: absent from this list is not eligible however the field is arranged, and no
#: tag ever adds to it. Preconstructed fills it; a constructed or draft mode
#: would fill it differently, which is the whole reason it is an input.
INDEPENDENT_SPELL_ACCESS: tuple[str, ...] = ("smoke-veil",)

#: The two spell slots a seat takes into a round. `None` is a legal slot — a
#: player may take one spell, or none. Read from the playtest rules rather than
#: declared twice.
SPELL_SLOTS: int = LOADOUT_RULES.slots


def unit_types() -> list[UnitType]:
    """The stat blocks a round's battle is built from."""
    return list(ABILITY_UNIT_TYPES)


def abilities() -> list[Any]:
    return list(PLACEHOLDER_ABILITIES)


def spell_definitions() -> SpellDefinitionCatalog:
    """The round's spell catalog, validated.

    Built on every call rather than at import: a definition with a mistyped
    field path raises from `build_definition_catalog`, and an import-time raise
    in a fixtures module takes the whole server down with a traceback that names
    the importer instead of the spell.
    """
    return build_definition_catalog(SPELL_DEFINITIONS)


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
        # What the side owns independently. Sent so the client's local preview
        # can grey a spell for the same reason the server would refuse it.
        "independentSpellAccess": list(INDEPENDENT_SPELL_ACCESS),
        "spellSlots": SPELL_SLOTS,
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
        "spellSlots": ["fireball", "ember-spark"],
        "energy": STARTING_ENERGY,
    }
