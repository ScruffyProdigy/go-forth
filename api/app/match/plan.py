"""A submitted plan: reading it, refusing it, and turning it into an army.

**The server owns validation and the energy spend.** A plan arrives from a phone
over a socket, so nothing about it is trusted: not the mage ids, not the summon
counts, not the orders, and above all not the spell costs. The client's
`plan/derive.ts` answers the same questions to grey out a button; this answers
them to decide what happens.

JQ-308 owns the *depth* of these rules — availability across rounds, the
five-choose-three package draw, the missed-plan and abandonment policy. What is
here is the shape they will deepen: a plan is legal or it is refused with a
reason naming what is wrong, and an illegal one never becomes an army.

`to_army_setup` is the only place a plan becomes sim input, and it supplies no
positions. Placement is derived from the order by `sim/formation.py` — the
design's central constraint (§6.1) — so a field that amounted to a placement
could not be added here even if a plan carried one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.match import fixtures
from app.match.wire import LoadoutSpell, SpellContributor
from app.sim.loadout import (
    DeployedMage,
    LoadoutMenu,
    LoadoutSnapshot,
    effect_summary,
    resolve_menu,
    resolve_slots,
    snapshot_loadout,
)
from app.sim.map import MapConfig
from app.sim.orders import Order, validate_order
from app.sim.types import Side
from app.sim.world import ArmySetup, RosterEntry, TroopSetup


class PlanError(Exception):
    """A plan this server will not field. Always answered to the seat that sent it."""


@dataclass(frozen=True, slots=True)
class PlannedTroop:
    mage_id: str
    summon_ids: tuple[str, ...]
    order: Order


@dataclass(frozen=True, slots=True)
class SubmittedPlan:
    troops: tuple[PlannedTroop, ...]
    #: Slots in screen order; `None` is a legal empty slot.
    spell_slots: tuple[str | None, ...]


# ------------------------------------------------------------------- parsing --


def _parse_order(raw: Any) -> Order:
    if not isinstance(raw, dict):
        raise PlanError("each troop needs an order")
    kind = raw.get("kind")
    if kind == "holdZone":
        zone_id = raw.get("zoneId")
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise PlanError("a hold order must name the zone it holds")
        return Order("holdZone", zone_id.strip())
    if kind in ("defendBase", "pushEnemyBase"):
        return Order(kind)
    raise PlanError(f"{kind!r} is not an order")


def parse_plan(raw: Any) -> SubmittedPlan:
    """Read a plan off the wire, or raise `PlanError` naming the first fault."""
    if not isinstance(raw, dict):
        raise PlanError("plan is required")

    raw_troops = raw.get("troops")
    if not isinstance(raw_troops, list):
        raise PlanError("plan.troops must be an array")

    troops: list[PlannedTroop] = []
    for entry in raw_troops:
        if not isinstance(entry, dict):
            raise PlanError("each plan.troops entry must be an object")
        mage_id = entry.get("mageId")
        if not isinstance(mage_id, str) or not mage_id.strip():
            raise PlanError("each troop needs a mageId")
        raw_summons = entry.get("summonIds", [])
        if not isinstance(raw_summons, list):
            raise PlanError("troop.summonIds must be an array")
        summon_ids: list[str] = []
        for summon_id in raw_summons:
            if not isinstance(summon_id, str) or not summon_id.strip():
                raise PlanError("troop.summonIds must be non-empty strings")
            summon_ids.append(summon_id.strip())
        troops.append(
            PlannedTroop(
                mage_id=mage_id.strip(),
                summon_ids=tuple(summon_ids),
                order=_parse_order(entry.get("order")),
            )
        )

    raw_slots = raw.get("spellSlots", [])
    if not isinstance(raw_slots, list):
        raise PlanError("plan.spellSlots must be an array")
    if len(raw_slots) > fixtures.SPELL_SLOTS:
        raise PlanError(f"a plan carries at most {fixtures.SPELL_SLOTS} spells")
    slots: list[str | None] = []
    for slot in raw_slots:
        if slot is None:
            slots.append(None)
        elif isinstance(slot, str) and slot.strip():
            slots.append(slot.strip())
        else:
            raise PlanError("each spell slot is a spell id or null")

    return SubmittedPlan(troops=tuple(troops), spell_slots=tuple(slots))


# ---------------------------------------------------------------- validation --


def fielded_mages(plan: SubmittedPlan) -> list[fixtures.MageOption]:
    """The mages this plan actually puts on the field, in troop order.

    In troop order rather than sorted, and a list rather than a set, because
    what reads this is spell resolution — and a resolved menu that changed order
    between two interpreters would be the hash-ordering bug the conventions file
    is about.
    """
    found: list[fixtures.MageOption] = []
    for troop in plan.troops:
        mage = fixtures.mage_by_id(troop.mage_id)
        if mage is not None:
            found.append(mage)
    return found


def deployed_mages(plan: SubmittedPlan) -> list[DeployedMage]:
    """This plan's mages as the resolver wants them: instances, with tags.

    The instance id is the troop's own position in the plan, which is also how
    `to_army_setup` names its troops. That matters for the one case the two
    representations differ on: fielding the same mage card twice is two
    deployed instances, counted twice for every tag they carry, and granting one
    menu entry between them (JQ-297). A resolver keyed on the card id could not
    tell those two mages apart.

    Summons are not here, and this is the only place they could have been:
    nothing downstream sees the roster, so "never count summons" is a property
    of the shape rather than of a filter somebody has to remember.
    """
    mages: list[DeployedMage] = []
    for index, troop in enumerate(plan.troops):
        option = fixtures.mage_by_id(troop.mage_id)
        if option is None:
            continue
        mages.append(
            DeployedMage(
                instance_id=f"troop-{index + 1}",
                type_id=option.id,
                name=option.name,
                tags=option.tags,
            )
        )
    return mages


def spell_menu(plan: SubmittedPlan) -> LoadoutMenu:
    """The eligible menu for this plan, resolved against its fielded mages.

    The same call the client's preview makes and the same one lock-in makes.
    Editing troops changes the plan, so the next call returns a different menu —
    there is no cached eligibility to invalidate, which is what makes JQ-297's
    "editing troops updates eligibility and previews immediately" true by
    construction rather than by a subscription somebody has to wire up.
    """
    return resolve_menu(
        mages=deployed_mages(plan),
        roster_access=fixtures.INDEPENDENT_SPELL_ACCESS,
        definitions=fixtures.spell_definitions(),
    )


def validate_plan(plan: SubmittedPlan, map_config: MapConfig) -> None:
    """Raise `PlanError` unless this plan is one the server will field."""
    if not plan.troops:
        raise PlanError("field at least one troop before locking in")
    if len(plan.troops) > fixtures.MAGE_CAP:
        raise PlanError(f"at most {fixtures.MAGE_CAP} mages may be fielded this round")

    # The roster is a multiset owned by the side, so the same summon fielded by
    # two troops draws on one pool. Counted across the whole plan rather than
    # per troop, which is the check a per-troop loop quietly misses.
    used: dict[str, int] = {}

    for troop in plan.troops:
        mage = fixtures.mage_by_id(troop.mage_id)
        if mage is None:
            raise PlanError(f"{troop.mage_id!r} is not a mage on this roster")

        try:
            validate_order(troop.order, map_config)
        except ValueError as err:
            raise PlanError(str(err)) from err

        capacity_used = 0
        for summon_id in troop.summon_ids:
            summon = fixtures.summon_by_id(summon_id)
            if summon is None:
                raise PlanError(f"{summon_id!r} is not a summon on this roster")

            capacity_used += summon.capacity_cost
            used[summon_id] = used.get(summon_id, 0) + 1
            owned = fixtures.SUMMON_COUNTS.get(summon_id, 0)
            if used[summon_id] > owned:
                raise PlanError(f"only {owned} {summon.name} available this round")

            # Support is mandatory and *local*: a mage in another troop is too
            # far away to help (§4.2). The sim rejects this too, at build time —
            # checked here so the player is told in the plan phase rather than
            # having the round fail to start.
            if not any(school in mage.schools for school in summon.schools):
                raise PlanError(f"{mage.name} cannot support {summon.name}")

        if capacity_used > mage.support_capacity:
            raise PlanError(
                f"{mage.name} supports {mage.support_capacity} points of summon, "
                f"and this troop asks for {capacity_used}"
            )

    # Spells last, and against the *resolved* menu rather than a second copy of
    # the access rules. A slot stranded by a troop edit is named with the reason
    # the menu gave, so the refusal reads the same as the greyed card the player
    # was looking at (JQ-297: "invalid slots require a legal replacement").
    for outcome in resolve_slots(spell_menu(plan), plan.spell_slots, fixtures.LOADOUT_RULES):
        if outcome.stranded:
            spell = fixtures.spell_by_id(str(outcome.definition_id))
            name = spell.name if spell is not None else str(outcome.definition_id)
            raise PlanError(f"spell {outcome.index + 1} — {name} {outcome.reason}")


# ---------------------------------------------------------------- resolution --


def resolve_snapshot(plan: SubmittedPlan, side: Side, round_number: int = 1) -> LoadoutSnapshot:
    """Freeze this plan's spells for the round. **The authoritative answer.**

    Everything downstream reads the snapshot: the wire loadout the seat is sent,
    the cost a cast is charged, and the effects the sim fires. Nothing re-derives
    them from the world, so a battle that kills every contributing mage leaves
    the loadout exactly as the plan screen priced it — JQ-297's provisional
    playtest policy, and the reason it is a snapshot rather than a live query.

    Namespaced by side because both seats can equip the same spell and resolve
    it to different numbers, and `BattleSetup.spells` is one catalog.
    """
    return snapshot_loadout(
        namespace=side,
        mages=deployed_mages(plan),
        selection=plan.spell_slots,
        roster_access=fixtures.INDEPENDENT_SPELL_ACCESS,
        definitions=fixtures.spell_definitions(),
        rules=fixtures.LOADOUT_RULES,
        round_number=round_number,
    )


def loadout_spells(snapshot: LoadoutSnapshot) -> list[LoadoutSpell]:
    """The snapshot as the wire carries it.

    Resolved rather than printed, which is the property worth restating: what a
    fielded mage's tags do to a spell is the server's answer, and a client
    pricing off the card would let a player spend energy they do not have.
    `LoadoutSpell` is a wire type, so this is where the plan layer stops and the
    contract begins.
    """
    return [
        LoadoutSpell(
            spell_id=spell.definition_id,
            name=spell.name,
            cost=spell.cost,
            effect=effect_summary(spell),
            contributors=tuple(
                SpellContributor(mage_id=who.instance_id, mage_name=who.mage_name, tag=who.tag)
                for who in spell.contributors
            ),
            tag_support=snapshot.tag_support,
        )
        for spell in snapshot.spells
    ]


def resolve_loadout(plan: SubmittedPlan, side: Side = "north") -> list[LoadoutSpell]:
    """A plan's wire loadout in one step. Convenience over `resolve_snapshot`."""
    return loadout_spells(resolve_snapshot(plan, side))


# ----------------------------------------------------------------- sim input --


def to_army_setup(plan: SubmittedPlan, side: Side) -> ArmySetup:
    """The plan as the sim wants it.

    No positions, no stances, no facings — the order is the whole of what a
    troop is given, and `sim/formation.py` derives the rest (§6.1).
    """
    troops = [
        TroopSetup(
            order=troop.order,
            mages=[RosterEntry(troop.mage_id)],
            summons=[RosterEntry(summon_id) for summon_id in troop.summon_ids],
            id=f"{side}-{index + 1}",
        )
        for index, troop in enumerate(plan.troops)
    ]
    return ArmySetup(side=side, troops=troops)


def default_plan(map_config: MapConfig) -> SubmittedPlan:
    """The legal suggested default, parsed from the same fixture the client is sent.

    Round-tripped through `parse_plan` rather than constructed directly, so a
    fixture the parser would reject fails a test here instead of stranding a
    player who locked in without touching anything.
    """
    plan = parse_plan(fixtures.opening_plan_json(1, map_config))
    validate_plan(plan, map_config)
    return plan
