"""Steps four and five: pick one, and say what was picked.

Selection is the highest score, and **ties go to the earlier candidate** in the
stable order `candidates.py` produced. That is the whole tie-break, and it is
deliberately not a coin toss: two actions a unit is genuinely indifferent
between should resolve the same way in every replay of the same battle, or the
replay is not one.

Randomness exists but is opt-in. A profile with `tie_break_jitter` above zero
draws one number per candidate from the battle's seeded generator, in candidate
order, which is enough to stop two identical creatures from moving in perfect
lockstep without making anything unreproducible — same seed, same jitter, same
outcome. A profile that leaves it at zero draws nothing at all, so the common
case does not perturb the RNG stream for everyone else.

Nothing here executes anything. The decision becomes an `Intent`, and the
movement and combat phases act on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.factors import FactorContribution, PersonalityInfluence
from app.sim.ai.intent import Intent
from app.sim.ai.observe import Observation
from app.sim.ai.profiles import ResolvedBehavior
from app.sim.ai.scoring import ScoredCandidate, score_candidates
from app.sim.rng import Rng
from app.sim.types import UnitId


@dataclass(frozen=True)
class Decision:
    """What one unit chose, and everything it weighed to get there."""

    unit_id: UnitId
    selected: Candidate
    score: float
    contributions: tuple[FactorContribution, ...]
    #: Which personality tags spoke to the winner, and in which situation.
    influences: tuple[PersonalityInfluence, ...]
    #: Every candidate that was scored, in the order they were scored.
    considered: tuple[ScoredCandidate, ...]


def _with_jitter(
    scored: tuple[ScoredCandidate, ...],
    jitter: float,
    rng: Rng | None,
) -> tuple[ScoredCandidate, ...]:
    """Adds a seeded nudge to each score, or nothing at all when unasked.

    Drawn in candidate order so the same battle draws the same numbers in the
    same sequence; the branch above is why a battle of jitter-free creatures
    consumes no randomness here whatsoever.
    """
    if jitter <= 0 or rng is None:
        return scored

    return tuple(
        ScoredCandidate(
            candidate=entry.candidate,
            score=entry.score + rng.next_float() * jitter,
            contributions=entry.contributions,
            influences=entry.influences,
        )
        for entry in scored
    )


def _select(scored: tuple[ScoredCandidate, ...]) -> ScoredCandidate:
    """Highest score; the earlier candidate wins a tie."""
    best = scored[0]
    for entry in scored[1:]:
        if entry.score > best.score:
            best = entry
    return best


def decide(
    observation: Observation,
    behavior: ResolvedBehavior,
    rng: Rng | None = None,
) -> Decision:
    """Observe -> generate -> score -> select, for one unit, for one tick."""
    candidates = generate_candidates(observation)
    scored = score_candidates(observation, candidates, behavior.weights, behavior.personalities)
    chosen = _select(_with_jitter(scored, behavior.tie_break_jitter, rng))

    return Decision(
        unit_id=observation.unit.id,
        selected=chosen.candidate,
        score=chosen.score,
        contributions=chosen.contributions,
        influences=chosen.influences,
        considered=scored,
    )


def intent_of(decision: Decision) -> Intent:
    """The decision, in the form movement and combat read."""
    candidate = decision.selected
    return Intent(
        kind=candidate.kind,
        target_id=candidate.target_id,
        destination=candidate.destination,
        ability_id=candidate.ability_id,
        score=decision.score,
        contributions=decision.contributions,
        influences=decision.influences,
    )
