"""Composing every unit's behavior once, at battle start.

Resolution happens here rather than on the first tick for one reason: a profile
that names a trait no definition covers, or a trait a creature has no capability
for, should fail before the battle runs and not two hundred ticks in. `create_world`
already rejects a roster that names a card it does not have; this is the same
check for behavior data.

The result is immutable and shared by reference across the per-tick snapshots —
see `ResolvedBehavior.__deepcopy__`.

**Units can also arrive mid-battle.** A resummoned summon (JQ-289) is built after
`create_world` has run, so it reaches the field with no behaviour at all — and a
unit with no behaviour is skipped by the decision phase entirely, which means it
would quietly fall back to walking at its station while everything around it was
deciding. `resolve_missing` is what the decision phase calls to catch those; it
leaves already-resolved units alone, so it cannot disturb an intent mid-tick.

Battle-start validation is deliberately *not* repeated for them. `unit_behaviors`
and `mage_personalities` name specific unit ids, and by the time a resummon
happens some of those units are dead and gone — re-checking would reject a
perfectly good library for naming a unit that has since fallen. One consequence
worth knowing: a rebuilt summon gets a new id, so an individual trait override
does not follow it. The override was authored about that individual, and the
replacement is a different one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.sim.ai.capabilities import capabilities_of
from app.sim.ai.intent import UnitAi
from app.sim.ai.profiles import (
    EMPTY_LIBRARY,
    BehaviorIndex,
    BehaviorLibrary,
    index_library,
    personality_refs_for_troop,
    resolve_behavior,
)
from app.sim.types import UnitId
from app.sim.units import UnitTypeCatalog

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from app.sim.world import Troop, Unit


def attach_behavior(
    units: Sequence[Unit],
    troops: Sequence[Troop],
    library: BehaviorLibrary,
    catalog: UnitTypeCatalog,
) -> None:
    """Resolves and attaches every unit's behavior. Mutates `units` in place.

    A battle with no behavior data attaches nothing, so `unit.ai` stays None and
    the decision phase skips every unit. That is not an optimisation — while
    slices B, C and D are unmerged, an empty library has to mean "behave exactly
    as before" or every other slice's fixtures would shift underneath them.
    """
    if is_empty(library):
        return

    index = index_library(library, catalog)

    known: set[UnitId] = {unit.id for unit in units}
    for behavior in library.unit_behaviors:
        if behavior.unit_id not in known:
            raise ValueError(
                f"behavior override names unit {behavior.unit_id!r}, which is not in this battle"
            )

    mages: set[UnitId] = {unit.id for unit in units if unit.kind == "mage"}
    for entry in library.mage_personalities:
        if entry.unit_id not in known:
            raise ValueError(f"personality list names unit {entry.unit_id!r}, which is not in this battle")
        if entry.unit_id not in mages:
            raise ValueError(
                f"personality list names unit {entry.unit_id!r}, which is a summon. "
                f"Personalities are authored on mages and reach their troop from there"
            )

    _resolve(units, troops, index)


def resolve_missing(
    units: Sequence[Unit],
    troops: Sequence[Troop],
    library: BehaviorLibrary,
    catalog: UnitTypeCatalog,
) -> None:
    """Attaches behaviour to units that have none yet, leaving the rest alone.

    For units that arrive after the battle has started. See the module docstring
    on why this does not repeat the battle-start validation.
    """
    if is_empty(library) or all(unit.ai is not None for unit in units):
        return

    _resolve(units, troops, index_library(library, catalog))


def _resolve(units: Sequence[Unit], troops: Sequence[Troop], index: BehaviorIndex) -> None:
    # Walks `troops`, a list, so the refs for each troop are gathered in a fixed
    # order regardless of how the sets above happened to hash.
    for troop in troops:
        refs = personality_refs_for_troop(troop.id, troop.mage_ids, index)
        for unit in units:
            if unit.troop_id != troop.id or unit.ai is not None:
                continue
            unit.ai = UnitAi(
                behavior=resolve_behavior(unit, capabilities_of(unit), index, refs),
                intent=None,
            )


def is_empty(library: BehaviorLibrary) -> bool:
    """Whether a library says anything at all about anything."""
    return not (
        library.traits
        or library.personalities
        or library.profiles
        or library.unit_behaviors
        or library.mage_personalities
    )


def empty_library() -> BehaviorLibrary:
    """The default for a battle that ships no behavior data."""
    return EMPTY_LIBRARY
