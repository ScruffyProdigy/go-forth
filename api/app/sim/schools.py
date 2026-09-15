"""Schools, and the one record slices C and D trade through.

Resonance (design doc §4.11) scales a school's energy gain, resummon pace, and
its own stat axis. Energy is slice C's territory and resonance is slice D's,
which would put both slices in the same energy-gain code. The multiplier table is
the seam that avoids it: resolved once here at battle start, read by every
system, written by nobody.

**Slice C reads it. Slice D populates it** — by running each school's resonance
curve over the mages deployed at battle start.

The table is **per side** (JQ-289). Resonance is a property of a player's own
roster, not of the field: §4.11 shows it as one number per school in *your* plan
phase ("Fire 4"), so two players with different rosters have different
multipliers, and counting every mage on the map would read a three-a-side Fire
mirror as "Fire 6". Slice C reads `multipliers[unit.side][school]`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Literal

from app.sim.types import SIDES, Side

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


#: What each resonance step is worth, indexed by how many mages of the school
#: were deployed. The last entry covers every higher count, so a curve is read
#: as "1, 2, 3, 4-or-more" without anyone writing a bound.
ResonanceCurve = tuple[SchoolMultipliers, ...]

#: Provisional, per the 2026-09-12 scheduling note: tuning inputs, not a
#: prerequisite. §4.11 gives the shape rather than the numbers — "1 → weak,
#: 2 → below par, 3 → par, 4+ → strong", with the curve steepening at 3 — and
#: these are the smallest numbers that have it. Two of them are load-bearing
#: rather than arbitrary:
#:
#: * **0 is identity.** A school nobody fielded has no resonance to apply, and
#:   its axis is inactive rather than penalised (§7.3's Furnace Golem).
#: * **3 is identity.** "Par" is the definition of unscaled, which is also what
#:   keeps `test_golden_parity` meaningful: the captured battles field three
#:   Fire mages a side.
#:
#: Pace runs the other way from the other two — it is *seconds* per resummon, so
#: a strong school wants a number below 1.
DEFAULT_RESONANCE_CURVE: ResonanceCurve = (
    SchoolMultipliers(),
    SchoolMultipliers(energy_gain_multiplier=0.75, resummon_pace_multiplier=1.35, stat_axis_multiplier=0.88),
    SchoolMultipliers(energy_gain_multiplier=0.85, resummon_pace_multiplier=1.20, stat_axis_multiplier=0.94),
    SchoolMultipliers(energy_gain_multiplier=1.00, resummon_pace_multiplier=1.00, stat_axis_multiplier=1.00),
    SchoolMultipliers(energy_gain_multiplier=1.15, resummon_pace_multiplier=0.90, stat_axis_multiplier=1.08),
)


@dataclass
class SchoolConfig:
    id: School
    #: Pinned values, applied *after* the curve and overriding it. What a test
    #: or a fixture uses to hold a school still while something else is measured.
    multipliers: Mapping[str, float] | None = field(default=None)
    #: This school's resonance curve. None means the provisional default.
    resonance: ResonanceCurve | None = field(default=None)
    #: How this school charges an energy gauge, as meters and their rates.
    #: None takes the school's default. Slice C's `energy.py` resolves it —
    #: the rule is data so a new school is a row rather than a new branch.
    energy_rule: Mapping[str, float] | None = field(default=None)


IDENTITY_MULTIPLIERS = SchoolMultipliers()

#: A multiplier per school. Read-only: resolved once at battle start, never after.
SchoolMultiplierTable = Mapping[School, SchoolMultipliers]

#: The same, per side — what a battle actually resolves. See the module docstring.
SideMultiplierTable = Mapping[Side, SchoolMultiplierTable]

_LEVERS = tuple(f.name for f in fields(SchoolMultipliers))


def resonance_step(curve: ResonanceCurve, count: int) -> SchoolMultipliers:
    """What a school with `count` mages deployed is worth on this curve.

    Counts past the end of the curve read its last step: "4+" is one entry, not
    an unbounded ramp, and nothing has to know where the curve stops.
    """
    if not curve:
        raise ValueError("a resonance curve needs at least one step")
    if count < 0:
        raise ValueError(f"resonance count must not be negative, got {count}")
    return curve[min(count, len(curve) - 1)]


def _merge(school: School, base: SchoolMultipliers, overrides: Mapping[str, float]) -> SchoolMultipliers:
    resolved: dict[str, float] = {lever: getattr(base, lever) for lever in _LEVERS}

    for lever, value in overrides.items():
        if lever not in resolved:
            raise ValueError(f"{lever!r} is not a multiplier; expected one of {_LEVERS}")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{school} {lever} must be a positive number, got {value!r}")
        resolved[lever] = float(value)

    return SchoolMultipliers(**resolved)


def _by_school(school_configs: Sequence[SchoolConfig]) -> dict[School, SchoolConfig]:
    indexed: dict[School, SchoolConfig] = {}

    for config in school_configs:
        if config.id in indexed:
            raise ValueError(f"school {config.id} is configured twice")
        indexed[config.id] = config

    return indexed


def resolve_school_multipliers(
    school_configs: Sequence[SchoolConfig],
    resonance: Mapping[School, int] | None = None,
) -> SchoolMultiplierTable:
    """One side's multiplier table: its resonance run through each school's curve.

    Pinned `multipliers` are applied on top of the curve's step and win, so a
    caller can hold one lever still without having to restate a whole curve.
    """
    configs = _by_school(school_configs)
    counts = resonance or {}

    # Built by walking SCHOOLS, never by iterating the dict above: insertion
    # order would be fine, but "never iterate an unordered collection" is the
    # rule that keeps this sim deterministic across processes.
    resolved: dict[School, SchoolMultipliers] = {}
    for school in SCHOOLS:
        config = configs.get(school)
        curve = (config.resonance if config else None) or DEFAULT_RESONANCE_CURVE
        step = resonance_step(curve, counts.get(school, 0))
        resolved[school] = _merge(school, step, (config.multipliers if config else None) or {})

    return MappingProxyType(resolved)


def resolve_side_multipliers(
    school_configs: Sequence[SchoolConfig],
    resonance: Mapping[Side, Mapping[School, int]] | None = None,
) -> SideMultiplierTable:
    """The battle's multiplier table: one resolved record per side.

    Call once, at battle start, from the mages each side actually deployed.
    """
    counts = resonance or {}

    # Walking SIDES rather than the mapping, for the reason above.
    return MappingProxyType(
        {side: resolve_school_multipliers(school_configs, counts.get(side, {})) for side in SIDES}
    )
