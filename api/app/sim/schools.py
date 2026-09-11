"""Schools, and the one record slices C and D trade through.

Resonance (design doc §4.11) scales a school's energy gain, resummon pace, and
its own stat axis. Energy is slice C's territory and resonance is slice D's,
which would put both slices in the same energy-gain code. The multiplier table is
the seam that avoids it: resolved once here at battle start, read by every
system, written by nobody.

**Slice C reads it. Slice D populates it** — by computing the resonance curve
inside `resolve_school_multipliers` from the mages deployed at battle start.
Slice A ships identity values, so the hook is live but changes nothing yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Literal

School = Literal["fire", "stone", "artifice", "time", "necromancy", "neutral"]

SCHOOLS: tuple[School, ...] = (
    "fire",
    "stone",
    "artifice",
    "time",
    "necromancy",
    "neutral",
)


@dataclass(frozen=True)
class SchoolMultipliers:
    #: Scales how fast a unit's energy gauge fills (§4.4). Slice C's lever.
    energy_gain_multiplier: float = 1.0
    #: Scales seconds-per-resummon for this school's mages (§4.5). Slice D's lever.
    resummon_pace_multiplier: float = 1.0
    #: Scales this school's own stat axis — Fire speed and damage, Stone HP (§4.11).
    stat_axis_multiplier: float = 1.0


@dataclass
class SchoolConfig:
    id: School
    #: Slice D fills these from the resonance curve; until then all identity.
    multipliers: Mapping[str, float] | None = field(default=None)


IDENTITY_MULTIPLIERS = SchoolMultipliers()

#: A multiplier per school. Read-only: resolved once at battle start, never after.
SchoolMultiplierTable = Mapping[School, SchoolMultipliers]

_LEVERS = tuple(f.name for f in fields(SchoolMultipliers))


def _merge(school: School, overrides: Mapping[str, float]) -> SchoolMultipliers:
    resolved: dict[str, float] = {lever: 1.0 for lever in _LEVERS}

    for lever, value in overrides.items():
        if lever not in resolved:
            raise ValueError(
                f"{lever!r} is not a multiplier; expected one of {_LEVERS}"
            )
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(
                f"{school} {lever} must be a positive number, got {value!r}"
            )
        resolved[lever] = float(value)

    return SchoolMultipliers(**resolved)


def resolve_school_multipliers(
    school_configs: list[SchoolConfig] | tuple[SchoolConfig, ...],
) -> SchoolMultiplierTable:
    """Builds the battle's multiplier table. Call once, at battle start."""
    overrides: dict[School, Mapping[str, float]] = {}

    for config in school_configs:
        if config.id in overrides:
            raise ValueError(f"school {config.id} is configured twice")
        overrides[config.id] = config.multipliers or {}

    # Built by walking SCHOOLS, never by iterating the dict above: insertion
    # order would be fine, but "never iterate an unordered collection" is the
    # rule that keeps this sim deterministic across processes.
    return MappingProxyType(
        {school: _merge(school, overrides.get(school, {})) for school in SCHOOLS}
    )
