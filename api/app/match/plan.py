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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.match import fixtures
from app.match.wire import LoadoutSpell
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
    what reads this is spell resolution — and a resolved sentence that changed
    wording between two interpreters would be the hash-ordering bug the
    conventions file is about.
    """
    found: list[fixtures.MageOption] = []
    for troop in plan.troops:
        mage = fixtures.mage_by_id(troop.mage_id)
        if mage is not None:
            found.append(mage)
    return found


def _spell_is_eligible(spell: fixtures.SpellOption, plan: SubmittedPlan) -> str | None:
    """The reason this spell cannot be equipped, or None if it can."""
    requires = spell.requires
    kind = requires.get("kind")
    if kind == "always":
        return None
    mages = fielded_mages(plan)
    if kind == "signature":
        mage_id = requires.get("mageId")
        if any(mage.id == mage_id for mage in mages):
            return None
        option = fixtures.mage_by_id(str(mage_id))
        name = option.name if option else str(mage_id)
        return f"needs {name} on the field"
    if kind == "tag":
        tag = str(requires.get("tag"))
        if any(tag in mage.tags for mage in mages):
            return None
        return f"needs a fielded mage tagged {tag}"
    return f"has an unreadable requirement ({kind!r})"


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

    for index, spell_id in enumerate(plan.spell_slots):
        if spell_id is None:
            continue
        spell = fixtures.spell_by_id(spell_id)
        if spell is None:
            raise PlanError(f"{spell_id!r} is not a spell on this roster")
        reason = _spell_is_eligible(spell, plan)
        if reason is not None:
            raise PlanError(f"spell {index + 1} — {spell.name} {reason}")


# ---------------------------------------------------------------- resolution --


def _contributors(plan: SubmittedPlan, spell: fixtures.SpellOption) -> list[tuple[str, str]]:
    """(mage name, tag) for each fielded mage carrying a tag the spell reads.

    Mage order, then tag order as the spell lists them. No set iteration, so the
    same plan resolves to the same sentence in every process.
    """
    found: list[tuple[str, str]] = []
    for mage in fielded_mages(plan):
        for tag in spell.reads:
            if tag in mage.tags:
                found.append((mage.name, tag))
    return found


def _effect_text(spell: fixtures.SpellOption, contributors: Sequence[tuple[str, str]]) -> str:
    magnitude = fixtures.BASE_MAGNITUDE + fixtures.PER_CONTRIBUTOR * len(contributors)
    if not contributors:
        return f"{spell.text} At {magnitude:g}, with nothing fielded to raise it."
    tags: list[str] = []
    for _, tag in contributors:
        if tag not in tags:
            tags.append(tag)
    count = len(contributors)
    plural = "" if count == 1 else "s"
    return f"{spell.text} At {magnitude:g} — {', '.join(tags)} from {count} fielded mage{plural}."


def resolve_loadout(plan: SubmittedPlan) -> list[LoadoutSpell]:
    """The spells this plan takes into the round, with **resolved** costs.

    Resolved rather than printed: what a fielded mage's tags do to a spell is
    the server's answer, and the client pricing off the card would let a player
    spend energy they do not have. `LoadoutSpell` is a wire type, so this is
    where the plan layer stops and the contract begins.
    """
    loadout: list[LoadoutSpell] = []
    for spell_id in plan.spell_slots:
        if spell_id is None:
            continue
        spell = fixtures.spell_by_id(spell_id)
        if spell is None:
            continue
        contributors = _contributors(plan, spell)
        loadout.append(
            LoadoutSpell(
                spell_id=spell.id,
                name=spell.name,
                cost=spell.cost,
                effect=_effect_text(spell, contributors),
            )
        )
    return loadout


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
