"""What a player picks from: five mage packages, each with a fixed entourage.

A **package** is the unit of choice in the opening round — one mage, the summons
that come with it, and the spells it makes eligible. The entourage is fixed by
the package rather than assembled by the player: that is what keeps the plan
phase to three taps on a phone (JQ-190), and it is why nothing here accepts a
roster.

Everything below is provisional in JQ-308's sense and JQ-307 replaces it. The
cards are the sim's own placeholder Fire roster, so no new unit numbers are
invented here; what is new is the *grouping* into five distinct options and the
spell costs, which no other ticket has yet supplied.

The five are built to be genuinely different rather than five ways to spell the
same troop, because a choose-three-of-five with three obvious picks is not a
choice. Two hounds is fast and fragile, the ram-and-sprite is slow and durable,
and the rest sit between them.

## Provisional spells

JQ-297 owns the real loadout (a multi-tag resolver over an eligible menu) and it
has not landed. Four stand-ins live here rather than in `sim/fixtures.py` on
purpose: the sim's fixtures are what the determinism harness and the headless
demo run on, and these are match-layer scaffolding with a known expiry. They use
the same effect vocabulary, so replacing them is a deletion rather than a port.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from app.sim import (
    PLACEHOLDER_UNIT_TYPES,
    AreaDamage,
    Burn,
    BurningGround,
    DamageProfile,
    Knockback,
    RosterEntry,
    Spell,
    UnitType,
    UnitTypeCatalog,
    build_unit_type_catalog,
)

#: Provisional player spells (JQ-297 replaces these outright).
PROVISIONAL_SPELLS: list[Spell] = [
    Spell(
        id="meteor",
        effects=(
            AreaDamage(radius=55, damage=DamageProfile(amount=30, bonus_vs_base=1.5)),
            BurningGround(radius=55, damage_per_second=5, duration_seconds=4),
        ),
    ),
    Spell(
        id="ember-surge",
        effects=(
            AreaDamage(radius=70, damage=DamageProfile(amount=16)),
            Burn(radius=70, damage_per_second=7, duration_seconds=3, spread_radius=20),
        ),
    ),
    Spell(
        id="cinder-wall",
        effects=(BurningGround(radius=48, damage_per_second=9, duration_seconds=6),),
    ),
    Spell(
        id="scorch-line",
        effects=(
            Knockback(radius=60, distance=34),
            AreaDamage(radius=60, damage=DamageProfile(amount=12, bonus_vs_mage=1.4)),
        ),
    ),
]

#: Per-spell overrides of `MatchProfile.default_spell_cost`. A spell absent here
#: costs the default. Provisional, and hand-set by shape rather than by measured
#: value: the wall is cheap because it denies ground instead of killing, and the
#: meteor is dear because it is the only one that meaningfully hits a base.
SPELL_COSTS: Mapping[str, float] = MappingProxyType(
    {
        "meteor": 55,
        "ember-surge": 40,
        "cinder-wall": 30,
        "scorch-line": 35,
    }
)


@dataclass(frozen=True)
class MagePackage:
    """One option on the five-package menu."""

    id: str
    #: What it reads as on the phone. Not load-bearing.
    name: str
    #: The mage card. One per package — a troop opens with exactly one mage.
    mage_type_id: str
    #: The summons that come with it, fixed. A player never edits this.
    entourage: tuple[RosterEntry, ...] = field(default_factory=tuple)
    #: The spells this package puts on the eligible menu. A plan's round loadout
    #: is drawn from the union of the packages it actually chose.
    spell_ids: tuple[str, ...] = field(default_factory=tuple)


#: The five on offer in the opening round. Every one fields `ember-adept`, whose
#: support capacity is 2 — which is what fixes every entourage at two summons.
FIVE_FIRE_PACKAGES: tuple[MagePackage, ...] = (
    MagePackage(
        id="hound-pair",
        name="Hound Pair",
        mage_type_id="ember-adept",
        entourage=(RosterEntry("cinder-hound", 2),),
        spell_ids=("meteor", "ember-surge"),
    ),
    MagePackage(
        id="ram-and-sprite",
        name="Ram and Sprite",
        mage_type_id="ember-adept",
        entourage=(RosterEntry("ash-ram"), RosterEntry("ember-sprite")),
        spell_ids=("meteor", "cinder-wall"),
    ),
    MagePackage(
        id="sprite-pair",
        name="Sprite Pair",
        mage_type_id="ember-adept",
        entourage=(RosterEntry("ember-sprite", 2),),
        spell_ids=("ember-surge", "cinder-wall"),
    ),
    MagePackage(
        id="ram-guard",
        name="Ram Guard",
        mage_type_id="ember-adept",
        entourage=(RosterEntry("ash-ram"), RosterEntry("cinder-hound")),
        spell_ids=("meteor", "scorch-line"),
    ),
    MagePackage(
        id="skirmish",
        name="Skirmish Pair",
        mage_type_id="ember-adept",
        entourage=(RosterEntry("cinder-hound"), RosterEntry("ember-sprite")),
        spell_ids=("ember-surge", "scorch-line"),
    ),
)


@dataclass(frozen=True)
class PackageCatalog:
    """The menu, plus the card data needed to check a plan against it.

    Carries its own unit types rather than reading a global, so that a test can
    offer a broken package (a mage that cannot support its own entourage) and
    watch the plan bounce.
    """

    packages: tuple[MagePackage, ...]
    unit_types: tuple[UnitType, ...]
    spells: tuple[Spell, ...]
    spell_costs: Mapping[str, float] = field(default_factory=lambda: SPELL_COSTS)

    @property
    def by_id(self) -> Mapping[str, MagePackage]:
        return MappingProxyType({package.id: package for package in self.packages})

    @property
    def types(self) -> UnitTypeCatalog:
        return build_unit_type_catalog(list(self.unit_types))

    def cost_of(self, spell_id: str, default: float) -> float:
        return self.spell_costs.get(spell_id, default)

    def eligible_spells(self, package_ids: Sequence[str]) -> tuple[str, ...]:
        """Every spell the chosen packages put on the menu, deduplicated.

        In menu order — the order of `packages`, then of each package's own
        list — rather than sorted or set-derived, so that the eligible menu a
        player is shown is stable across processes. See the hash-ordering note
        in `sim/rng.py`: a set would not be.
        """
        chosen = [pid for pid in package_ids if pid in self.by_id]
        eligible: list[str] = []
        for package in self.packages:
            if package.id not in chosen:
                continue
            for spell_id in package.spell_ids:
                if spell_id not in eligible:
                    eligible.append(spell_id)
        return tuple(eligible)


def validate_catalog(catalog: PackageCatalog, *, expected: int) -> None:
    """Raises unless the menu is one a plan could legally be built from.

    Checked once, when a match is set up, so that every later rejection is
    about the *plan* rather than about the menu it was chosen from.
    """
    if len(catalog.packages) != expected:
        raise ValueError(f"the opening menu offers {expected} packages, got {len(catalog.packages)}")

    seen: set[str] = set()
    for package in catalog.packages:
        if package.id in seen:
            raise ValueError(f"package {package.id} is offered twice")
        seen.add(package.id)

    types = catalog.types
    spell_ids = {spell.id for spell in catalog.spells}

    for package in catalog.packages:
        mage = types.get(package.mage_type_id)
        if mage is None:
            raise ValueError(f"package {package.id} fields {package.mage_type_id}, which is not a card")
        if mage.kind != "mage":
            raise ValueError(f"package {package.id} fields {package.mage_type_id}, which is not a mage")
        for entry in package.entourage:
            summon = types.get(entry.type_id)
            if summon is None:
                raise ValueError(f"package {package.id} fields {entry.type_id}, which is not a card")
            if summon.kind != "summon":
                raise ValueError(f"package {package.id} lists {entry.type_id} as a summon, but it is not")
        for spell_id in package.spell_ids:
            if spell_id not in spell_ids:
                raise ValueError(f"package {package.id} offers spell {spell_id}, which is not in the catalog")


#: The opening-round menu, ready to hand to a controller.
OPENING_CATALOG = PackageCatalog(
    packages=FIVE_FIRE_PACKAGES,
    unit_types=tuple(PLACEHOLDER_UNIT_TYPES),
    spells=tuple(PROVISIONAL_SPELLS),
)
