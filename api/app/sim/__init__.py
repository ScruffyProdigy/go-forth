"""The battle sim.

Everything a caller needs is here; nothing here touches the outside world. The
server hands `run_battle` a map, the school configs, a battle's roster data, and a
seed, and gets back the whole battle — tick by tick, with its event stream.

Slice A (JQ-286) of the sim. Orders and zones are JQ-287, energy and abilities
JQ-288, resummoning and resonance JQ-289. See `phases/__init__.py` for where each
of them attaches.

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
from app.sim.ai.fixtures import placeholder_behavior, placeholder_objectives, sample_library
from app.sim.ai.intent import ActionKind, Intent, UnitAi
from app.sim.ai.objective import Objective, ObjectiveFixtures, objective_for
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
    unit_defeated,
)
from app.sim.fixtures import PLACEHOLDER_UNIT_TYPES, placeholder_battle
from app.sim.map import (
    THREE_ZONE_MAP,
    BaseConfig,
    DeploymentStrip,
    MapConfig,
    ZoneConfig,
    validate_map_config,
    zone_containing,
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
    unit_ref,
)

__all__ = [
    "DEFAULT_SIM_CONFIG",
    "FACTORS",
    "IDENTITY_MULTIPLIERS",
    "PLACEHOLDER_UNIT_TYPES",
    "SCHOOLS",
    "SIDES",
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
    "CreatureProfile",
    "Decision",
    "DeploymentStrip",
    "EventActors",
    "EventEmitter",
    "EventSwing",
    "FactorContribution",
    "FactorName",
    "FactorWeights",
    "Intent",
    "MagePersonality",
    "MapConfig",
    "Objective",
    "ObjectiveFixtures",
    "Observation",
    "PersonalityDefinition",
    "PersonalityRef",
    "PersonalityTag",
    "ResolvedBehavior",
    "Rng",
    "RosterEntry",
    "School",
    "SchoolConfig",
    "SchoolMultiplierTable",
    "SchoolMultipliers",
    "ScoredCandidate",
    "Side",
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
    "attach_behavior",
    "build_unit_type_catalog",
    "capabilities_of",
    "create_event_emitter",
    "create_rng",
    "create_tick_context",
    "create_world",
    "decide",
    "digest_battle",
    "generate_candidates",
    "intent_of",
    "max_ticks",
    "objective_for",
    "observe",
    "opposing",
    "placeholder_battle",
    "placeholder_behavior",
    "placeholder_objectives",
    "resolve_school_multipliers",
    "rng_from_state",
    "run_battle",
    "sample_library",
    "score_candidates",
    "seconds_per_tick",
    "serialize_battle",
    "step_battle",
    "supports",
    "to_ticks",
    "unit_defeated",
    "unit_ref",
    "validate_map_config",
    "validate_sim_config",
    "zone_containing",
]
