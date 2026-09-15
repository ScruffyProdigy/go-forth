"""How a round ends, and which ending wins when two land on the same tick.

This is the mechanical half of JQ-308 — deliberately code rather than
configuration, because a rule that can be dialled from a settings file is a rule
nobody has decided. The numbers it reads (the score threshold, the battle's
length) come from `profile.py`; the precedence between outcomes does not.

## The reasons, and why they are separate

Ryan, 2026-09-13: base destruction must not be "presented as merely one round
lost". So `baseDestroyed` is not a variant of `timeUp` with a different winner —
it is a different reason, it ends the **match** rather than the round, and it
carries the remaining base HP so a client can say *how* close it was.

| Reason | Ends | Meaning |
|---|---|---|
| `scoreThreshold` | round | A side reached the threshold; won outright, before the backstop |
| `timeUp` | round | Ran its length. Decided on zone score, then on base HP |
| `annihilation` | round | A side has nothing left on the field |
| `baseDestroyed` | **match** | A base fell. That side loses the match at once |
| `mutualBaseDestroyed` | **match** | Both bases fell on the same tick |

## Precedence within one tick

Checked in the order below, and the order is the policy:

1. **Both bases at zero** → `mutualBaseDestroyed`, a draw. Two spells can land on
   one tick and nothing serialises them against each other, so this is reachable
   rather than theoretical. Symmetric event, symmetric result (Ryan,
   2026-09-15). The sim's own `_base_destroyed` walks `SIDES` and would name
   north; that is an accident of iteration order, not a policy, so this module
   reads the bases itself and never asks.
2. **One base at zero** → `baseDestroyed`. Beats everything else on the tick,
   including a score threshold crossed by the side whose base just fell.
3. **A side wiped out** → `annihilation`, to the side still standing.
4. **Score threshold reached** → `scoreThreshold`. Both on one tick is possible
   (both lanes flip together); the higher score takes it, and an exact tie falls
   through to the same base-HP tiebreak `timeUp` uses.
5. Nothing → the round continues.

At the backstop, `timeUp`: higher zone score wins; equal score is broken on
**remaining base HP** (Ryan, 2026-09-15), which rewards chip damage a pure score
comparison throws away; equal on both is a genuine draw and is reported as one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.match.profile import MatchProfile
from app.sim import SIDES, Side, World

RoundEndReason = Literal[
    "scoreThreshold",
    "timeUp",
    "annihilation",
    "baseDestroyed",
    "mutualBaseDestroyed",
]

#: What settled a round whose reason left a winner open to interpretation.
#: `none` is a real answer: a draw that nothing broke.
DecidedBy = Literal["score", "baseHp", "standing", "baseFell", "none"]

#: The reasons that end the whole match rather than the round.
MATCH_ENDING: frozenset[str] = frozenset({"baseDestroyed", "mutualBaseDestroyed"})


@dataclass(frozen=True)
class RoundOutcome:
    """A finished round, and everything a client needs to narrate it."""

    reason: RoundEndReason
    #: None on a draw, and on a draw only.
    winner: Side | None
    decided_by: DecidedBy
    #: The tick the round ended on.
    tick: int
    zone_score: Mapping[Side, float]
    #: What each base has left. Present on every outcome, not just the base ones:
    #: it is the `timeUp` tiebreak, so it has to be legible there too.
    base_hp: Mapping[Side, float]
    #: The profile this round was played under, carried through so that a
    #: single-round test result can never be mistaken for production Starter.
    profile_label: str
    #: Whose base fell, on a base outcome. Both sides on a mutual destruction.
    destroyed_bases: tuple[Side, ...] = ()

    @property
    def ends_match(self) -> bool:
        """Whether the match is over, as opposed to just this round."""
        return self.reason in MATCH_ENDING


def _scores(world: World) -> dict[Side, float]:
    return {side: world.zone_score[side] for side in SIDES}


def _base_hp(world: World) -> dict[Side, float]:
    return {side: world.bases[side].hp for side in SIDES}


def _fallen_bases(world: World) -> tuple[Side, ...]:
    """Every base at or below zero, in `SIDES` order.

    Walked rather than short-circuited precisely because the count is the thing
    that matters: one is a defeat and two is a draw.
    """
    return tuple(side for side in SIDES if world.bases[side].hp <= 0)


def _standing(world: World) -> tuple[Side, ...]:
    return tuple(side for side in SIDES if any(unit.side == side for unit in world.units))


def _break_tie(world: World, reason: RoundEndReason, profile: MatchProfile) -> RoundOutcome:
    """Equal score: decide on remaining base HP, and report a draw if that is
    level too. Never invents a winner."""
    base_hp = _base_hp(world)
    ranked = sorted(SIDES, key=lambda side: base_hp[side], reverse=True)
    leader, trailer = ranked[0], ranked[1]
    tied = base_hp[leader] == base_hp[trailer]

    return _outcome(
        world,
        reason=reason,
        winner=None if tied else leader,
        decided_by="none" if tied else "baseHp",
        profile=profile,
    )


def _outcome(
    world: World,
    *,
    reason: RoundEndReason,
    winner: Side | None,
    decided_by: DecidedBy,
    profile: MatchProfile,
    destroyed_bases: tuple[Side, ...] = (),
) -> RoundOutcome:
    return RoundOutcome(
        reason=reason,
        winner=winner,
        decided_by=decided_by,
        tick=world.tick,
        zone_score=_scores(world),
        base_hp=_base_hp(world),
        profile_label=profile.label,
        destroyed_bases=destroyed_bases,
    )


def _on_score(world: World, reason: RoundEndReason, profile: MatchProfile) -> RoundOutcome:
    scores = _scores(world)
    ranked = sorted(SIDES, key=lambda side: scores[side], reverse=True)
    leader, trailer = ranked[0], ranked[1]

    if scores[leader] == scores[trailer]:
        return _break_tie(world, reason, profile)
    return _outcome(world, reason=reason, winner=leader, decided_by="score", profile=profile)


def terminal_outcome(world: World, profile: MatchProfile) -> RoundOutcome | None:
    """The round's ending as of this tick, or None if it is still going.

    Called after every tick, so the first ending to occur is the one that
    counts — a threshold crossed at tick 500 ends the round there, whatever
    would have happened at tick 900.
    """
    fallen = _fallen_bases(world)

    if len(fallen) == len(SIDES):
        return _outcome(
            world,
            reason="mutualBaseDestroyed",
            winner=None,
            decided_by="none",
            profile=profile,
            destroyed_bases=fallen,
        )

    if fallen:
        loser = fallen[0]
        survivor = next(side for side in SIDES if side != loser)
        return _outcome(
            world,
            reason="baseDestroyed",
            winner=survivor,
            decided_by="baseFell",
            profile=profile,
            destroyed_bases=fallen,
        )

    standing = _standing(world)
    if len(standing) == 1:
        return _outcome(
            world,
            reason="annihilation",
            winner=standing[0],
            decided_by="standing",
            profile=profile,
        )
    if not standing:
        # Both wiped out on one tick. Nobody holds the field, so nobody takes
        # the round — the same symmetry that makes a double base destruction a
        # draw.
        return _outcome(world, reason="annihilation", winner=None, decided_by="none", profile=profile)

    scores = _scores(world)
    if any(scores[side] >= profile.score_threshold for side in SIDES):
        return _on_score(world, "scoreThreshold", profile)

    return None


def time_up_outcome(world: World, profile: MatchProfile) -> RoundOutcome:
    """The ending when the battle simply ran its length."""
    return _on_score(world, "timeUp", profile)
