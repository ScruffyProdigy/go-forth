"""A plan, what makes one legal, and what the server does when none arrives.

The plan is the whole of what a player gives the server for a round: which three
packages they field, where each troop is sent, and which spells they carry. It
is validated *here*, before a battle exists, so that an illegal plan is a
rejection with a reason rather than a `ValueError` out of `create_world` — the
sim builds worlds, it does not police clients.

Every rule below has a reason code, and the codes are the contract: a client
renders them, and the tests assert on them rather than on message text.

**Suggested legal defaults are not a nicety.** JQ-308 asks for them twice — once
as something to show a player who has not decided, and once as the answer to a
player who never decides at all. They are the same object, which is why
`suggested_plan` is the only place either comes from: a default that could be
illegal would turn a missed plan into a crash at the worst possible moment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.match.packages import PackageCatalog
from app.match.profile import MatchProfile
from app.sim import MapConfig, Order, Side, UnitType, legal_orders

#: Why a plan was refused. The wire contract; message text is for humans.
PlanRejection = Literal[
    "wrongPhase",
    "alreadyLocked",
    "wrongTroopCount",
    "duplicatePackage",
    "unknownPackage",
    "illegalOrder",
    "overCapacity",
    "unsupportedSummon",
    "wrongSpellCount",
    "duplicateSpell",
    "ineligibleSpell",
]


class PlanRejected(Exception):
    """An illegal plan. Carries the code a client keys off."""

    def __init__(self, reason: PlanRejection, detail: str) -> None:
        super().__init__(detail)
        self.reason: PlanRejection = reason
        self.detail = detail


@dataclass(frozen=True)
class TroopPlan:
    """One troop: which package, and the one order it is under."""

    package_id: str
    order: Order


@dataclass(frozen=True)
class Plan:
    """A side's whole round.

    `spell_ids` is JQ-297's round loadout snapshot: chosen during planning,
    fixed at lock, and the only spells the side may cast all round. Snapshotting
    it here rather than checking a live menu mid-battle is what makes a cast
    cheap to validate and impossible to widen after the reveal.
    """

    troops: tuple[TroopPlan, ...] = field(default_factory=tuple)
    spell_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def package_ids(self) -> tuple[str, ...]:
        return tuple(troop.package_id for troop in self.troops)


def _entourage_size(catalog: PackageCatalog, package_id: str) -> int:
    package = catalog.by_id[package_id]
    return sum(entry.count for entry in package.entourage)


def _capacity_of(mage: UnitType) -> int:
    return mage.support_capacity or 0


def validate_plan(
    plan: Plan,
    catalog: PackageCatalog,
    map_config: MapConfig,
    profile: MatchProfile,
) -> None:
    """Raises `PlanRejected` unless every rule the ticket lists is satisfied.

    Order matters only for which reason a doubly-illegal plan reports; the
    sequence runs cheapest and most structural first, so that a plan with the
    wrong number of troops is told *that* rather than something about a spell.
    """
    by_id = catalog.by_id
    types = catalog.types

    if len(plan.troops) != profile.packages_chosen:
        raise PlanRejected(
            "wrongTroopCount",
            f"a plan fields {profile.packages_chosen} troops, got {len(plan.troops)}",
        )

    seen: list[str] = []
    for troop in plan.troops:
        if troop.package_id not in by_id:
            raise PlanRejected("unknownPackage", f"{troop.package_id} is not on the menu")
        if troop.package_id in seen:
            # Each package is one instance. Two troops of the same package would
            # be a roster the fixed-entourage rule exists to prevent.
            raise PlanRejected("duplicatePackage", f"{troop.package_id} is chosen twice")
        seen.append(troop.package_id)

    allowed = legal_orders(map_config)
    for troop in plan.troops:
        if troop.order not in allowed:
            raise PlanRejected(
                "illegalOrder",
                f"{troop.order} is not an order this map offers",
            )

    for troop in plan.troops:
        package = by_id[troop.package_id]
        mage = types[package.mage_type_id]
        size = _entourage_size(catalog, troop.package_id)
        if size > _capacity_of(mage):
            raise PlanRejected(
                "overCapacity",
                f"{package.id} fields {size} summons behind a mage supporting {_capacity_of(mage)}",
            )

        # The same rule `world._assert_supported` applies at build time, applied
        # early so that an unsupportable package is a rejection rather than a
        # crash three calls later. Support is mandatory and local (§4.2).
        supported = set(mage.schools)
        for entry in package.entourage:
            summon = types[entry.type_id]
            if not any(school in supported for school in summon.schools):
                raise PlanRejected(
                    "unsupportedSummon",
                    f"{package.id} has no mage able to support {entry.type_id} ({'/'.join(summon.schools)})",
                )

    if len(plan.spell_ids) != profile.spells_per_round:
        raise PlanRejected(
            "wrongSpellCount",
            f"a round loadout carries {profile.spells_per_round} spells, got {len(plan.spell_ids)}",
        )
    if len(set(plan.spell_ids)) != len(plan.spell_ids):
        raise PlanRejected("duplicateSpell", "a spell is carried twice")

    eligible = catalog.eligible_spells(plan.package_ids)
    for spell_id in plan.spell_ids:
        if spell_id not in eligible:
            raise PlanRejected(
                "ineligibleSpell",
                f"{spell_id} is not offered by any package this plan chose",
            )


def suggested_plan(
    side: Side,
    catalog: PackageCatalog,
    map_config: MapConfig,
    profile: MatchProfile,
) -> Plan:
    """A legal plan, for a player who has not made one.

    Shown as the starting state of the plan screen, and submitted on that
    player's behalf if the backstop expires (Ryan, 2026-09-15: auto-lock the
    suggested default rather than forfeit, so an idle player loses on the field
    rather than on a technicality).

    Deliberately *unremarkable* rather than good: the first packages on the
    menu, spread across the map's lanes and then told to push. A default that
    tried to be strong would be a strategy the server plays for you, and a
    player who never edits it should lose to one who did.

    Identical for both sides. The map is symmetric, and a default that differed
    by side would hand one of them an opening the other has to find.
    """
    chosen = catalog.packages[: profile.packages_chosen]
    holds = [order for order in legal_orders(map_config) if order.kind == "holdZone"]
    push = next(order for order in legal_orders(map_config) if order.kind == "pushEnemyBase")

    orders: list[Order] = []
    for index in range(len(chosen)):
        # One troop to each lane, and anything left over goes forward. With two
        # lanes and three troops that is hold/hold/push.
        orders.append(holds[index] if index < len(holds) else push)

    package_ids = tuple(package.id for package in chosen)
    eligible = catalog.eligible_spells(package_ids)

    return Plan(
        troops=tuple(
            TroopPlan(package_id=package.id, order=order)
            for package, order in zip(chosen, orders, strict=True)
        ),
        spell_ids=eligible[: profile.spells_per_round],
    )
