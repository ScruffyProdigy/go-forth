"""Plane geometry, kept to operations IEEE-754 specifies exactly.

Add, subtract, multiply, divide and square root only — no trigonometry and no
fractional powers. Those are implementation-defined, and a battle that replays
differently on another interpreter build is not deterministic. `math.sqrt` maps
to the hardware instruction and is correctly rounded, so it is safe.
"""

from __future__ import annotations

import math

from app.sim.types import Vec2


def distance(a: Vec2, b: Vec2) -> float:
    dx = b.x - a.x
    dy = b.y - a.y
    return math.sqrt(dx * dx + dy * dy)


def move_toward(origin: Vec2, target: Vec2, step: float) -> Vec2:
    """Steps `origin` toward `target` by at most `step`, stopping exactly on it."""
    gap = distance(origin, target)
    if gap == 0 or step >= gap:
        return Vec2(target.x, target.y)

    scale = step / gap
    return Vec2(
        origin.x + (target.x - origin.x) * scale,
        origin.y + (target.y - origin.y) * scale,
    )
