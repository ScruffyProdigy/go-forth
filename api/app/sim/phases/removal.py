"""Sweeping the dead off the field.

Separate from combat so everything resolving this tick sees the same field: a
unit brought to zero stops acting immediately, but only leaves the lists once the
tick is over.

Slice D (JQ-289) hangs the dispelled slot and the troop-bond dissolve off this
phase — it is where a troop first learns it has lost its last mage.
"""

from __future__ import annotations

from app.sim.context import TickContext
from app.sim.phases.targeting import is_alive
from app.sim.world import World


class RemovalPhase:
    name = "removal"

    def run(self, world: World, ctx: TickContext) -> None:
        fallen_ids = {unit.id for unit in world.units if not is_alive(unit)}
        if not fallen_ids:
            return

        # `fallen_ids` is tested for membership only, never iterated: Python
        # randomises string hashing per process, so iterating it would order the
        # survivors differently in a fresh interpreter. See `rng.py`.
        world.units = [unit for unit in world.units if unit.id not in fallen_ids]

        for troop in world.troops:
            troop.mage_ids = [uid for uid in troop.mage_ids if uid not in fallen_ids]
            troop.summon_ids = [uid for uid in troop.summon_ids if uid not in fallen_ids]


removal_phase = RemovalPhase()
