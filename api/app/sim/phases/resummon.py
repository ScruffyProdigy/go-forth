"""Resummoning: a troop rebuilds what it has lost, where it stands.

Design doc §4.5. A defeated summon leaves a **dispelled slot** on its troop, and
every living mage in that troop refills one slot every `resummon_pace_seconds`,
at that mage's own position, up to the troop's combined support capacity. Two
mages therefore rebuild twice as fast as one, which is the whole point: a troop
is won by tempo — kill faster than it rebuilds, or reach the mages.

Three things this phase is careful about.

**The clock is its own.** `resummon_remaining` is not `cooldown_remaining`: a
mage rebuilds and attacks on separate timers and neither interrupts the other
(§4.4). Both are counted in whole ticks for the reason `config.to_ticks`
explains — subtracting 0.05 twenty times does not reliably reach zero.

**An idle mage does not bank time.** A mage with nothing to rebuild holds its
timer at a full pace rather than counting down to zero and waiting there. A slot
that opened a moment ago would otherwise be refilled the same tick it appeared,
which is not "every N seconds" by any reading.

**Pace is the school's lever, not this phase's.** The seconds come from the mage
type; the scaling comes from `ctx.multipliers[side][school].resummon_pace_multiplier`,
which resonance populated at battle start. A dual-school mage rebuilds on its
best school's pace — one of its halves being weak should not slow the other down
(§4.11).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.sim.config import to_ticks
from app.sim.context import TickContext
from app.sim.events import resummoned
from app.sim.phases.targeting import is_alive
from app.sim.resonance import apply_stat_axis
from app.sim.world import Troop, Unit, World, support_capacity_of, unit_ref


def resummon_pace_ticks(mage: Unit, ctx: TickContext) -> int | None:
    """How many ticks this mage waits between rebuilds, or None if it never does."""
    if mage.resummon_pace_seconds is None:
        return None

    # Membership-safe: `schools` is a tuple, so this min is order-independent
    # in the only way that matters — the value, not the iteration.
    table = ctx.multipliers[mage.side]
    multiplier = min(table[school].resummon_pace_multiplier for school in mage.schools)
    return to_ticks(mage.resummon_pace_seconds * multiplier, ctx.config)


def _living(unit_ids: Sequence[str], by_id: dict[str, Unit]) -> list[Unit]:
    """The living units behind a troop's id list, in the troop's own order."""
    return [by_id[uid] for uid in unit_ids if uid in by_id and is_alive(by_id[uid])]


class ResummonPhase:
    name = "resummon"

    def run(self, world: World, ctx: TickContext) -> None:
        # Keyed lookup only — never iterated, so hash order cannot reach output.
        by_id = {unit.id: unit for unit in world.units}

        for troop in world.troops:
            self._rebuild(troop, world, ctx, by_id)

    def _rebuild(self, troop: Troop, world: World, ctx: TickContext, by_id: dict[str, Unit]) -> None:
        mages = _living(troop.mage_ids, by_id)
        if not mages:
            return

        capacity = support_capacity_of(mages)
        held = len(_living(troop.summon_ids, by_id))

        for mage in mages:
            pace = resummon_pace_ticks(mage, ctx)
            if pace is None:
                continue

            if not troop.dispelled_slots or held >= capacity:
                mage.resummon_remaining = pace
                continue

            # Arm on the first tick of work rather than trusting the idle branch
            # to have run: a mage that has never had anything to rebuild is
            # still sitting at the zero it was built with, and counting down
            # from there would refill a slot the instant it appeared.
            if mage.resummon_remaining <= 0:
                mage.resummon_remaining = pace

            mage.resummon_remaining -= 1
            if mage.resummon_remaining > 0:
                continue

            summon = self._refill(troop, world, ctx, mage)
            by_id[summon.id] = summon
            held += 1
            mage.resummon_remaining = pace

    def _refill(self, troop: Troop, world: World, ctx: TickContext, mage: Unit) -> Unit:
        """Puts one dispelled summon back on the field at its mage's position."""
        slot = troop.dispelled_slots.pop(0)
        unit_type = ctx.unit_types.get(slot.type_id)
        if unit_type is None:
            raise ValueError(
                f"troop {troop.id} holds a dispelled slot for {slot.type_id}, "
                f"which is not in the battle's unit type catalog"
            )

        summon = Unit(
            id=f"{troop.id}-u{troop.next_unit_ordinal}",
            type_id=unit_type.id,
            kind=unit_type.kind,
            schools=unit_type.schools,
            side=troop.side,
            troop_id=troop.id,
            max_hp=unit_type.max_hp,
            damage=unit_type.damage,
            range=unit_type.range,
            speed=unit_type.speed,
            attack_cooldown_seconds=unit_type.attack_cooldown_seconds,
            hp=unit_type.max_hp,
            position=mage.position,
            support_capacity=unit_type.support_capacity,
            resummon_pace_seconds=unit_type.resummon_pace_seconds,
        )
        troop.next_unit_ordinal += 1
        # A rebuilt summon is as strong as the one it replaces: the axis is
        # applied when a unit reaches the field, not only at battle start.
        apply_stat_axis(summon, ctx.multipliers[troop.side])

        world.units.append(summon)
        troop.summon_ids.append(summon.id)

        ctx.emitter.emit(
            **resummoned(
                tick=world.tick,
                summon=unit_ref(summon),
                mage=unit_ref(mage),
                position=mage.position,
            )
        )
        return summon


resummon_phase = ResummonPhase()
