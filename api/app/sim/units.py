"""Unit types — the card, not the instance on the field.

The stat block is design doc §4.4. The energy gauge and the ability arrived
with slice C (JQ-288); resummon pace is still read by slice D. They are
declared here because the *type* carries them.

A card's `schools` is a tuple because dual-school cards are the design's scarce
fixing (§4.1) — a Furnace Golem is Fire/Artifice and counts for both.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from app.sim.schools import SCHOOLS, School

UnitKind = Literal["mage", "summon"]


@dataclass(frozen=True)
class UnitType:
    id: str
    kind: UnitKind
    #: One school for a mono card, two for a dual. Never empty.
    schools: tuple[School, ...]
    max_hp: float
    damage: float
    #: Attack reach in map units. Melee is a short range, not a special case.
    range: float
    #: Map units per second. The loop converts to per-tick.
    speed: float
    attack_cooldown_seconds: float
    #: Mages only: how many summons this mage sustains (§4.2).
    support_capacity: int | None = None
    #: Mages only: seconds per resummon (§4.5). Slice D reads it.
    resummon_pace_seconds: float | None = None
    #: The ability a full energy gauge fires, by id. None never charges.
    #: A reference rather than the ability itself: a card that held its own
    #: effects would pull the whole effect vocabulary into this module.
    ability_id: str | None = None
    #: An emplacement holds its ground: speed 0, never knocked back, never
    #: resummoned, and it survives round end while its mage lives (JQ-288).
    emplacement: bool = False
    #: A barricade. Enemies cannot walk through the disc it stands in, which is
    #: the whole of the blocking primitive — an Artifice wall is this flag on a
    #: card, not new code in the sim.
    blocks_movement: bool = False
    #: The radius of that disc. Only read when `blocks_movement`.
    block_radius: float = 0.0


UnitTypeCatalog = Mapping[str, UnitType]


def _validate(unit_type: UnitType) -> None:
    if not unit_type.schools:
        raise ValueError(f"unit type {unit_type.id} belongs to no school")
    for school in unit_type.schools:
        if school not in SCHOOLS:
            raise ValueError(f"{school!r} is not a school; unit type {unit_type.id}")
    if not unit_type.max_hp > 0:
        raise ValueError(f"unit type {unit_type.id} has max_hp {unit_type.max_hp}; must be positive")
    if unit_type.damage < 0:
        raise ValueError(f"unit type {unit_type.id} has negative damage")
    if unit_type.range < 0:
        raise ValueError(f"unit type {unit_type.id} has a negative range")
    if unit_type.speed < 0:
        raise ValueError(f"unit type {unit_type.id} has a negative speed")
    if not unit_type.attack_cooldown_seconds > 0:
        raise ValueError(
            f"unit type {unit_type.id} has an attack cooldown of "
            f"{unit_type.attack_cooldown_seconds}; a cooldown of zero would fire every tick"
        )
    if unit_type.kind == "mage" and not (unit_type.support_capacity or 0) > 0:
        raise ValueError(f"mage type {unit_type.id} has no support capacity, so it could hold no summons")
    if unit_type.emplacement and unit_type.kind != "summon":
        raise ValueError(
            f"unit type {unit_type.id} is an emplacement but is a {unit_type.kind}, not a summon"
        )
    if unit_type.emplacement and unit_type.speed != 0:
        raise ValueError(
            f"emplacement {unit_type.id} has speed {unit_type.speed}; an emplacement holds position"
        )
    if unit_type.blocks_movement and not unit_type.block_radius > 0:
        raise ValueError(f"unit type {unit_type.id} blocks movement but has no block radius")


def build_unit_type_catalog(unit_types: Sequence[UnitType]) -> UnitTypeCatalog:
    """Indexes the battle's cards by id, rejecting incoherent ones up front."""
    catalog: dict[str, UnitType] = {}

    for unit_type in unit_types:
        if unit_type.id in catalog:
            raise ValueError(f"unit type {unit_type.id} is defined twice")
        _validate(unit_type)
        catalog[unit_type.id] = unit_type

    return MappingProxyType(catalog)
