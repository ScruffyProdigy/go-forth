"""Reading the order/objective contract JQ-287 owns, without owning any of it.

JQ-287 defines orders, derives each unit's station from its troop's order, and
restricts base attacks to troops pushing the enemy base. This ticket consumes
that; it does not get a vote in it. So everything here is read-only, and the two
facts it reads are deliberately the narrowest pair that makes a decision:

* **where this unit is supposed to be standing** — its assigned station, which
  JQ-287's orders phase writes to `unit.destination` every tick, before this one
  runs. Because it is rewritten every tick, a diversion the decision loop commits
  to is undone by default on the next tick: "go back to your post" costs nothing
  to implement.
* **whether this unit may take the enemy base as an objective** — true only for
  a troop ordered to push it.

**The seam.** While JQ-287 is in flight there is no `Troop.order` to read, so
this module falls back to fixture facts. It does that structurally — a
`getattr` for the field, a string compare on `order.kind` — and never imports
`app.sim.orders`. That is not squeamishness: `tests/sim/test_purity.py` walks
this package's import graph and reads every `app.sim.*` module it finds, so
importing a module that does not exist yet would break the suite rather than
degrade. When slice B lands, delete `ObjectiveFixtures` and the `order is None`
branch; nothing else here changes.

Base *damage* is JQ-287's. `may_attack_base` gates only whether the enemy base
is allowed to be a destination worth scoring.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from app.sim.map import MapConfig
from app.sim.types import TroopId, Vec2, opposing

if TYPE_CHECKING:  # pragma: no cover - `world.py` holds the fixtures, so this
    # module must stay a leaf. Nothing below needs these at runtime: reading an
    # order is attribute access, and that is also how the JQ-287 seam works.
    from app.sim.world import Troop, Unit, World

#: JQ-287's `OrderKind` for a troop told to push the enemy base. Compared as a
#: string so this module need not import theirs. It is part of their contract,
#: so a change to it is a change we have to be told about.
PUSH_ENEMY_BASE = "pushEnemyBase"


@dataclass(frozen=True)
class Objective:
    """The two objective facts a decision needs."""

    #: Where this unit is supposed to be standing.
    station: Vec2
    #: Whether the enemy base is a legal objective for this unit's troop.
    may_attack_base: bool


@dataclass(frozen=True)
class ObjectiveFixtures:
    """Objective facts supplied by fixtures until JQ-287 lands.

    The ticket allows exactly this. Kept out of `World` because it is static
    configuration like the map, not battle state — nothing mutates it, so it
    cannot drift between a run and its replay.
    """

    #: Assigned station per troop. A troop not listed marches on the enemy base.
    stations: Mapping[TroopId, Vec2] = field(default_factory=lambda: MappingProxyType({}))
    #: Troops allowed to take the enemy base. Membership only — never iterated.
    push_troops: frozenset[TroopId] = frozenset()
    #: What a troop absent from `push_troops` gets. True keeps slice A's
    #: "everyone marches on the base" behavior runnable before orders exist.
    default_may_attack_base: bool = True

    def __deepcopy__(self, memo: dict[int, Any]) -> ObjectiveFixtures:
        """Frozen configuration, so the per-tick snapshots share one."""
        return self


DEFAULT_FIXTURES = ObjectiveFixtures()


def troop_of(world: World, unit: Unit) -> Troop | None:
    for troop in world.troops:
        if troop.id == unit.troop_id:
            return troop
    return None


def enemy_base_position(map_config: MapConfig, unit: Unit) -> Vec2:
    return map_config.bases[opposing(unit.side)].position


def objective_for(
    world: World,
    unit: Unit,
    map_config: MapConfig,
    fixtures: ObjectiveFixtures = DEFAULT_FIXTURES,
) -> Objective:
    """This unit's station and base permission, from JQ-287 if it is there."""
    troop = troop_of(world, unit)
    order = getattr(troop, "order", None) if troop is not None else None

    if order is None:
        station = fixtures.stations.get(unit.troop_id)
        return Objective(
            station=station if station is not None else enemy_base_position(map_config, unit),
            may_attack_base=(
                unit.troop_id in fixtures.push_troops
                if fixtures.push_troops
                else fixtures.default_may_attack_base
            ),
        )

    # JQ-287's orders phase has already written this unit's station for the tick.
    station = unit.destination
    return Objective(
        station=station if station is not None else enemy_base_position(map_config, unit),
        may_attack_base=getattr(order, "kind", None) == PUSH_ENEMY_BASE,
    )
