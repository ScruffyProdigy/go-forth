"""Resonance: how many of a school you brought, and what that is worth.

Design doc §4.11. A school's resonance is the number of its mages **deployed at
the start of the round** — a dual-school mage counting for both of its schools —
and it is what a school's effects gate on and scale by.

Three properties this module exists to hold onto.

**Once per battle.** The count is taken from the opening world and never again.
Nothing here runs per tick, there are no passives, and a mage dying at tick 40
does not weaken its school — resonance is what you *deployed*, which is what
makes it a planning decision rather than a battle one. `run_battle` calls
`count_resonance` exactly once; `tests/sim/test_resonance.py` asserts it.

**Per side.** See the note in `schools.py`: resonance belongs to a player's
roster, not to the field.

**It is an input, not a blanket scaling.** Resonance does *not* walk the field
multiplying everybody's stats. Ryan's call, 2026-09-15: a school's strength
should show up as effects that **require** a resonance level to be selectable at
all, or that **scale their own magnitude** by it — not as a flat multiplier on
everything a school touches. A flat multiplier is both unreadable to a player
(nothing on screen says why this Ember Adept hits for 8.8) and invisible to
design, since every future effect inherits it whether or not that makes sense.

So this module produces two things and applies neither on its own:

* `count_resonance` — the number itself, per side and school, which effects read
  for a requirement ("selectable at Fire 3") or to scale their own magnitude;
* the multiplier record in `schools.py`, which named systems read deliberately.
  `resummon_pace_multiplier` is read by the resummon phase, and that is the one
  scaling slice D applies, because pace is a per-school stat by design (§4.5).

**The axis is the school's, not the unit's.** `STAT_AXES` records §4.11's table —
which stat each school's resonance is *about* — as design data for the effects
that will read it. A mono card has one axis; a dual card has both, each fed by
its own school, which is the shape Ryan described: a red/yellow creature that
gets faster from yellow and hits harder from red. Fire and Artifice are the two
the opening demo needs (JQ-307 is Fire, §7.3's dual is Fire/Artifice); Stone's HP
and armor, Time's carried energy and Necromancy's lifesteal land here when the
stats they name exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from app.sim.schools import SCHOOLS, School
from app.sim.types import SIDES, Side
from app.sim.world import World

#: Which stat each school's resonance is about (§4.11's table). Design data for
#: the effects that scale on it — nothing here applies it to a unit. A school
#: absent from this table has an axis the sim has no stat for yet.
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
