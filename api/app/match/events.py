"""What the match layer tells the outside world.

Separate from `sim/events.py`: those are things that happened *in* a battle, and
these are things that happened to the match around it — a phase opening, a plan
locking, a cast being turned away. A client needs both streams and they are not
the same shape, so they are not the same type.

Flat `(type, tick, data)` rather than a class per event, matching the sim's
envelope. The wire contract JQ-309 will carry these over is not designed yet;
what JQ-308 owes it is that every state change *has* an event, not that the
envelope is final.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

MatchEventType = Literal[
    "phaseChanged",
    "planLocked",
    "plansRevealed",
    "spellAccepted",
    "spellRejected",
    "roundEnded",
    "matchEnded",
]


@dataclass(frozen=True)
class MatchEvent:
    type: MatchEventType
    #: The battle tick this happened on. 0 throughout planning, which has no
    #: ticks of its own — the ticket rules out a planning countdown.
    tick: int = 0
    data: Mapping[str, Any] = field(default_factory=dict)
