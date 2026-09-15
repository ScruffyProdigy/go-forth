"""Sweeping the dead off the field, and what their troop makes of it.

Separate from combat so everything resolving this tick sees the same field: a
unit brought to zero stops acting immediately, but only leaves the lists once the
tick is over.

Two of slice D's rules (JQ-289) hang off this phase, because it is where a troop
first learns what it has lost:

* a defeated **summon** leaves a dispelled slot on its troop rather than simply
  disappearing from it (§4.5), which is what the resummon phase refills;
* a troop that has just lost its **last mage** dissolves — every summon it still
  holds leaves the field at once, as one `troopDissolve` event (§4.6).

The bond is local, and deliberately so. A living mage of the same school in a
*different* troop is too far away to help, so it does not stop the dissolve.
That is what makes mage protection the core defensive skill.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.energy import ALLY_DEFEATED
from app.sim.events import troop_dissolved
from app.sim.phases.targeting import is_alive
from app.sim.types import Vec2
from app.sim.world import DispelledSlot, Troop, Unit, World, unit_ref


def _centre(units: list[Unit]) -> Vec2:
    """Where a dissolve reads as having happened: the middle of what dissolved.

    The event envelope wants one position and the bond breaking has no single
    actor — the mage that died is already being swept this tick, and there may
    have been several. The summons are what the player sees vanish.
    """
    return Vec2(
        sum(unit.position.x for unit in units) / len(units),
        sum(unit.position.y for unit in units) / len(units),
    )


class RemovalPhase:
    name = "removal"

    def run(self, world: World, ctx: TickContext) -> None:
        fallen_ids = {unit.id for unit in world.units if not is_alive(unit)}
        if not fallen_ids:
            return

        troops_by_id = {troop.id: troop for troop in world.troops}

        # Walked in world order, never by iterating `fallen_ids`: Python
        # randomises string hashing per process, so iterating that set would
        # order the slots differently in a fresh interpreter. See `rng.py`.
        for unit in world.units:
            if unit.id in fallen_ids and unit.kind == "summon":
                troop = troops_by_id.get(unit.troop_id)
                if troop is not None:
                    troop.dispelled_slots.append(
                        DispelledSlot(type_id=unit.type_id, formation_offset=unit.formation_offset)
                    )

        # Death-triggered charge (JQ-288): a card whose school charges off
        # `allyDefeated` pays out here, while the fallen are still on the field.
        # Counted per troop rather than per side, because support in this game
        # is local (§4.2) — a death across the field is not something a mage
        # feels. Walked in world order for the reason above.
        losses: dict[str, int] = {}
        for unit in world.units:
            if not is_alive(unit):
                losses[unit.troop_id] = losses.get(unit.troop_id, 0) + 1
        if losses:
            for unit in world.units:
                if is_alive(unit) and unit.troop_id in losses:
                    unit.energy_meters[ALLY_DEFEATED] += losses[unit.troop_id]

        had_mages = {troop.id for troop in world.troops if troop.mage_ids}

        world.units = [unit for unit in world.units if unit.id not in fallen_ids]

        for troop in world.troops:
            troop.mage_ids = [uid for uid in troop.mage_ids if uid not in fallen_ids]
            troop.summon_ids = [uid for uid in troop.summon_ids if uid not in fallen_ids]

        for troop in world.troops:
            if troop.id in had_mages and not troop.mage_ids:
                self._dissolve(troop, world, ctx)

    def _dissolve(self, troop: Troop, world: World, ctx: TickContext) -> None:
        """The troop bond breaks: everything this troop still holds leaves (§4.6).

        The summons are not defeated — nothing killed them and nobody is credited
        — so this emits no `unitDefeated`. They are gone for the rest of the
        round and refill with their mages at round end, which is JQ-187's reset.
        """
        dissolving = [unit for unit in world.units if unit.troop_id == troop.id and unit.kind == "summon"]
        if not dissolving:
            return

        # Membership only; the list above is already in world order.
        dissolved_ids = {unit.id for unit in dissolving}
        world.units = [unit for unit in world.units if unit.id not in dissolved_ids]
        troop.summon_ids = [uid for uid in troop.summon_ids if uid not in dissolved_ids]

        ctx.emitter.emit(
            **troop_dissolved(
                tick=world.tick,
                position=_centre(dissolving),
                summons=tuple(unit_ref(unit) for unit in dissolving),
            )
        )


removal_phase = RemovalPhase()
