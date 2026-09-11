"""Shared vocabulary: the handful of types every sim module speaks in."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

#: The two sides of the map. Portrait orientation, so north is the top of the screen.
Side = Literal["north", "south"]

SIDES: tuple[Side, ...] = ("north", "south")


def opposing(side: Side) -> Side:
    """The opposing side."""
    return "south" if side == "north" else "north"


class Vec2(NamedTuple):
    """A point in map space, which is portrait: `y` runs down the lane, north to south."""

    x: float
    y: float


@dataclass
class Span:
    """An interval along one axis. `from` is a keyword in Python, hence start/end."""

    start: float
    end: float


UnitId = str
TroopId = str


class UnitRef(NamedTuple):
    """How a unit appears in the event stream.

    Enough to identify it without holding a reference to mutable state, so a
    drained stream stays readable after the battle has moved on.
    """

    unit_id: UnitId
    troop_id: TroopId
    side: Side
    type_id: str
