"""The energy gauge, and the rules that fill it.

Design doc §4.4: a unit charges a gauge, and at full its ability becomes
available. *How* it charges differs by school — Fire off damage dealt, Artifice
off a clock — and JQ-288 is explicit that this must be school **data, not
code**. A third school must be a row in a table, not a third branch in a phase.

The vocabulary that makes that possible is the **energy source**: one way of
charging, written as a meter the sim already measures and what one unit of it
is worth. A school's rule is a *tuple* of sources, because charging is not one
thing — every school trickles on a clock, and most have a second way on top
that is the school's character:

    fire        = (per_second(4), per_damage_dealt(1))
    stone       = (per_second(4), per_damage_taken(1))
    artifice    = (per_second(10),)
    necromancy  = (per_second(4), per_ally_defeated(25))

Read that as: a Fire unit gains 4 energy a second just for being on the field,
and another 1 for every point of damage it deals. So a cinder-hound swinging
for 11 gains 11 from the blow — about four swings to a 35-cost ability, a
little sooner with the trickle. Artifice has no second source; a faster clock
*is* its character, and it is what lets an emplacement that never swings still
come online.

Two properties fall out of the tuple that the earlier mapping form did not
have. Sources are ordered, so the sum is deterministic without leaning on a
separate list of meter names. And a school can hold two sources on the same
meter if a design ever wants that, which a mapping keyed by meter cannot say.

A dual-school card takes the **best rate per meter** across its schools, and
the best energy multiplier. Merging any other way either double-charges it or
punishes it for being dual, and dual cards are the design's scarce fixing
(§4.1). Provisional, of the kind JQ-288 authorises the implementer to pick.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from app.sim.schools import SCHOOLS, School, SchoolConfig, SchoolMultiplierTable

#: What the sim measures about a unit over one tick. A source is written in these.
EnergyMeter = str

DAMAGE_DEALT: EnergyMeter = "damageDealt"
DAMAGE_TAKEN: EnergyMeter = "damageTaken"
ELAPSED_SECONDS: EnergyMeter = "elapsedSeconds"
ALLY_DEFEATED: EnergyMeter = "allyDefeated"

#: Declared as an ordered tuple, not just a type: a unit's meters are always
#: walked through this, never by iterating the dict that holds them, because
#: `PYTHONHASHSEED` would order the additions differently in each process.
ENERGY_METERS: tuple[EnergyMeter, ...] = (
    DAMAGE_DEALT,
    DAMAGE_TAKEN,
    ELAPSED_SECONDS,
    ALLY_DEFEATED,
)


@dataclass(frozen=True)
class EnergySource:
    """One way of charging: a meter, and what one unit of it is worth."""

    meter: EnergyMeter
    energy_per_unit: float

    def __post_init__(self) -> None:
        if self.meter not in ENERGY_METERS:
            raise ValueError(f"{self.meter!r} is not a meter; expected one of {ENERGY_METERS}")
        if not isinstance(self.energy_per_unit, (int, float)) or isinstance(self.energy_per_unit, bool):
            raise ValueError(f"{self.meter} rate must be a number, got {self.energy_per_unit!r}")
        if self.energy_per_unit < 0:
            raise ValueError(f"{self.meter} rate must not be negative, got {self.energy_per_unit}")


#: How a school charges: every way it does, in order.
EnergyRule = tuple[EnergySource, ...]


def per_second(energy: float) -> EnergySource:
    """Charges on a clock, whatever the unit is doing."""
    return EnergySource(ELAPSED_SECONDS, energy)


def per_damage_dealt(energy: float) -> EnergySource:
    """Charges from aggression — Fire's rule (§4.4)."""
    return EnergySource(DAMAGE_DEALT, energy)


def per_damage_taken(energy: float) -> EnergySource:
    """Charges from being hit — Stone's rule (§4.4)."""
    return EnergySource(DAMAGE_TAKEN, energy)


def per_ally_defeated(energy: float) -> EnergySource:
    """Charges when a troop-mate falls — Necromancy's rule (§4.4)."""
    return EnergySource(ALLY_DEFEATED, energy)


#: Every school charges on a clock, so no unit is ever wholly inert — a card
#: whose school's other source never fires still comes online eventually.
#: Provisional rate.
BASELINE_TRICKLE = per_second(4)

#: Artifice's clock is faster, because the clock *is* its character (§4.4)
#: rather than a floor under something else. Provisional rate.
ARTIFICE_CLOCK = per_second(10)

#: Every school's rule, as the design doc states them (§4.4): "Fire: from
#: dealing damage; Stone: from taking it; Artifice: on a timer; Time:
#: generation TBD; Necromancy: from ally deaths" — each over the common clock.
#:
#: Four of the five are written here with no code behind any of them, which is
#: the claim JQ-288 is really making: the vocabulary was built from Fire and
#: Artifice, and the other schools turned out to be rows rather than branches.
#: Time is the one the doc leaves open, so it carries the trickle alone until
#: §7.2 settles carryover.
DEFAULT_ENERGY_RULES: Mapping[School, EnergyRule] = MappingProxyType(
    {
        "fire": (BASELINE_TRICKLE, per_damage_dealt(1)),
        "stone": (BASELINE_TRICKLE, per_damage_taken(1)),
        "artifice": (ARTIFICE_CLOCK,),
        "necromancy": (BASELINE_TRICKLE, per_ally_defeated(25)),
        "time": (BASELINE_TRICKLE,),
        "neutral": (BASELINE_TRICKLE,),
    }
)

#: One rule per school, resolved once at battle start alongside the multipliers.
SchoolEnergyRuleTable = Mapping[School, EnergyRule]


def new_energy_meters() -> dict[EnergyMeter, float]:
    """A unit's meters, all at zero. Built in `ENERGY_METERS` order."""
    return {meter: 0.0 for meter in ENERGY_METERS}


def rule_from_rates(rates: Mapping[str, float]) -> EnergyRule:
    """Builds a rule from `{meter: rate}`, the shape a config file writes.

    Config arrives as data and a mapping is the natural way to write it down;
    the tuple is the shape the sim reasons in. Ordered by `ENERGY_METERS` so
    two configs that say the same thing produce the same rule.
    """
    unknown = [meter for meter in sorted(rates) if meter not in ENERGY_METERS]
    if unknown:
        raise ValueError(f"energy rule names {unknown}, which are not meters; expected {ENERGY_METERS}")

    return tuple(EnergySource(meter, rates[meter]) for meter in ENERGY_METERS if meter in rates)


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
                rule_from_rates(overrides[school]) if school in overrides else DEFAULT_ENERGY_RULES[school]
            )
            for school in SCHOOLS
        }
    )


def energy_rule_for(schools: Sequence[School], table: SchoolEnergyRuleTable) -> EnergyRule:
    """The rule a unit charges by: the best rate per meter across its schools."""
    best: dict[EnergyMeter, float] = {}

    for school in schools:
        for source in table[school]:
            current = best.get(source.meter)
            if current is None or source.energy_per_unit > current:
                best[source.meter] = source.energy_per_unit

    return tuple(EnergySource(meter, best[meter]) for meter in ENERGY_METERS if meter in best)


def energy_multiplier_for(schools: Sequence[School], multipliers: SchoolMultiplierTable) -> float:
    """The resonance multiplier a unit charges under (§4.11).

    Read from the core's multiplier record and never computed here: JQ-289
    populates it from the resonance curve, and this slice only consumes it.
    """
    return max((multipliers[school].energy_gain_multiplier for school in schools), default=1.0)


def energy_gain(meters: Mapping[EnergyMeter, float], rule: EnergyRule, multiplier: float) -> float:
    """What a tick's meters are worth under `rule`, scaled by resonance.

    Walks the rule's own sources, in their declared order — so the sum is
    reproducible without depending on how any dict happens to be ordered.
    """
    total = 0.0

    for source in rule:
        total += meters.get(source.meter, 0.0) * source.energy_per_unit

    return total * multiplier
