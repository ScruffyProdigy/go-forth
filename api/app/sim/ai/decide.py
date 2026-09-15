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

from app.sim.ai import pursuit
from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.factors import FactorContribution
from app.sim.ai.intent import ENGAGING, MOVING_ACTIONS, TARGET_SWITCHED, Commitment, Intent
from app.sim.ai.observe import Observation
from app.sim.ai.profiles import ResolvedBehavior
from app.sim.ai.pursuit import TARGET_SWITCH_MARGIN
from app.sim.ai.scoring import ScoredCandidate, score_candidates
from app.sim.rng import Rng
from app.sim.types import UnitId

#: How much better a *different* action has to be before a unit changes its mind
#: about what it is doing. The same quantity as `TARGET_SWITCH_MARGIN` and for
#: the same reason, applied to the whole decision rather than only to its target;
#: kept as its own name so the two can be tuned apart.
ACTION_HYSTERESIS = TARGET_SWITCH_MARGIN

#: How much better than standing still a step has to be before a unit takes it.
#: See `_worth_moving`, which is where the measurement behind the number is.
#: Provisional, and the one number here a reader should expect to retune: too
#: small and units vibrate, too large and they stop marching.
MOVEMENT_THRESHOLD = 0.06


@dataclass(frozen=True)
class Decision:
    """What one unit chose, and everything it weighed to get there."""

    unit_id: UnitId
    selected: Candidate
    score: float
    contributions: tuple[FactorContribution, ...]
    #: Every candidate that was scored, in the order they were scored.
    considered: tuple[ScoredCandidate, ...]
    #: Why this action won, as one of `intent.REASONS`. Usually the winning
    #: candidate's own reason; a chase that ended on a bound reports the bound
    #: instead, because "it stopped chasing" is the interesting fact and the
    #: action it fell back to is the consequence.
    reason: str = ""
    #: The chase this unit should be running after this decision, or None. The
    #: decision phase writes it to `unit.ai`; `decide` stays pure.
    commitment: Commitment | None = None
    #: Ticks of chase recovery this unit should be carrying afterwards.
    recovery_remaining: int = 0


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


def _hold_committed_target(
    scored: tuple[ScoredCandidate, ...],
    chosen: ScoredCandidate,
    commitment: Commitment | None,
) -> ScoredCandidate:
    """Keeps a committed chase unless something is meaningfully better.

    The ticket's rule: a target switch requires a real improvement, not a
    rounding error. Without hysteresis a unit chasing one of two near-identical
    enemies flips between them every time they jostle, which looks like
    indecision and is worse than either choice — the unit closes on neither.

    The margin is only applied when there is something to hold on to. A
    commitment whose candidate has vanished from the set — the quarry died, left
    reach, or fell outside the leash — imposes nothing: the old action became
    invalid, which is precisely the case the rule exempts.
    """
    if commitment is None or chosen.candidate.target_id == commitment.target_id:
        return chosen

    committed = next(
        (entry for entry in scored if entry.candidate.target_id == commitment.target_id),
        None,
    )
    if committed is None:
        return chosen

    if chosen.score > committed.score + TARGET_SWITCH_MARGIN:
        return chosen
    return committed


def _prefer_incumbent(
    scored: tuple[ScoredCandidate, ...],
    chosen: ScoredCandidate,
    previous: Intent | None,
) -> ScoredCandidate:
    """Keeps doing what it was doing unless something is meaningfully better.

    The general form of the target-switch rule above, and it exists because
    without it a unit dithers at *any* boundary where two forces balance —
    which, with a candidate set re-derived from scratch every tick, is everywhere
    two of them cross.

    Measured, on an iron-bulwark holding a post with an enemy beyond its reach.
    Inside the station tolerance, stepping toward the enemy costs nothing on
    objective progress, so closing wins; one stride later the unit is *on* the
    tolerance edge, stepping further now costs, so walking back to the post wins;
    and it walked back inside, where closing won again. It alternated between two
    positions one map unit apart for the whole battle, committing to a chase and
    abandoning it on every single tick, which also churned the reason a reader of
    a trace would see.

    `CONVENTIONS.md` records this shape twice already, in geometry: a rule that
    decides where a unit stops and a rule that decides what it may do there must
    overlap on an interval rather than meeting at a point. A scoring boundary is
    the same hazard one layer up, and a margin is the interval.

    Identity is the pair `(kind, target_id)` rather than the destination, because
    destinations move under a unit every tick — the point a weapon's reach from a
    walking enemy is a different number each time, and comparing those would make
    every candidate perpetually new.
    """
    if previous is None:
        return chosen

    incumbent_key = (previous.kind, previous.target_id)
    if (chosen.candidate.kind, chosen.candidate.target_id) == incumbent_key:
        return chosen

    incumbent = next(
        (entry for entry in scored if (entry.candidate.kind, entry.candidate.target_id) == incumbent_key),
        None,
    )
    if incumbent is None:
        # Last tick's action is not even legal now. Nothing to be steady about.
        return chosen

    if chosen.score > incumbent.score + ACTION_HYSTERESIS:
        return chosen
    return incumbent


def _worth_moving(
    scored: tuple[ScoredCandidate, ...],
    chosen: ScoredCandidate,
) -> ScoredCandidate:
    """Standing still is the default; a step has to be clearly better than it.

    **This is what stops a unit oscillating around a point, and nothing else
    does.** The reason is structural rather than a matter of tuning. Every factor
    here is a *rate* — objective progress is ground gained this tick, not ground
    held — so `hold` scores exactly zero on it however well placed a unit is,
    while both walking toward the post and walking toward an enemy score
    positive. Moving is therefore better than standing almost everywhere, and
    where the two moves balance, the unit alternates between them.

    Measured on an iron-bulwark holding a post with an enemy beyond its reach.
    The two candidates cross at three map units off the post — closing scores
    +0.0513, returning scores +0.0513, holding scores 0.0000 — and either side of
    that the leader changes by about 0.03 per unit of travel. So the unit stepped
    out, stepped back, stepped out, for the whole battle.

    Neither of the two smaller fixes reaches it, and both were tried. A decision
    margin only widens the band the unit wanders inside, because the band is
    where the scores are close *by construction*. Smoothing the objective
    gradient removes the cliff and leaves the equilibrium exactly where it was.
    What is actually needed is for one candidate to win outright near the
    crossing, and the only candidate that can is the one that does not move: the
    unit settles where no step is worth taking, which with the numbers above is
    within two units of the crossing and then stays there.

    Attacking and casting are exempt. They do not move the unit, so they cannot
    produce this, and a swing that is barely better than standing there is still
    a swing worth taking.
    """
    if chosen.candidate.kind not in MOVING_ACTIONS:
        return chosen

    standing = next((entry for entry in scored if entry.candidate.kind == "hold"), None)
    if standing is None:  # pragma: no cover - `hold` is always generated
        return chosen

    if chosen.score - standing.score >= MOVEMENT_THRESHOLD:
        return chosen
    return standing


def _commit(
    observation: Observation,
    chosen: Candidate,
    released: str | None,
) -> tuple[Commitment | None, int, str]:
    """The chase state this decision leaves behind, and what to call the decision.

    Four outcomes, in the order they are decided:

    * a bound tripped — the chase is dropped, recovery starts, and the *bound*
      is the reason, because "why did it stop" is what a reader came for;
    * the chosen action closes on the enemy already committed to — the chase
      continues untouched, so its start tick keeps counting toward the timeout;
    * the chosen action closes on a different enemy — a new chase, anchored here;
    * anything else — no chase at all.

    Recovery counts down whatever happens, including mid-chase. It is a bar on
    *starting* a chase, not a state a unit sits in.
    """
    recovery = max(0, observation.recovery_remaining - 1)

    if released is not None:
        recovery = _recovery_ticks(observation)
        return None, recovery, released

    if chosen.kind != "advance" or chosen.target_id is None:
        return None, recovery, chosen.reason

    commitment = observation.commitment
    if commitment is not None and commitment.target_id == chosen.target_id:
        return commitment, recovery, chosen.reason

    if chosen.reason == ENGAGING:
        # Already in reach of it. Standing toe to toe is not a chase, and
        # committing to one here would start a timeout running on a fight.
        return None, recovery, chosen.reason

    reason = TARGET_SWITCHED if commitment is not None else chosen.reason
    return pursuit.begin(observation, chosen.target_id), recovery, reason


def _recovery_ticks(observation: Observation) -> int:
    if observation.seconds_per_tick <= 0:
        return 0
    return max(1, round(pursuit.PURSUIT_RECOVERY_SECONDS / observation.seconds_per_tick))


def decide(
    observation: Observation,
    behavior: ResolvedBehavior,
    rng: Rng | None = None,
) -> Decision:
    """Observe -> generate -> score -> select, for one unit, for one tick.

    Plus the one piece of state that cannot be re-derived each tick: a chase, and
    the bounds it runs under. Everything else here is a pure function of the
    field; `commitment` is the exception, and `ai/pursuit.py` explains why it has
    to be.
    """
    released = pursuit.release_reason(observation)
    live = observation.commitment if released is None else None

    candidates = generate_candidates(observation)
    scored = score_candidates(observation, candidates, behavior.weights)
    winner = _select(_with_jitter(scored, behavior.tie_break_jitter, rng))
    steady = _prefer_incumbent(scored, _hold_committed_target(scored, winner, live), observation.previous)
    chosen = _worth_moving(scored, steady)

    commitment, recovery, reason = _commit(observation, chosen.candidate, released)

    return Decision(
        unit_id=observation.unit.id,
        selected=chosen.candidate,
        score=chosen.score,
        contributions=chosen.contributions,
        considered=scored,
        reason=reason,
        commitment=commitment,
        recovery_remaining=recovery,
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
        reason=decision.reason,
        protecting_id=candidate.protecting_id,
    )
