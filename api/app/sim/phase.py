"""What a per-tick phase is.

Its own module so the phases and the list of them do not import each other.
"""

from __future__ import annotations

from typing import Protocol

from app.sim.context import TickContext
from app.sim.world import World


class TickPhase(Protocol):
    """Advances the world in place, once per tick, in the declared order."""

    name: str

    def run(self, world: World, ctx: TickContext) -> None: ...
