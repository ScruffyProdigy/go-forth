"""Resonance: how many of a school you brought, and what that is worth.

Design doc §4.11. A school's resonance is the number of its mages **deployed at
the start of the round** — a dual-school mage counting for both of its schools —
and that one number scales the school's energy gain, its resummon pace, and its
own stat axis.

Three properties this module exists to hold onto.

**Once per battle.** The count is taken from the opening world and never again.
Nothing here runs per tick, there are no passives, and a mage dying at tick 40
does not weaken its school — resonance is what you *deployed*, which is what
makes it a planning decision rather than a battle one. `run_battle` calls
`count_resonance` exactly once; `tests/sim/test_resonance.py` asserts it.

**Per side.** See the note in `schools.py`: resonance belongs to a player's
roster, not to the field.

**The axis is the school's, not the unit's.** A mono card scales on its one
school's axis; a dual card has both, each fed by its own school — a Fire/Artifice
golem gets Fire's multiplier on speed and damage and Artifice's on range, and its
Artifice half is inactive when no Artifice mage is fielded, because a school
nobody brought sits at the curve's identity step.

Only Fire and Artifice have an axis the sim can act on today, which is what the
opening demo needs (JQ-307 is Fire, §7.3's dual is Fire/Artifice). Stone's HP and
armor, Time's carried energy, and Necromancy's lifesteal are all declared in
§4.11 but have nothing to scale until the stats they name exist — `STAT_AXES`
below is where each lands when it does.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from app.sim.schools import SCHOOLS, School, SchoolMultiplierTable
from app.sim.types import SIDES, Side
from app.sim.world import Unit, World

#: Which of a unit's stats each school's resonance scales (§4.11's table).
#: A school absent from here has an axis the sim cannot express yet.
STAT_AXES: Mapping[School, tuple[str, ...]] = MappingProxyType(
    {
        "fire": ("speed", "damage"),
        "artifice": ("range",),
    }
)

ResonanceCounts = Mapping[School, int]
SideResonanceCounts = Mapping[Side, ResonanceCounts]


def count_resonance(world: World) -> SideResonanceCounts:
    """Each side's resonance, per school, from the mages it has on the field.

    Call this on the opening world. Summons do not count — a school's strength
    is the mages backing it — and a dual-school mage counts once for each of its
    schools, which is exactly what makes duals the scarce fixing (§4.1).
    """
    # Built by walking SIDES and SCHOOLS so the mappings have a declared order
    # rather than whatever a fresh interpreter's hashing produces. See `rng.py`.
    counts: dict[Side, dict[School, int]] = {side: dict.fromkeys(SCHOOLS, 0) for side in SIDES}

    for unit in world.units:
        if unit.kind != "mage":
            continue
        for school in unit.schools:
            counts[unit.side][school] += 1

    return MappingProxyType({side: MappingProxyType(counts[side]) for side in SIDES})


def apply_stat_axis(unit: Unit, multipliers: SchoolMultiplierTable) -> None:
    """Scales a unit's stats by its own schools' axes, in place.

    Applied when a unit reaches the field — at battle start, and again to
    anything resummoned onto it — rather than read at every use, so a stat block
    on the field is the stat block that fights. A dual card takes both axes, so
    the two multiply where the axes overlap; they do not today, and if a future
    pair ever shares one, multiplying is the reading §4.11 describes ("a dual at
    3/3 is strong because both halves are").
    """
    for school in unit.schools:
        multiplier = multipliers[school].stat_axis_multiplier
        if multiplier == 1.0:
            continue
        for stat in STAT_AXES.get(school, ()):
            setattr(unit, stat, getattr(unit, stat) * multiplier)


def apply_resonance(world: World, multipliers: Mapping[Side, SchoolMultiplierTable]) -> None:
    """Scales every deployed unit by its side's resonance. Call once, at start."""
    for unit in world.units:
        apply_stat_axis(unit, multipliers[unit.side])
