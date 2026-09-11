"""Tick settings.

The battle runs at a fixed tick rate read from here rather than from a constant
buried in the loop: the rate is the unit every duration in the game is expressed
in, and a headless sim with no wall clock has nothing else to measure time with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SimConfig:
    #: Ticks per second. A whole number, so a second is a whole number of ticks.
    tick_rate: int = 20
    #: Backstop length. The design doc's battle phase is 60–90 s (§3.2).
    max_battle_seconds: float = 90


DEFAULT_SIM_CONFIG = SimConfig()


def validate_sim_config(config: SimConfig) -> None:
    if (
        not isinstance(config.tick_rate, int)
        or isinstance(config.tick_rate, bool)
        or config.tick_rate <= 0
    ):
        raise ValueError(
            f"tick rate must be a positive whole number, got {config.tick_rate!r}"
        )
    if not config.max_battle_seconds > 0:
        raise ValueError(
            f"battle length must be positive, got {config.max_battle_seconds!r}"
        )


def seconds_per_tick(config: SimConfig) -> float:
    return 1 / config.tick_rate


def max_ticks(config: SimConfig) -> int:
    """The tick the loop stops at, so a battle always terminates."""
    return math.ceil(config.max_battle_seconds * config.tick_rate)


def to_ticks(seconds: float, config: SimConfig) -> int:
    """Converts a duration in seconds into whole ticks.

    Durations are counted in ticks rather than decremented in seconds on purpose:
    subtracting 0.05 twenty times does not reliably land on zero, and a cooldown
    that sometimes takes an extra tick is a determinism bug waiting to happen.
    """
    return max(1, round(seconds * config.tick_rate))
