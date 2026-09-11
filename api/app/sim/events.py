"""The event stream.

Designed in the first slice rather than retrofitted: adding emission across three
already-written systems later is the cost the parent ticket warns about. Every
system emits through the one emitter in the tick context, and every event carries
the same envelope — when it happened, where, who was involved, and what it moved.

The **swing** is the part that makes the stream worth reading. A highlight reel or
a post-battle summary wants "what changed because of this", not "a thing
occurred", so every event carries zone-score and base-HP deltas and the units it
removed — zeroed when it moved none.

`unitDefeated` is the only type slice A has anything to say with. Orders and zone
flips arrive with JQ-287, ability casts with JQ-288, resummons and dissolves with
JQ-289 — each adding its own member to `BattleEventType`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from app.sim.types import Side, UnitRef, Vec2

BattleEventType = Literal["unitDefeated"]

_NO_DELTA: Mapping[Side, float] = MappingProxyType({"north": 0, "south": 0})


@dataclass(frozen=True)
class EventActors:
    #: Who caused it. None when nothing did — attrition, expiry, a dissolve.
    source: UnitRef | None = None
    #: Who it happened to.
    targets: tuple[UnitRef, ...] = ()


@dataclass(frozen=True)
class EventSwing:
    """What the event moved. Zeroed on an event that moved nothing."""

    zone_score: Mapping[Side, float] = field(default=_NO_DELTA)
    base_hp: Mapping[Side, float] = field(default=_NO_DELTA)
    units_removed: tuple[UnitRef, ...] = ()


@dataclass(frozen=True)
class BattleEvent:
    type: BattleEventType
    tick: int
    position: Vec2
    actors: EventActors
    swing: EventSwing


class EventEmitter:
    """The single emitter every system writes through. One per battle."""

    __slots__ = ("_buffer",)

    def __init__(self) -> None:
        self._buffer: list[BattleEvent] = []

    @property
    def events(self) -> tuple[BattleEvent, ...]:
        """Everything emitted since the last drain, in emission order."""
        return tuple(self._buffer)

    def emit(
        self,
        *,
        type: BattleEventType,
        tick: int,
        position: Vec2,
        actors: EventActors | None = None,
        swing: EventSwing | None = None,
    ) -> BattleEvent:
        """Records an event, filling in the rest of the envelope."""
        event = BattleEvent(
            type=type,
            tick=tick,
            position=position,
            actors=actors if actors is not None else EventActors(),
            swing=swing if swing is not None else EventSwing(),
        )
        self._buffer.append(event)
        return event

    def drain(self) -> list[BattleEvent]:
        """Hands the buffer over and starts a fresh one."""
        drained = self._buffer
        self._buffer = []
        return drained


def create_event_emitter() -> EventEmitter:
    return EventEmitter()


def unit_defeated(
    *, tick: int, position: Vec2, unit: UnitRef, killer: UnitRef | None
) -> dict[str, Any]:
    """The first event type: a unit reached 0 HP and left the field.

    Returns the keyword arguments for `EventEmitter.emit`, so a caller writes
    `emitter.emit(**unit_defeated(...))` and the envelope stays in one place.
    """
    return {
        "type": "unitDefeated",
        "tick": tick,
        "position": position,
        "actors": EventActors(source=killer, targets=(unit,)),
        "swing": EventSwing(units_removed=(unit,)),
    }
