"""The world model, and how a battle's opening state is built from roster data.

The roster is a **multiset** (design doc §4.1): "3x Ember Adept, 4x Cinder Hound"
is the normal shape, and nothing in the sim assumes an army size. Round 1 fields
three mages and round 4 fields most of the roster, so any code here that
hard-coded a count would be wrong by round 2.

A troop is one or more mages plus the summons they support (§4.2). Support is
mandatory and local — a mage in another troop is too far away to help — so a
summon whose school no mage in *its own* troop supports is rejected at build time
rather than quietly standing on the field.

Placement is derived, never supplied. Every troop carries exactly one order, and
`formation.py` turns that order into a shape, a starting spot in the deployment
strip, and the station each unit walks to. Nothing in this module — or anywhere
else in the API — accepts a position, a stance or a facing from a plan.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.sim.formation import (
    Formation,
    deployment_anchor,
    deployment_band,
    deployment_spot,
    derive_formation,
    station,
)
from app.sim.map import MapConfig, validate_map_config
from app.sim.orders import Order, validate_order
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
    """A troop as a plan gives it: a roster and the one order it is under.

    `order` comes first and has no default because it is not optional — a troop
    without an order has nothing to derive a position from, and a default would
    quietly become the placement input this design does not have.
    """

    order: Order
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
    #: Base HP carried in from earlier rounds. A side left out opens at full.
    #: Damage persists across a match: nothing here ever refills a base (JQ-187).
    base_hp: dict[Side, float] = field(default_factory=dict)


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
    #: This unit's slot in its troop's formation, relative to the objective.
    #: Derived from the troop's order at battle start; never supplied.
    formation_offset: Vec2
    #: Where the unit is trying to stand this tick. The orders phase rewrites it
    #: from the troop's order every tick, so a behaviour layer (JQ-296/328) can
    #: overwrite it for a bounded diversion and get the assigned station back by
    #: simply stopping — returning to post needs no bookkeeping of its own.
    destination: Vec2
    #: Ticks still to wait before this unit can attack again — ticks, not seconds.
    cooldown_remaining: int = 0


@dataclass
class Troop:
    id: TroopId
    side: Side
    #: Exactly one, for the whole battle. The plan phase is where it is chosen.
    order: Order
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
    #: Who currently holds each zone, by zone id. None while empty or contested.
    zone_holders: dict[str, Side | None]


def unit_ref(unit: Unit) -> UnitRef:
    """How a unit appears in the event stream."""
    return UnitRef(unit.id, unit.troop_id, unit.side, unit.type_id)


def is_alive(unit: Unit) -> bool:
    """A unit brought to zero stops acting at once, and is swept at end of tick."""
    return unit.hp > 0


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


def _carried_base_hp(config: MapConfig, side: Side, carried: dict[Side, float]) -> float:
    """The HP this side's base opens on: what it has left, or full if unstated.

    A base never recovers between rounds (JQ-187), so a match engine hands last
    round's remaining HP straight back in.
    """
    if side not in carried:
        return config.bases[side].max_hp

    hp = carried[side]
    if not isinstance(hp, (int, float)) or isinstance(hp, bool):
        raise ValueError(f"carried {side} base HP must be a number, got {hp!r}")
    if hp <= 0:
        raise ValueError(f"{side} base is carried in at {hp} HP, so the match is already over")
    if hp > config.bases[side].max_hp:
        raise ValueError(f"{side} base is carried in above its maximum; bases do not recover")
    return float(hp)


def create_world(config: MapConfig, battle_state: BattleSetup, rng: Rng) -> World:
    """Builds the opening state of a battle. Pure: same inputs, same world."""
    validate_map_config(config)
    _assert_one_army_per_side(battle_state.armies)

    catalog = build_unit_type_catalog(battle_state.unit_types)
    units: list[Unit] = []
    troops: list[Troop] = []
    seen_ids: set[UnitId] = set()

    for army in battle_state.armies:
        for troop_index, troop_setup in enumerate(army.troops):
            troop_id = troop_setup.id or f"{army.side}-t{troop_index}"
            order = troop_setup.order
            validate_order(order, config)

            mage_types = _expand(troop_setup.mages, catalog, "mage")
            summon_types = _expand(troop_setup.summons, catalog, "summon")
            _assert_supported(mage_types, summon_types, troop_id)

            band = deployment_band(config, army.side, troop_index, len(army.troops))
            formation: Formation = derive_formation(
                order,
                army.side,
                len(mage_types),
                len(summon_types),
                band.end - band.start,
            )
            anchor = deployment_anchor(config, army.side, order, band, formation)
            troop = Troop(id=troop_id, side=army.side, order=order)

            for member_index, unit_type in enumerate([*mage_types, *summon_types]):
                unit_id = f"{troop_id}-u{member_index}"
                if unit_id in seen_ids:
                    raise ValueError(f"two units share the id {unit_id}; troop ids must be unique")
                seen_ids.add(unit_id)

                offset = formation.offsets[member_index]
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
                        position=deployment_spot(config, army.side, anchor, offset, rng),
                        formation_offset=offset,
                        destination=station(order, army.side, offset, config),
                    )
                )

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
                hp=_carried_base_hp(config, side, battle_state.base_hp),
            )
            for side in SIDES
        },
        zone_score={"north": 0, "south": 0},
        zone_holders={zone.id: None for zone in config.zones},
    )


def troop_of(world: World, unit: Unit) -> Troop:
    """The troop a unit belongs to. Every unit belongs to exactly one."""
    for troop in world.troops:
        if troop.id == unit.troop_id:
            return troop
    raise ValueError(f"unit {unit.id} names troop {unit.troop_id}, which is not in this battle")


def order_of(world: World, unit: Unit) -> Order:
    """The order this unit is acting under — its troop's, always."""
    return troop_of(world, unit).order


def orders_by_troop(world: World) -> dict[TroopId, Order]:
    """Every troop's order, for a phase that needs to look one up per unit.

    A dict keyed by troop id: looked up, never iterated. Iterating it would order
    the sim by Python's per-process string hashing. See `rng.py`.
    """
    return {troop.id: troop.order for troop in world.troops}
