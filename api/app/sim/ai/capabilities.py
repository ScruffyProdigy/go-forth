"""What a unit can actually do right now, read off its live stats.

This is the part that keeps fighting style out of the creature type. A card is
not "a skirmisher" because someone wrote skirmisher on it; it skirmishes because
it has reach and speed, and if a debuff takes its speed away it stops
skirmishing without anyone editing its profile. So every capability here is
derived from the unit **as it stands this tick** — its current HP, its current
range and speed — never from `UnitType`.

Capabilities answer "is this option legal or useful at all". Traits and
personalities answer "which of the legal options do I like". Keeping those two
apart is what stops a bold trait from making a legless summon charge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, see module docstring
    from app.sim.world import Unit

#: Reach bands, in map units. The three-zone map is 375 wide and sprites are
#: 18-28 px (JQ-243), so "melee" is roughly contact and "ranged" is roughly a
#: third of a zone. Provisional tuning data, like everything numeric here.
MELEE_REACH = 32.0
RANGED_REACH = 64.0

EngagementBand = Literal["melee", "skirmish", "ranged"]

CapabilityName = Literal["move", "attack", "melee_attack", "ranged_attack"]

CAPABILITIES: tuple[CapabilityName, ...] = get_args(CapabilityName)


@dataclass(frozen=True)
class Capabilities:
    """A snapshot of what one unit can do, this tick."""

    can_move: bool
    can_attack: bool
    #: Weapon reach in map units, as it stands now.
    reach: float
    #: Map units per second, as it stands now.
    speed: float
    #: Damage per swing, as it stands now.
    damage: float
    #: Remaining HP over max, in `[0, 1]`. The durability term everything reads.
    health_fraction: float
    #: Which band `reach` falls in. Derived, never declared.
    engagement: EngagementBand


def _band(reach: float) -> EngagementBand:
    if reach < MELEE_REACH:
        return "melee"
    if reach < RANGED_REACH:
        return "skirmish"
    return "ranged"


def capabilities_of(unit: Unit) -> Capabilities:
    """Reads a unit's live capabilities. Pure: no state, no caching."""
    max_hp = unit.max_hp if unit.max_hp > 0 else 1.0
    return Capabilities(
        can_move=unit.speed > 0,
        can_attack=unit.damage > 0,
        reach=unit.range,
        speed=unit.speed,
        damage=unit.damage,
        health_fraction=min(1.0, max(0.0, unit.hp / max_hp)),
        engagement=_band(unit.range),
    )


def supports(capabilities: Capabilities, capability: CapabilityName) -> bool:
    """Whether a unit meets a named capability requirement."""
    if capability == "move":
        return capabilities.can_move
    if capability == "attack":
        return capabilities.can_attack
    if capability == "melee_attack":
        return capabilities.can_attack
    if capability == "ranged_attack":
        return capabilities.can_attack and capabilities.engagement != "melee"
    raise ValueError(f"{capability!r} is not a capability; expected one of {CAPABILITIES}")


def missing_capabilities(
    capabilities: Capabilities, required: tuple[CapabilityName, ...]
) -> tuple[CapabilityName, ...]:
    """Which of `required` this unit does not meet, in the order given."""
    return tuple(capability for capability in required if not supports(capabilities, capability))


def validate_capability_names(required: tuple[str, ...], what: str) -> None:
    for capability in required:
        if capability not in CAPABILITIES:
            raise ValueError(
                f"{what} requires {capability!r}, which is not a capability; expected one of {CAPABILITIES}"
            )
