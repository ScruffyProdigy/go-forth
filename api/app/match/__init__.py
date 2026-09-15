"""The match layer: the rules above the battle.

`sim/` runs a battle. This runs a *match* — what a legal plan is, when the
battle starts, what a cast costs, and which of two simultaneous endings wins.
The sim has no opinion about any of it, which is why none of this lives there.

JQ-308 builds the single-round test profile. JQ-187 grows it into best-of-five;
JQ-309 puts a Lobby contract and a realtime session around it. Nothing here
talks to a socket or a database, so both of those wrap it rather than edit it.
"""

from __future__ import annotations

from app.match.controller import (
    CastRejected,
    CastRejection,
    LockedPlan,
    LockSource,
    MatchController,
    MatchPhase,
    base_hp_snapshot,
    new_match,
)
from app.match.energy import SpellEnergy, new_pool
from app.match.events import MatchEvent, MatchEventType
from app.match.outcome import (
    MATCH_ENDING,
    DecidedBy,
    RoundEndReason,
    RoundOutcome,
    terminal_outcome,
    time_up_outcome,
)
from app.match.packages import (
    FIVE_FIRE_PACKAGES,
    OPENING_CATALOG,
    PROVISIONAL_SPELLS,
    SPELL_COSTS,
    MagePackage,
    PackageCatalog,
    validate_catalog,
)
from app.match.plan import (
    Plan,
    PlanRejected,
    PlanRejection,
    TroopPlan,
    suggested_plan,
    validate_plan,
)
from app.match.profile import (
    SINGLE_ROUND_TEST,
    SINGLE_ROUND_TEST_PROFILE,
    MatchProfile,
    validate_profile,
)

__all__ = [
    "FIVE_FIRE_PACKAGES",
    "MATCH_ENDING",
    "OPENING_CATALOG",
    "PROVISIONAL_SPELLS",
    "SINGLE_ROUND_TEST",
    "SINGLE_ROUND_TEST_PROFILE",
    "SPELL_COSTS",
    "CastRejected",
    "CastRejection",
    "DecidedBy",
    "LockSource",
    "LockedPlan",
    "MagePackage",
    "MatchController",
    "MatchEvent",
    "MatchEventType",
    "MatchPhase",
    "MatchProfile",
    "PackageCatalog",
    "Plan",
    "PlanRejected",
    "PlanRejection",
    "RoundEndReason",
    "RoundOutcome",
    "SpellEnergy",
    "TroopPlan",
    "base_hp_snapshot",
    "new_match",
    "new_pool",
    "suggested_plan",
    "terminal_outcome",
    "time_up_outcome",
    "validate_catalog",
    "validate_plan",
    "validate_profile",
]
