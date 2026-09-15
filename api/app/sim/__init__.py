"""The battle sim.

Everything a caller needs is here; nothing here touches the outside world. The
server hands `run_battle` a map, the school configs, a battle's roster data, and a
seed, and gets back the whole battle — tick by tick, with its event stream.

**side** first — resonance is a property of a player's roster rather than of the
and abilities JQ-288. See `phases/__init__.py` for where each of them attaches.
attaches.
dissolve inside `phases/removal.py`) and filled in the per-school multiplier
field — so a system reads `ctx.multipliers[unit.side][school]`.
record from the resonance curve (`resonance.py`). That record is now keyed by
resummoning and resonance JQ-289. See `phases/__init__.py` for where each of them
Slice D added resummoning and the troop bond (`phases/resummon.py`, and the
Slices A (JQ-286) and B (JQ-287) of the sim. Energy and abilities are JQ-288,
Slices A (JQ-286) and D (JQ-289) of the sim. Orders and zones are JQ-287, energy

Shared unit behavior — creature profiles, mage personalities, and the
deterministic decision loop that reads them — is JQ-328, in `ai/`. A battle that
ships no behavior library runs without it and behaves exactly as slice A did.

Two Python rules hold the determinism guarantee, neither of which had an
equivalent in the TypeScript this was ported from:

* Never iterate an unordered collection. `PYTHONHASHSEED` is randomised per
  interpreter, so `set` order differs between processes — invisible to any test
  that runs in one. Sets are used for membership only.
* Never use module-level `random`; it is process-global. Randomness comes from an
  explicit `Rng` threaded through the tick context.
"""

from app.sim.ai.attach import attach_behavior
from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.capabilities import Capabilities, capabilities_of, supports
from app.sim.ai.decide import Decision, decide, intent_of
from app.sim.ai.factors import FACTORS, FactorContribution, FactorName, FactorWeights
from app.sim.ai.fixtures import placeholder_behavior, sample_library
from app.sim.ai.intent import ActionKind, Intent, UnitAi
from app.sim.ai.observe import Observation, observe
from app.sim.ai.profiles import (
    BehaviorLibrary,
    CreatureProfile,
    MagePersonality,
    PersonalityDefinition,
    PersonalityRef,
    PersonalityTag,
    ResolvedBehavior,
    TraitDefinition,
    TraitTag,
    UnitBehavior,
)
from app.sim.ai.scoring import ScoredCandidate, score_candidates
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
    resummoned,
    troop_dissolved,
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
from app.sim.resonance import (
    STAT_AXES,
    ResonanceCounts,
    SideResonanceCounts,
    count_resonance,
)
from app.sim.rng import Rng, create_rng, rng_from_state
from app.sim.run_battle import (
    BattleOutcome,
    BattleResult,
    BattleTick,
    run_battle,
    step_battle,
)
from app.sim.schools import (
    DEFAULT_RESONANCE_CURVE,
    IDENTITY_MULTIPLIERS,
    SCHOOLS,
    ResonanceCurve,
    School,
    SchoolConfig,
    SchoolMultipliers,
    SchoolMultiplierTable,
    SideMultiplierTable,
    resolve_school_multipliers,
    resolve_side_multipliers,
    resonance_step,
)
from app.sim.serialize import digest_battle, serialize_battle
from app.sim.types import SIDES, Side, Span, TroopId, UnitId, UnitRef, Vec2, opposing
from app.sim.units import UnitKind, UnitType, UnitTypeCatalog, build_unit_type_catalog
from app.sim.world import (
    ArmySetup,
    BaseState,
    BattleSetup,
    DispelledSlot,
    RosterEntry,
    Troop,
    TroopSetup,
    Unit,
    World,
    create_world,
    is_alive,
    order_of,
    orders_by_troop,
    support_capacity_of,
    troop_of,
    unit_ref,
)
from app.sim.zones import ZoneOccupancy, zone_occupancy

__all__ = [
    "DEFAULT_RESONANCE_CURVE",
    "DEFAULT_SIM_CONFIG",
    "DEFEND_BASE",
    "FACTORS",
    "FORMATION_RANK_GAP",
    "FORMATION_SPACING",
    "IDENTITY_MULTIPLIERS",
    "MAGE_SETBACK_GUARDED",
    "MAGE_SETBACK_PUSH",
    "PLACEHOLDER_UNIT_TYPES",
    "PUSH_ENEMY_BASE",
    "SCHOOLS",
    "SIDES",
    "STAT_AXES",
    "THREE_ZONE_MAP",
    "TICK_PHASES",
    "ActionKind",
    "ArmySetup",
    "BaseConfig",
    "BaseState",
    "BattleEvent",
    "BattleEventType",
    "BattleOutcome",
    "BattleResult",
    "BattleSetup",
    "BattleTick",
    "BehaviorLibrary",
    "Candidate",
    "Capabilities",
    "ChipReserve",
    "CreatureProfile",
    "Decision",
    "DeploymentStrip",
    "DispelledSlot",
    "EventActors",
    "EventEmitter",
    "EventSwing",
    "FactorContribution",
    "FactorName",
    "FactorWeights",
    "Formation",
    "Intent",
    "MagePersonality",
    "MapConfig",
    "Observation",
    "Order",
    "OrderKind",
    "PersonalityDefinition",
    "PersonalityRef",
    "PersonalityTag",
    "ResolvedBehavior",
    "ResonanceCounts",
    "ResonanceCurve",
    "Rng",
    "RosterEntry",
    "School",
    "SchoolConfig",
    "SchoolMultiplierTable",
    "SchoolMultipliers",
    "ScoredCandidate",
    "Side",
    "SideMultiplierTable",
    "SideResonanceCounts",
    "SimConfig",
    "Span",
    "TickContext",
    "TickPhase",
    "TraitDefinition",
    "TraitTag",
    "Troop",
    "TroopId",
    "TroopSetup",
    "Unit",
    "UnitAi",
    "UnitBehavior",
    "UnitId",
    "UnitKind",
    "UnitRef",
    "UnitType",
    "UnitTypeCatalog",
    "Vec2",
    "World",
    "ZoneConfig",
    "ZoneOccupancy",
    "attach_behavior",
    "build_unit_type_catalog",
    "capabilities_of",
    "chip_box",
    "clear_of_chip",
    "count_resonance",
    "create_event_emitter",
    "create_rng",
    "create_tick_context",
    "create_world",
    "decide",
    "deployment_anchor",
    "deployment_band",
    "derive_formation",
    "digest_battle",
    "generate_candidates",
    "hold",
    "intent_of",
    "is_alive",
    "legal_orders",
    "max_ticks",
    "may_attack_base",
    "objective_position",
    "observe",
    "opposing",
    "order_of",
    "orders_by_troop",
    "placeholder_battle",
    "placeholder_behavior",
    "resolve_school_multipliers",
    "resolve_side_multipliers",
    "resonance_step",
    "resummoned",
    "rng_from_state",
    "run_battle",
    "sample_library",
    "score_candidates",
    "seconds_per_tick",
    "serialize_battle",
    "station",
    "step_battle",
    "strip_centre",
    "support_capacity_of",
    "supports",
    "to_ticks",
    "troop_dissolved",
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
