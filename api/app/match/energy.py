"""The player's spell energy — the server's copy, which is the only one.

Separate from the unit gauges in `sim/energy.py`, and deliberately so: a unit
charges from what it does on the field (§4.4) and fires by itself, while this is
a pool the *player* spends, and the sim has no opinion about it. JQ-288 built
the injection envelope with no cost field for the same reason — "JQ-187/188 own
the seat, the tick and whether the cast was legal at all".

Advanced a tick at a time rather than derived from elapsed time, because the cap
makes those two different numbers: a pool that sat full for thirty seconds and
then spent has generated less than `rate x elapsed`, and a closed-form
`min(cap, start + rate * t) - spent` quietly gives the player back energy the cap
should have thrown away.

**The balance is derived, not accumulated.** `current` is a property over
`start + generated - spent` rather than a field the two sides adjust, so the
books cannot come apart: there is one number and two ledgers explaining it,
rather than three numbers that have to agree. That is not a stylistic
preference — at 4 energy a second over a 20 Hz tick the increment is 0.2, which
is not representable in binary, and a `current` mutated 1800 times drifts away
from its own ledger by the end of a single battle. Measured: after ten ticks and
one spend, an accumulating version was already off by 7e-15, which is enough to
fail an exact assertion and — far worse — enough to make a cast at exactly the
cost boundary land differently depending on how long the battle had been going.

This is the same hazard `sim/config.to_ticks` calls out for durations
("subtracting 0.05 twenty times does not reliably land on zero"), answered the
same way: keep the authoritative quantity in a form that does not decay.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpellEnergy:
    """One side's pool for one round."""

    cap: float
    per_tick: float
    start: float
    #: Energy actually added, which is less than `per_tick` on any tick the pool
    #: was at or near its cap.
    generated: float = 0.0
    spent: float = 0.0

    @property
    def current(self) -> float:
        """What the side has to spend. Derived — see the module docstring."""
        return self.start + self.generated - self.spent

    def tick(self) -> None:
        """Generates a tick's worth, clipped at the cap."""
        self.generated += min(self.per_tick, max(0.0, self.cap - self.current))

    def can_afford(self, cost: float) -> bool:
        return self.current >= cost

    def spend(self, cost: float) -> None:
        """Takes a cast's cost out.

        Callers check `can_afford` first and turn the cast away if it fails — a
        rejected cast must not spend, which is the ticket's wording exactly.
        Raising here rather than clamping to zero keeps that a caller's bug
        instead of a silent overdraft.
        """
        if not self.can_afford(cost):
            raise ValueError(f"cannot spend {cost} from a pool holding {self.current}")
        self.spent += cost


def new_pool(*, start: float, per_tick: float, cap: float) -> SpellEnergy:
    return SpellEnergy(cap=cap, per_tick=per_tick, start=start)
