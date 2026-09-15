"""The battle sim.

Everything a caller needs is here; nothing here touches the outside world. The
server hands `run_battle` a map, the school configs, a battle's roster data, and a
seed, and gets back the whole battle — tick by tick, with its event stream.

Slices A (JQ-286) and B (JQ-287) of the sim. Energy and abilities are JQ-288,
resummoning and resonance JQ-289. See `phases/__init__.py` for where each of them
attaches.

Two Python rules hold the determinism guarantee, neither of which had an
equivalent in the TypeScript this was ported from:

* Never iterate an unordered collection. `PYTHONHASHSEED` is randomised per
  interpreter, so `set` order differs between processes — invisible to any test
  that runs in one. Sets are used for membership only.
* Never use module-level `random`; it is process-global. Randomness comes from an
  explicit `Rng` threaded through the tick context.
"""

from app.sim.config import (
    DEFAULT_SIM_CONFIG,
    SimConfig,
    max_ticks,
    seconds_per_tick,
    to_ticks,
    validate_sim_config,
)
from app.sim.context import TickContext, create_tick_context
from app.sim.events import (
    BattleEvent,
    BattleEventType,
    EventActors,
    EventEmitter,
    EventSwing,
    create_event_emitter,
    unit_defeated,
)
from app.sim.fixtures import PLACEHOLDER_UNIT_TYPES, placeholder_battle
from app.sim.formation import (
    FORMATION_RANK_GAP,
    FORMATION_SPACING,
    MAGE_SETBACK_GUARDED,
    MAGE_SETBACK_PUSH,
    Formation,
    deployment_anchor,
    deployment_band,
    derive_formation,
    station,
)
from app.sim.map import (
    THREE_ZONE_MAP,
    BaseConfig,
    ChipReserve,
    DeploymentStrip,
    MapConfig,
    ZoneConfig,
    chip_box,
    clear_of_chip,
    strip_centre,
    validate_map_config,
    zone_by_id,
    zone_centre,
    zone_containing,
)
from app.sim.orders import (
    DEFEND_BASE,
    PUSH_ENEMY_BASE,
    Order,
    OrderKind,
    hold,
    legal_orders,
    may_attack_base,
    objective_position,
    validate_order,
)
from app.sim.phase import TickPhase
from app.sim.phases import TICK_PHASES
from app.sim.rng import Rng, create_rng, rng_from_state
from app.sim.run_battle import (
    BattleOutcome,
    BattleResult,
    BattleTick,
    run_battle,
    step_battle,
)
from app.sim.schools import (
    IDENTITY_MULTIPLIERS,
    SCHOOLS,
    School,
    SchoolConfig,
    SchoolMultipliers,
    SchoolMultiplierTable,
    resolve_school_multipliers,
)
from app.sim.serialize import digest_battle, serialize_battle
from app.sim.types import SIDES, Side, Span, TroopId, UnitId, UnitRef, Vec2, opposing
from app.sim.units import UnitKind, UnitType, UnitTypeCatalog, build_unit_type_catalog
from app.sim.world import (
    ArmySetup,
    BaseState,
    BattleSetup,
    RosterEntry,
    Troop,
    TroopSetup,
    Unit,
    World,
    create_world,
    is_alive,
    order_of,
    orders_by_troop,
    troop_of,
    unit_ref,
)
from app.sim.zones import ZoneOccupancy, zone_occupancy

__all__ = [
    "DEFAULT_SIM_CONFIG",
    "DEFEND_BASE",
    "FORMATION_RANK_GAP",
    "FORMATION_SPACING",
    "IDENTITY_MULTIPLIERS",
    "MAGE_SETBACK_GUARDED",
    "MAGE_SETBACK_PUSH",
    "PLACEHOLDER_UNIT_TYPES",
    "PUSH_ENEMY_BASE",
    "SCHOOLS",
    "SIDES",
    "THREE_ZONE_MAP",
    "TICK_PHASES",
    "ArmySetup",
    "BaseConfig",
    "BaseState",
    "BattleEvent",
    "BattleEventType",
    "BattleOutcome",
    "BattleResult",
    "BattleSetup",
    "BattleTick",
    "ChipReserve",
    "DeploymentStrip",
    "EventActors",
    "EventEmitter",
    "EventSwing",
    "Formation",
    "MapConfig",
    "Order",
    "OrderKind",
    "Rng",
    "RosterEntry",
    "School",
    "SchoolConfig",
    "SchoolMultiplierTable",
    "SchoolMultipliers",
    "Side",
    "SimConfig",
    "Span",
    "TickContext",
    "TickPhase",
    "Troop",
    "TroopId",
    "TroopSetup",
    "Unit",
    "UnitId",
    "UnitKind",
    "UnitRef",
    "UnitType",
    "UnitTypeCatalog",
    "Vec2",
    "World",
    "ZoneConfig",
    "ZoneOccupancy",
    "build_unit_type_catalog",
    "chip_box",
    "clear_of_chip",
    "create_event_emitter",
    "create_rng",
    "create_tick_context",
    "create_world",
    "deployment_anchor",
    "deployment_band",
    "derive_formation",
    "digest_battle",
    "hold",
    "is_alive",
    "legal_orders",
    "max_ticks",
    "may_attack_base",
    "objective_position",
    "opposing",
    "order_of",
    "orders_by_troop",
    "placeholder_battle",
    "resolve_school_multipliers",
    "rng_from_state",
    "run_battle",
    "seconds_per_tick",
    "serialize_battle",
    "station",
    "step_battle",
    "strip_centre",
    "to_ticks",
    "troop_of",
    "unit_defeated",
    "unit_ref",
    "validate_map_config",
    "validate_order",
    "validate_sim_config",
    "zone_by_id",
    "zone_centre",
    "zone_containing",
    "zone_occupancy",
]
