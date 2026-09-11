"""The world model, and how a battle's opening state is built from roster data.

The roster is a **multiset** (design doc §4.1): "3x Ember Adept, 4x Cinder Hound"
is the normal shape, and nothing in the sim assumes an army size. Round 1 fields
three mages and round 4 fields most of the roster, so any code here that
hard-coded a count would be wrong by round 2.

A troop is one or more mages plus the summons they support (§4.2). Support is
mandatory and local — a mage in another troop is too far away to help — so a
summon whose school no mage in *its own* troop supports is rejected at build time
rather than quietly standing on the field.

Placement here is the flat "everyone into the strip" version. Formations derived
from orders are slice B (JQ-287); this is what it replaces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.sim.map import MapConfig, validate_map_config
from app.sim.rng import Rng
from app.sim.schools import School
from app.sim.types import SIDES, Side, TroopId, UnitId, UnitRef, Vec2
from app.sim.units import UnitKind, UnitType, UnitTypeCatalog, build_unit_type_catalog


@dataclass
class RosterEntry:
    """One line of a roster: a card and how many copies. Omitting count means one."""

    type_id: str
    count: int = 1


@dataclass
class TroopSetup:
    mages: list[RosterEntry] = field(default_factory=list)
    summons: list[RosterEntry] = field(default_factory=list)
    id: str | None = None


@dataclass
class ArmySetup:
    side: Side
    troops: list[TroopSetup] = field(default_factory=list)


@dataclass
class BattleSetup:
    """Everything a battle needs to exist, as data."""

    unit_types: list[UnitType] = field(default_factory=list)
    armies: list[ArmySetup] = field(default_factory=list)


@dataclass
class Unit:
    id: UnitId
    type_id: str
    kind: UnitKind
    schools: tuple[School, ...]
    side: Side
    troop_id: TroopId
    max_hp: float
    damage: float
    range: float
    #: Map units per second; the loop converts to per-tick.
    speed: float
    attack_cooldown_seconds: float
    hp: float
    position: Vec2
    #: Ticks still to wait before this unit can attack again — ticks, not seconds.
    cooldown_remaining: int = 0


@dataclass
class Troop:
    id: TroopId
    side: Side
    #: Living mages. A troop whose last mage dies dissolves — slice D (§4.6).
    mage_ids: list[UnitId] = field(default_factory=list)
    summon_ids: list[UnitId] = field(default_factory=list)


@dataclass
class BaseState:
    max_hp: float
    position: Vec2
    hp: float


@dataclass
class World:
    tick: int
    #: Serialisable: a snapshot fully determines every draw that follows it.
    rng_state: int
    units: list[Unit]
    troops: list[Troop]
    bases: dict[Side, BaseState]
    zone_score: dict[Side, float]


def unit_ref(unit: Unit) -> UnitRef:
    """How a unit appears in the event stream."""
    return UnitRef(unit.id, unit.troop_id, unit.side, unit.type_id)


#: Spacing between deployed units, in map units. Sprites are 18-28 px (JQ-243).
DEPLOY_SPACING = 24
#: A unit of jitter, so placement reads as an army rather than a spreadsheet.
DEPLOY_JITTER = 1


def _expand(entries: Sequence[RosterEntry], catalog: UnitTypeCatalog, kind: UnitKind) -> list[UnitType]:
    expanded: list[UnitType] = []

    for entry in entries:
        unit_type = catalog.get(entry.type_id)
        if unit_type is None:
            raise ValueError(f"roster names {entry.type_id}, which is not in the unit type catalog")
        if unit_type.kind != kind:
            raise ValueError(f"{entry.type_id} is a {unit_type.kind}, but the roster lists it as a {kind}")
        if not isinstance(entry.count, int) or entry.count < 1:
            raise ValueError(f"roster entry {entry.type_id} has a count of {entry.count!r}")
        expanded.extend([unit_type] * entry.count)

    return expanded


def _assert_one_army_per_side(armies: Sequence[ArmySetup]) -> None:
    seen: set[Side] = set()
    for army in armies:
        if army.side in seen:
            raise ValueError(f"two armies were given for {army.side}")
        seen.add(army.side)
    for side in SIDES:
        if side not in seen:
            raise ValueError(f"no army was given for {side}")


def _assert_supported(mages: Sequence[UnitType], summons: Sequence[UnitType], troop_id: TroopId) -> None:
    if not mages:
        raise ValueError(f"troop {troop_id} has no mage, so it could hold nothing on the field")

    # Membership only — never iterated. See the note in `rng.py`.
    supported: set[School] = {school for mage in mages for school in mage.schools}
    for summon in summons:
        if not any(school in supported for school in summon.schools):
            raise ValueError(
                f"troop {troop_id} has no mage able to support {summon.id} "
                f"({'/'.join(summon.schools)}); support is mandatory and local"
            )


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _deployment_spot(config: MapConfig, side: Side, index: int, rng: Rng) -> Vec2:
    """Lays a side's units out in its strip, filling columns before adding a row.

    A row costs 21 px of the scarce portrait axis, a column 22 px of width the
    map was not using (JQ-243).
    """
    strip = config.deployment[side]
    width = strip.extent.end - strip.extent.start
    columns = max(1, int(width // DEPLOY_SPACING))
    column = index % columns
    row = index // columns

    x = strip.extent.start + DEPLOY_SPACING / 2 + column * DEPLOY_SPACING
    jitter = (rng.next_float() * 2 - 1) * DEPLOY_JITTER

    # Front rank nearest the zones; further ranks fall back toward the base.
    depth = DEPLOY_SPACING / 2 + row * DEPLOY_SPACING
    y = strip.lane.end - depth if side == "north" else strip.lane.start + depth

    return Vec2(
        _clamp(x + jitter, strip.extent.start, strip.extent.end),
        _clamp(y, strip.lane.start, strip.lane.end),
    )


def create_world(config: MapConfig, battle_state: BattleSetup, rng: Rng) -> World:
    """Builds the opening state of a battle. Pure: same inputs, same world."""
    validate_map_config(config)
    _assert_one_army_per_side(battle_state.armies)

    catalog = build_unit_type_catalog(battle_state.unit_types)
    units: list[Unit] = []
    troops: list[Troop] = []
    seen_ids: set[UnitId] = set()

    for army in battle_state.armies:
        placed = 0

        for troop_index, troop_setup in enumerate(army.troops):
            troop_id = troop_setup.id or f"{army.side}-t{troop_index}"
            mage_types = _expand(troop_setup.mages, catalog, "mage")
            summon_types = _expand(troop_setup.summons, catalog, "summon")
            _assert_supported(mage_types, summon_types, troop_id)

            troop = Troop(id=troop_id, side=army.side)

            for member_index, unit_type in enumerate([*mage_types, *summon_types]):
                unit_id = f"{troop_id}-u{member_index}"
                if unit_id in seen_ids:
                    raise ValueError(f"two units share the id {unit_id}; troop ids must be unique")
                seen_ids.add(unit_id)

                units.append(
                    Unit(
                        id=unit_id,
                        type_id=unit_type.id,
                        kind=unit_type.kind,
                        schools=unit_type.schools,
                        side=army.side,
                        troop_id=troop_id,
                        max_hp=unit_type.max_hp,
                        damage=unit_type.damage,
                        range=unit_type.range,
                        speed=unit_type.speed,
                        attack_cooldown_seconds=unit_type.attack_cooldown_seconds,
                        hp=unit_type.max_hp,
                        position=_deployment_spot(config, army.side, placed, rng),
                    )
                )
                placed += 1

                if unit_type.kind == "mage":
                    troop.mage_ids.append(unit_id)
                else:
                    troop.summon_ids.append(unit_id)

            troops.append(troop)

    return World(
        tick=0,
        rng_state=rng.state,
        units=units,
        troops=troops,
        bases={
            side: BaseState(
                max_hp=config.bases[side].max_hp,
                position=config.bases[side].position,
                hp=config.bases[side].max_hp,
            )
            for side in SIDES
        },
        zone_score={"north": 0, "south": 0},
    )
