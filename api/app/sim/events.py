"""The event stream.

Designed in the first slice rather than retrofitted: adding emission across three
already-written systems later is the cost the parent ticket warns about. Every
system emits through the one emitter in the tick context, and every event carries
the same envelope — when it happened, where, who was involved, and what it moved.

The **swing** is the part that makes the stream worth reading. A highlight reel or
a post-battle summary wants "what changed because of this", not "a thing
occurred", so every event carries zone-score and base-HP deltas and the units it
removed — zeroed when it moved none.

`unitDefeated` shipped with slice A; `zoneFlip` and `baseHit` with slice B;
`resummon` and `troopDissolve` with slice D. Ability casts are JQ-288 — each
slice adding its own member to `BattleEventType`.

A `zoneFlip`'s swing is the one that needs saying out loud: it carries the change
in **per-tick income** the flip caused — the new holder gains the zone's rate, the
old holder loses it — not a one-off award. The award itself lands every tick for
as long as the zone is held, and attributing a whole zone's worth of score to the
moment it changed hands would be a lie in either direction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from app.sim.types import Side, UnitRef, Vec2

BattleEventType = Literal["unitDefeated", "zoneFlip", "baseHit", "resummon", "troopDissolve"]

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
    #: The zone the event is about, for the events that are about one. A zone
    #: flip that does not say which zone flipped is not worth reading, and the
    #: renderer's chips are indexed by zone id (JQ-294).
    zone_id: str | None = None


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
        zone_id: str | None = None,
    ) -> BattleEvent:
        """Records an event, filling in the rest of the envelope."""
        event = BattleEvent(
            type=type,
            tick=tick,
            position=position,
            actors=actors if actors is not None else EventActors(),
            swing=swing if swing is not None else EventSwing(),
            zone_id=zone_id,
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


def unit_defeated(*, tick: int, position: Vec2, unit: UnitRef, killer: UnitRef | None) -> dict[str, Any]:
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


def resummoned(*, tick: int, summon: UnitRef, mage: UnitRef, position: Vec2) -> dict[str, Any]:
    """A living mage refilled one of its troop's dispelled slots (§4.5).

    The mage is the source and the rebuilt summon the target, at the mage's own
    position — a troop rebuilds where it stands, which is what makes holding a
    zone sticky.
    """
    return {
        "type": "resummon",
        "tick": tick,
        "position": position,
        "actors": EventActors(source=mage, targets=(summon,)),
        "swing": EventSwing(),
    }


def troop_dissolved(*, tick: int, position: Vec2, summons: tuple[UnitRef, ...]) -> dict[str, Any]:
    """A troop lost its last mage, so every summon it held left at once (§4.6).

    One event for the whole troop rather than one per summon: the bond breaking
    is a single thing that happened, and a highlight reel wants it that way.
    There is no source — nothing killed these units, their support simply ended.
    """
    return {
        "type": "troopDissolve",
        "tick": tick,
        "position": position,
        "actors": EventActors(source=None, targets=summons),
        "swing": EventSwing(units_removed=summons),
    }


def _delta(gaining: Side | None, losing: Side | None, amount: float) -> Mapping[Side, float]:
    """A swing built by walking `SIDES`, never by iterating a dict. See `rng.py`."""
    return MappingProxyType(
        {
            side: (amount if side == gaining else 0) - (amount if side == losing else 0)
            for side in ("north", "south")
        }
    )


def zone_flip(
    *,
    tick: int,
    position: Vec2,
    zone_id: str,
    holder: Side | None,
    previous: Side | None,
    points_per_tick: float,
) -> dict[str, Any]:
    """A zone changed hands — to a side, or to nobody.

    The swing is the change in per-tick income: what the new holder starts
    earning and the old holder stops. A flip into contested or empty carries the
    loss alone, which is the whole of what that moment cost.
    """
    return {
        "type": "zoneFlip",
        "tick": tick,
        "position": position,
        "zone_id": zone_id,
        "swing": EventSwing(zone_score=_delta(holder, previous, points_per_tick)),
    }


def base_hit(
    *,
    tick: int,
    position: Vec2,
    owner: Side,
    attacker: UnitRef,
    damage: float,
) -> dict[str, Any]:
    """A unit under Push enemy base landed a blow on that base."""
    return {
        "type": "baseHit",
        "tick": tick,
        "position": position,
        "actors": EventActors(source=attacker),
        "swing": EventSwing(base_hp=_delta(None, owner, damage)),
    }
