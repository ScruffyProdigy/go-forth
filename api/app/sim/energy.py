"""The energy gauge, and the rule that fills it.

Design doc §4.4: a unit charges a gauge, and at full it casts its ability and
the gauge resets. *How* it charges differs by school — Fire charges off damage
dealt, Artifice off a timer — and JQ-288 is explicit that this must be school
**data, not code**. A third school must be a row in a table, not a third branch
in the phase.

The vocabulary that makes that possible is the meter. A meter is something the
sim already measures about a unit over one tick; a rule is how much energy each
point of each meter is worth. Fire's rule is `{damageDealt: 1}` and Artifice's
is `{elapsedSeconds: 10}`.

The design doc names five (§4.4): "Fire: from dealing damage; Stone: from
taking it; Artifice: on a timer; Time: generation TBD; Necromancy: from ally
deaths". Four of them are written in `DEFAULT_ENERGY_RULES` below and none has
a line of code behind it — which is the claim this module exists to make, on
schools it was not designed against rather than on the two it was.

A dual-school card takes the **best** rate per meter across its schools, and
the best energy multiplier. Merging any other way either double-charges it or
punishes it for being dual, and dual cards are the design's scarce fixing
(§4.1). This is a provisional rule of the kind JQ-288 authorises the
implementer to pick; the numbers on either side of it are tuning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from app.sim.schools import SCHOOLS, School, SchoolConfig, SchoolMultiplierTable

#: What the sim measures about a unit over one tick. A rule is written in these.
#:
#: Declared as an ordered tuple, not just a type: every walk over a unit's
#: meters goes through this, because iterating the dict itself would order the
#: additions by whatever `PYTHONHASHSEED` picked that process.
EnergyMeter = str

DAMAGE_DEALT: EnergyMeter = "damageDealt"
DAMAGE_TAKEN: EnergyMeter = "damageTaken"
ELAPSED_SECONDS: EnergyMeter = "elapsedSeconds"
ALLY_DEFEATED: EnergyMeter = "allyDefeated"

ENERGY_METERS: tuple[EnergyMeter, ...] = (
    DAMAGE_DEALT,
    DAMAGE_TAKEN,
    ELAPSED_SECONDS,
    ALLY_DEFEATED,
)

#: Energy per point of each meter. Absent meter means that meter is worth nothing.
EnergyRule = Mapping[EnergyMeter, float]

#: Fire (§4.4): aggression charges the gauge. One energy per point of damage dealt.
DAMAGE_DEALT_RULE: EnergyRule = MappingProxyType({DAMAGE_DEALT: 1.0})

#: Stone (§4.4): charges from taking damage rather than dealing it.
DAMAGE_TAKEN_RULE: EnergyRule = MappingProxyType({DAMAGE_TAKEN: 1.0})

#: Artifice (§4.4): the gauge fills on its own clock, so an emplacement that
#: never swings still comes online. Provisional rate — ten energy a second.
TIMER_RULE: EnergyRule = MappingProxyType({ELAPSED_SECONDS: 10.0})

#: Necromancy (§4.4): charges from ally deaths. Provisional rate — a troop-mate
#: falling is worth two and a half seconds of an Artifice timer.
ALLY_DEFEATED_RULE: EnergyRule = MappingProxyType({ALLY_DEFEATED: 25.0})

#: Every school's rule, as the design doc states them (§4.4): "Fire: from
#: dealing damage; Stone: from taking it; Artifice: on a timer; Time:
#: generation TBD; Necromancy: from ally deaths".
#:
#: Four of the five are written above with no code behind any of them, which is
#: the claim JQ-288 is really making — the vocabulary was built from Fire and
#: Artifice, and the other two schools turned out to be rows rather than
#: branches. Time is the one the doc leaves open; it takes the timer until §7.2
#: settles carryover, so a card with an ability is never inert.
DEFAULT_ENERGY_RULES: Mapping[School, EnergyRule] = MappingProxyType(
    {
        "fire": DAMAGE_DEALT_RULE,
        "stone": DAMAGE_TAKEN_RULE,
        "artifice": TIMER_RULE,
        "necromancy": ALLY_DEFEATED_RULE,
        "time": TIMER_RULE,
        "neutral": TIMER_RULE,
    }
)

#: One rule per school, resolved once at battle start alongside the multipliers.
SchoolEnergyRuleTable = Mapping[School, EnergyRule]


def new_energy_meters() -> dict[EnergyMeter, float]:
    """A unit's meters, all at zero. Built in `ENERGY_METERS` order."""
    return {meter: 0.0 for meter in ENERGY_METERS}


def _validate_rule(school: School, rule: Mapping[str, float]) -> EnergyRule:
    resolved: dict[EnergyMeter, float] = {}

    for meter in ENERGY_METERS:
        if meter not in rule:
            continue
        rate = rule[meter]
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate < 0:
            raise ValueError(f"{school} energy rate for {meter} must be a non-negative number, got {rate!r}")
        resolved[meter] = float(rate)

    unknown = [meter for meter in sorted(rule) if meter not in ENERGY_METERS]
    if unknown:
        raise ValueError(
            f"{school} energy rule names {unknown}, which are not meters; expected {ENERGY_METERS}"
        )

    return MappingProxyType(resolved)


def resolve_school_energy_rules(school_configs: Sequence[SchoolConfig]) -> SchoolEnergyRuleTable:
    """Builds the battle's energy-rule table. Call once, at battle start.

    Mirrors `resolve_school_multipliers` deliberately — same lifecycle, same
    "resolved once, read by everyone, written by nobody" contract, and built by
    walking `SCHOOLS` rather than the configs so the order cannot vary.
    """
    overrides: dict[School, Mapping[str, float]] = {}
    # Tracked apart from the overrides: a school configured twice is an error
    # whether or not either config happened to carry an energy rule.
    seen: set[School] = set()

    for config in school_configs:
        if config.id in seen:
            raise ValueError(f"school {config.id} is configured twice")
        seen.add(config.id)
        if config.energy_rule is not None:
            overrides[config.id] = config.energy_rule

    return MappingProxyType(
        {
            school: (
                _validate_rule(school, overrides[school])
                if school in overrides
                else DEFAULT_ENERGY_RULES[school]
            )
            for school in SCHOOLS
        }
    )


def energy_rule_for(schools: Sequence[School], table: SchoolEnergyRuleTable) -> EnergyRule:
    """The rule a unit charges by: the best rate per meter across its schools."""
    merged: dict[EnergyMeter, float] = {}

    for meter in ENERGY_METERS:
        rates = [table[school][meter] for school in schools if meter in table[school]]
        if rates:
            merged[meter] = max(rates)

    return MappingProxyType(merged)


def energy_multiplier_for(schools: Sequence[School], multipliers: SchoolMultiplierTable) -> float:
    """The resonance multiplier a unit charges under (§4.11).

    Read from the core's multiplier record and never computed here: JQ-289
    populates it from the resonance curve, and this slice only consumes it.
    """
    return max((multipliers[school].energy_gain_multiplier for school in schools), default=1.0)


def energy_gain(meters: Mapping[EnergyMeter, float], rule: EnergyRule, multiplier: float) -> float:
    """What a tick's meters are worth under `rule`, scaled by resonance."""
    total = 0.0

    for meter in ENERGY_METERS:
        rate = rule.get(meter)
        if rate:
            total += meters.get(meter, 0.0) * rate

    return total * multiplier
