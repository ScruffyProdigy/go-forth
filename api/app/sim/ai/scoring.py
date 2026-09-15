"""Step three: score every surviving candidate on the same four factors.

Each factor returns a raw verdict in `[-1, 1]` and the total is the weighted
**mean**, not the weighted sum. That is the detail that makes the numbers
bounded: a unit carrying four maxed-out weights and a unit carrying four neutral
ones both score in `[-1, 1]`, so a heavily-modified creature is opinionated
rather than loud, and adding a fifth factor later would not silently rescale
every existing profile.

Weights never change what is *possible* — `candidates.py` already discarded
anything illegal — only which of the possible things this unit likes. Danger
carries its own sign so that caring about danger and ignoring it are a large
weight and a small one; see `factors.py` on why weights stay non-negative.

Every factor's raw value and weight are kept on the result. Nothing in the sim
reads them, and that is the point: JQ-331 explains a decision by reading them
back rather than by re-running it with instrumentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.candidates import Candidate
from app.sim.ai.factors import FACTORS, FactorContribution, FactorName, FactorWeights, clamp_score
from app.sim.ai.observe import Observation
from app.sim.geometry import distance, move_toward
from app.sim.types import Vec2
from app.sim.world import Unit

#: How far away an ally still counts as support, in map units. Roughly half a
#: zone on the three-zone map. Provisional.
SUPPORT_RADIUS = 60.0
#: The amount of support at which more stops helping.
SUPPORT_SATURATION = 3.0
#: What an attack on a plain, healthy, in-reach enemy is worth before any of
#: the bonuses. See `_target_suitability` on why it is not zero.
ENGAGEABLE = 0.5
#: What closing on a target is worth against actually hitting it.
APPROACH_DISCOUNT = 0.5
#: What an enemy's damage counts for when you are at the very edge of its
#: reach, versus standing on top of it. See `_danger`.
EDGE_EXPOSURE = 0.5
#: An ally in the same troop is worth this many strangers — support is local
#: and mandatory within a troop (design doc 4.2), so it is worth more.
OWN_TROOP_SUPPORT = 2.0


@dataclass(frozen=True)
class ScoredCandidate:
    """A candidate, its total, and the four verdicts that produced it."""

    candidate: Candidate
    #: The weighted mean of the contributions, in `[-1, 1]`.
    score: float
    contributions: tuple[FactorContribution, ...]


def _position_after(observation: Observation, candidate: Candidate) -> Vec2:
    """Where this candidate would leave the unit standing.

    Uses the same `move_toward` the movement phase uses, so the danger a unit
    weighs is the danger it actually walks into and not an approximation of it.
    """
    if candidate.kind == "advance" and candidate.destination is not None:
        return move_toward(observation.unit.position, candidate.destination, observation.step)
    return observation.unit.position


def _find(observation: Observation, unit_id: str | None) -> Unit | None:
    if unit_id is None:
        return None
    for enemy in observation.enemies:
        if enemy.id == unit_id:
            return enemy
    return None


def _objective_progress(observation: Observation, candidate: Candidate, position: Vec2) -> float:
    """Ground gained toward the station, as a fraction of one tick's stride.

    Attacking and holding score zero rather than negative: standing your ground
    is not losing the objective, it just is not advancing it. A candidate that
    walks *away* from the station — closing on an enemy behind you, say — scores
    negative, which is how a unit with a heavy objective weight refuses a chase.
    """
    if candidate.kind != "advance" or observation.step <= 0:
        return 0.0

    station = observation.objective.station
    before = distance(observation.unit.position, station)
    after = distance(position, station)
    return clamp_score((before - after) / observation.step)


def _target_suitability(observation: Observation, candidate: Candidate) -> float:
    """How worthwhile this candidate's target is, attacking it or closing on it.

    A viable enemy inside reach starts at `ENGAGEABLE` rather than at nothing.
    That baseline is doing real work: without it, the best a plain healthy target
    could score was the sum of a few small bonuses, so a single tick of walking —
    which scores a flat 1.0 for heading the right way — beat every attack any
    unit could ever make, and two armies walked straight through each other to
    stand on the opposing bases. A factor that cannot reach the same range as
    the factor beside it is not comparable with it, and comparability is the
    whole basis for adding them up.

    On top of the baseline, in descending order: this swing would finish it, it
    is already hurt, and it hits hard enough to be worth silencing first.
    """
    target = _find(observation, candidate.target_id)
    if target is None or candidate.kind == "hold":
        return 0.0

    unit = observation.unit
    max_hp = target.max_hp if target.max_hp > 0 else 1.0

    kills_now = 1.0 if unit.damage >= target.hp else 0.0
    wounded = clamp_score(1.0 - target.hp / max_hp)
    threat = target.damage / (target.damage + unit.damage) if (target.damage + unit.damage) > 0 else 0.0

    suitability = ENGAGEABLE + 0.30 * kills_now + 0.10 * wounded + 0.10 * threat

    # Walking toward a target serves the same end as swinging at it, just less
    # directly — so it scores the same way, discounted. Without this an
    # aggressive creature could never choose to close on anything: closing is an
    # advance, advances scored nothing here, and the only factor that credits a
    # move is progress toward the station. "Aggressive" would have meant nothing
    # more than "swings at whatever happens to walk into reach".
    return clamp_score(suitability if candidate.kind == "attack" else APPROACH_DISCOUNT * suitability)


def _exposure(observation: Observation, position: Vec2) -> float:
    """Incoming damage at the position this candidate leaves us in, versus HP.

    Two gradients, both of which matter more than they look.

    Being *deep* inside an enemy's reach counts for more than clipping its edge:
    a unit at the fringe can step back out next tick, one in the middle cannot.
    Without that, danger would be a step function — in reach or not — and since a
    unit covers only a few map units per tick, almost every candidate would land
    on the same side of the step and the factor would tell them apart never.

    And it is scaled by *current* HP rather than max, so the same spot reads as
    more dangerous to something already hurt. That is the durability term: a wary
    trait pulls a wounded creature back and leaves a fresh one where it stands.
    """
    incoming = 0.0

    for enemy in observation.enemies:
        gap = distance(position, enemy.position)
        if gap > enemy.range:
            continue
        depth = 1.0 if enemy.range <= 0 else 1.0 - gap / enemy.range
        incoming += enemy.damage * (EDGE_EXPOSURE + (1.0 - EDGE_EXPOSURE) * depth)

    if incoming <= 0:
        return 0.0

    hp = observation.unit.hp if observation.unit.hp > 0 else 1.0
    return -min(1.0, incoming / hp)


def _danger(observation: Observation, candidate: Candidate, position: Vec2) -> float:
    """Exposure over the whole tick, which for a move is both ends of it.

    An advance is scored on the worse of where it starts and where it ends,
    because a unit that turns its back on something already in reach of it eats
    the swing regardless. Scoring only the destination made walking away from a
    fight strictly safer than standing in it, and two armies duly strolled
    through each other and out the far side: every unit disengaged the moment it
    was hit, nobody could re-engage, and a battle that ended in annihilation in
    eighteen seconds without any decision loop ran the full ninety with one.

    Breaking off is still available — it just has to be worth something, rather
    than being free. What it costs to be *chased* while doing it is JQ-329's
    (bounded pursuit and screening), not this ticket's.
    """
    here = _exposure(observation, observation.unit.position)
    if candidate.kind != "advance":
        return here

    # Both are non-positive, so the more dangerous end is the smaller number.
    return min(here, _exposure(observation, position))


def _ally_support(observation: Observation, position: Vec2) -> float:
    """How well covered this position is. Own-troop allies count for more."""
    support = sum(
        OWN_TROOP_SUPPORT if ally.troop_id == observation.unit.troop_id else 1.0
        for ally in observation.allies
        if distance(position, ally.position) <= SUPPORT_RADIUS
    )
    return min(1.0, support / SUPPORT_SATURATION)


def _raw(observation: Observation, candidate: Candidate, factor: FactorName, position: Vec2) -> float:
    if factor == "objective_progress":
        return _objective_progress(observation, candidate, position)
    if factor == "target_suitability":
        return _target_suitability(observation, candidate)
    if factor == "danger":
        return _danger(observation, candidate, position)
    if factor == "ally_support":
        return _ally_support(observation, position)
    raise ValueError(f"{factor!r} is not a factor; expected one of {FACTORS}")


def score_candidate(
    observation: Observation,
    candidate: Candidate,
    weights: FactorWeights,
) -> ScoredCandidate:
    position = _position_after(observation, candidate)

    # Walks FACTORS, never the weights mapping: declared order, not hash order.
    contributions = tuple(
        FactorContribution(
            factor=factor,
            raw=clamp_score(_raw(observation, candidate, factor, position)),
            weight=weights[factor],
        )
        for factor in FACTORS
    )

    total_weight = sum(contribution.weight for contribution in contributions)
    score = (
        sum(contribution.contribution for contribution in contributions) / total_weight
        if total_weight > 0
        else 0.0
    )

    return ScoredCandidate(candidate=candidate, score=score, contributions=contributions)


def score_candidates(
    observation: Observation,
    candidates: tuple[Candidate, ...],
    weights: FactorWeights,
) -> tuple[ScoredCandidate, ...]:
    """Scores in the order given, which `candidates.py` has already made stable."""
    return tuple(score_candidate(observation, candidate, weights) for candidate in candidates)
