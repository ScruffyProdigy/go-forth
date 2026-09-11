"""The sim's only source of randomness.

A battle must replay identically from its seed, in this process and in a fresh
one, or the server cannot be the authority on what happened. Two Python-specific
rules follow, and neither has an equivalent in the TypeScript this was ported
from:

* Never use module-level `random`. It is process-global shared state, so one
  caller reseeding it changes another's battle. Everything here is an explicit
  object.
* Never iterate an unordered collection anywhere in the sim. Python randomises
  string hashing per process (`PYTHONHASHSEED`), so `set` iteration order
  differs between interpreters — which passes every in-process test and fails
  in production. Sets are used for membership only.

The generator is mulberry32 — one 32-bit word of state, integer arithmetic only,
so the state serialises into a snapshot as a plain number and the sequence
resumes exactly where it left off. It is the same generator the TypeScript sim
used, and `tests/test_rng.py` pins it to output captured from that
implementation.
"""

from __future__ import annotations

MASK32 = 0xFFFFFFFF
TWO_POW_32 = 1 << 32


class Rng:
    """A seeded generator. Hold one per battle and pass it down the tick context."""

    __slots__ = ("_state",)

    def __init__(self, state: int) -> None:
        # JavaScript's `state | 0` keeps the low 32 bits; masking is the same
        # bit pattern, which is why a negative seed ports unchanged.
        self._state = state & MASK32

    @property
    def state(self) -> int:
        """The state *after* every draw so far. Resume it with `rng_from_state`."""
        return self._state

    def next_uint32(self) -> int:
        """The next draw, as an unsigned 32-bit integer."""
        state = (self._state + 0x6D2B79F5) & MASK32
        self._state = state

        t = ((state ^ (state >> 15)) * (1 | state)) & MASK32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & MASK32)) & MASK32) ^ t
        return (t ^ (t >> 14)) & MASK32

    def next_float(self) -> float:
        """The next draw, scaled into `[0, 1)`."""
        return self.next_uint32() / TWO_POW_32

    def next_int(self, max_exclusive: int) -> int:
        """The next draw, as an integer in `[0, max_exclusive)`."""
        if not isinstance(max_exclusive, int):
            raise TypeError(f"next_int bound must be an integer, got {max_exclusive!r}")
        if max_exclusive < 1:
            raise ValueError(f"next_int bound must be a positive integer, got {max_exclusive}")
        return int(self.next_uint32() / TWO_POW_32 * max_exclusive)


def rng_from_state(state: int) -> Rng:
    """Resumes a generator from a state captured off another one."""
    return Rng(state)


def create_rng(seed: int) -> Rng:
    """Starts a generator from a battle seed."""
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError(f"seed must be an integer, got {seed!r}")
    return Rng(seed)
