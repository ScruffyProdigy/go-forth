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

**Weights arrive per candidate, not per unit.** A unit's standing weights are
composed once at battle start, but a personality's contextual rules (JQ-330) can
only be resolved against a particular thing it could do — whether an ally is
under threat is a fact about this tick. So each candidate is scored against the
standing weights plus whatever rules matched *it*, clamped again. Two
consequences worth knowing before reading a surprising score:

* The denominator differs between candidates, since it is the sum of that
  candidate's weights. The total stays inside `[-1, 1]` either way, because it
  is still a weighted mean of values that are.
* Raising the weight on a factor whose raw value sits below a candidate's mean
  *lowers* that candidate's score. That is correct and load-bearing: it is how
  "care more about staying with your troop" removes a pursuit from contention
  without anyone having to price danger differently.

Every factor's raw value and weight are kept on the result. Nothing in the sim
reads them, and that is the point: JQ-331 explains a decision by reading them
back rather than by re-running it with instrumentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.candidates import Candidate
from app.sim.ai.factors import (
    FACTORS,
    FactorContribution,
    FactorName,
    FactorWeights,
    PersonalityInfluence,
    clamp_score,
    clamp_weight,
    freeze_weights,
)
from app.sim.ai.observe import Observation
from app.sim.ai.profiles import PersonalityRule, ResolvedPersonality
from app.sim.ai.situation import holds
from app.sim.effects import AreaDamage, DashToTarget
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
#: How much better a ready ability is than the plain swing underneath it, when
#: its own mechanic actually accomplishes something. A creature with a feature
#: that gives it an edge prefers to use that feature — but preferring is what
#: this is, a thumb on the scale rather than a rule, so a dutiful unit can still
#: walk past a cast it could make.
ABILITY_PREMIUM = 1.3
#: What closing on something whose reach matches your own is worth: nothing over
#: the swing itself. A melee enemy was walking into contact anyway, so the dash
#: bought a moment at most.
DASH_ON_EQUAL_REACH = 1.0
#: And what it is worth against something that badly out-ranges you. This is the
#: dash's real purpose — not arriving sooner, but taking away the gap the enemy
#: was using to hit you for free. Higher than the generic premium because it
#: denies the target its whole way of fighting rather than merely helping yours.
DASH_ON_LONGER_REACH = 1.6
#: And what it is worth when the mechanic accomplishes nothing — a dash at
#: something already in reach moves the unit nowhere and the gauge is gone.
#: Below one, so a plain attack outscores a wasted ability and the gauge is kept.
WASTED_ABILITY_DISCOUNT = 0.5
#: Enemies inside an area ability's radius at which spending it is clearly worth
#: it. Fewer than this scales down rather than being refused outright.
AREA_WORTH_IT = 2.0
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
    #: Which personality tags spoke to this candidate, in which situation, and
    #: by how much. Empty when none did — including when every one of them was
    #: dialled to zero. Diagnostics only; nothing branches on it.
    influences: tuple[PersonalityInfluence, ...] = ()


def _dash_of(observation: Observation) -> DashToTarget | None:
    ability = observation.ability
    if ability is None:
        return None
    return next((e for e in ability.effects if isinstance(e, DashToTarget)), None)


def _position_after(observation: Observation, candidate: Candidate) -> Vec2:
    """Where this candidate would leave the unit standing.

    Uses the same `move_toward` the movement phase uses, so the danger a unit
    weighs is the danger it actually walks into and not an approximation of it.

    A cast that dashes is projected the same way, mirroring `_resolve_dash` —
    which is the point of deriving behaviour from ability mechanics rather than
    from a label on the card. A unit weighing a pounce weighs where the pounce
    puts it, so the same danger and objective factors judge it without either
    knowing what a pounce is.
    """
    if candidate.kind == "advance" and candidate.destination is not None:
        return move_toward(observation.unit.position, candidate.destination, observation.step)

    if candidate.kind == "cast":
        dash = _dash_of(observation)
        target = _find(observation, candidate.target_id)
        if dash is not None and target is not None:
            gap = distance(observation.unit.position, target.position)
            step = min(dash.max_distance, gap - dash.stop_short)
            if step > 0:
                return move_toward(observation.unit.position, target.position, step)

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
    if candidate.kind == "cast" and candidate.target_id is None:
        # Lands on the caster: judged by how much of the field it covers.
        return _area_suitability(observation)

    target = _find(observation, candidate.target_id)
    if target is None or candidate.kind == "hold":
        return 0.0

    unit = observation.unit
    max_hp = target.max_hp if target.max_hp > 0 else 1.0

    kills_now = 1.0 if unit.damage >= target.hp else 0.0
    wounded = clamp_score(1.0 - target.hp / max_hp)
    threat = target.damage / (target.damage + unit.damage) if (target.damage + unit.damage) > 0 else 0.0

    suitability = ENGAGEABLE + 0.30 * kills_now + 0.10 * wounded + 0.10 * threat

    if candidate.kind == "cast":
        return clamp_score(suitability * _ability_multiplier(observation, candidate))

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
    more dangerous to something already hurt. That is the durability term.

    **What this factor cannot do, and a reader will assume it does.** Danger
    chooses between degrees of engagement; it cannot produce a disengagement,
    because none of the three verbs this ticket owns expresses one. A unit
    standing on its station under fire has exactly three options — hold, attack
    something in reach, or advance, and the only advance on offer leads *toward*
    an enemy, since it is already on its station. So every candidate is scored
    and the least-bad wins, but "leave" was never among them: a wary mage at a
    fifth of its health, surrounded, still picks a swing. See
    `test_no_candidate_expresses_a_retreat`, which pins that.

    This is faithful to the ticket — advance, attack, hold, and retreat lives
    with positioning and bounded pursuit in JQ-329 — but it means a heavy danger
    weight buys caution about where to *go*, not a survival instinct. Anyone
    tuning these numbers expecting units to withdraw will be tuning the wrong
    dial until that verb exists.

    **And it does not keep units apart.** It is tempting to read this factor as
    the thing standing between the sim and two units occupying one point, because
    once a unit is acting on an intent it has bypassed the engage-en-route hold
    that stops everything else walking into contact. It is not: danger makes
    closing *unattractive*, and a unit whose objective weight outvotes it walks
    all the way on. Measured, opposing units come to rest coincident for seconds
    at a time. See "Movement does not guarantee separation" in `CONVENTIONS.md`
    for both sets of numbers, and JQ-380 for the decision — this is a consequence
    of the press-past capability rather than a defect in either rule.
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


def _matches(
    rule: PersonalityRule,
    observation: Observation,
    candidate: Candidate,
    position: Vec2,
) -> bool:
    """All four of a rule's dimensions, in the cheapest order.

    Actions first because it is a tuple membership test and rules are commonly
    scoped to one verb; the situation next; the exceptions last, since they are
    only reached by a rule that was otherwise about to fire. Every exception is
    read at the same influence range as the rule itself — an exception that
    looked further than the rule it guards could silence something the rule
    could not see in the first place.
    """
    if rule.actions and candidate.kind not in rule.actions:
        return False
    if not holds(rule.when, observation, candidate, position, rule.influence):
        return False
    return not any(
        holds(exception, observation, candidate, position, rule.influence) for exception in rule.unless
    )


def contextual_weights(
    observation: Observation,
    candidate: Candidate,
    position: Vec2,
    weights: FactorWeights,
    personalities: tuple[ResolvedPersonality, ...],
) -> tuple[FactorWeights, tuple[PersonalityInfluence, ...]]:
    """The standing weights, plus whatever this candidate's situation woke up.

    Deltas **sum**. Two tags that both speak to a candidate both apply, and
    neither wins for having been authored first — the same rule composition
    follows everywhere else, and the reason it matters most here is that this is
    where a mage gets to be two things at once. A reckless, protective mage
    intercepting a threat to an ally has both tags pushing the same way, because
    each is speaking to a different part of the same moment.

    Walks personalities in tag order and rules in authored order, both fixed, so
    the additions happen in the same sequence in every process.
    """
    if not personalities:
        return weights, ()

    adjusted: dict[FactorName, float] = {factor: weights[factor] for factor in FACTORS}
    influences: list[PersonalityInfluence] = []

    for personality in personalities:
        for rule in personality.rules:
            if not _matches(rule, observation, candidate, position):
                continue
            for factor in FACTORS:
                # `.get` rather than indexing: a resolved rule carries all four
                # factors, but an author's raw rule carries only what it names,
                # and a KeyError from inside the scoring loop is a miserable way
                # to learn that. A factor a rule does not mention is no delta.
                delta = rule.weights.get(factor, 0.0)
                if delta == 0.0:
                    # Includes every rule of a tag dialled to zero: it matched,
                    # and it had nothing to say. Recording that as an influence
                    # would fill a decision trace with silence.
                    continue
                adjusted[factor] += delta
                influences.append(
                    # `rule.when` is the whole answer to "which situation woke
                    # this", which is why a rule carries exactly one.
                    PersonalityInfluence(
                        tag=personality.tag,
                        context=rule.when,
                        factor=factor,
                        delta=delta,
                    )
                )

    return (
        freeze_weights({factor: clamp_weight(adjusted[factor]) for factor in FACTORS}),
        tuple(influences),
    )


def score_candidate(
    observation: Observation,
    candidate: Candidate,
    weights: FactorWeights,
    personalities: tuple[ResolvedPersonality, ...] = (),
) -> ScoredCandidate:
    position = _position_after(observation, candidate)
    weights, influences = contextual_weights(observation, candidate, position, weights, personalities)

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

    return ScoredCandidate(
        candidate=candidate,
        score=score,
        contributions=contributions,
        influences=influences,
    )


def score_candidates(
    observation: Observation,
    candidates: tuple[Candidate, ...],
    weights: FactorWeights,
    personalities: tuple[ResolvedPersonality, ...] = (),
) -> tuple[ScoredCandidate, ...]:
    """Scores in the order given, which `candidates.py` has already made stable."""
    return tuple(score_candidate(observation, candidate, weights, personalities) for candidate in candidates)


def _ability_multiplier(observation: Observation, candidate: Candidate) -> float:
    """Whether this ability's own mechanic accomplishes anything, as a scale.

    The premium is the tactical instinct that a creature with a feature giving it
    an edge would rather use that feature than swing. The discount is the other
    half of the same instinct: if the circumstances are not right, the feature is
    worth holding, and spending it anyway is worse than an ordinary attack
    because the gauge does not come back.

    Read off the effects rather than off the ability's id, so a new card with a
    dash on it is judged correctly by code that has never heard of it.
    """
    dash = _dash_of(observation)
    if dash is None:
        return ABILITY_PREMIUM

    target = _find(observation, candidate.target_id)
    if target is None:
        return WASTED_ABILITY_DISCOUNT

    gap = distance(observation.unit.position, target.position)
    would_move = min(dash.max_distance, gap - dash.stop_short)

    # Already close enough to swing: the dash buys nothing the next attack would
    # not, and the gauge could have carried this unit into the next fight.
    if gap <= observation.capabilities.reach or would_move <= 0:
        return WASTED_ABILITY_DISCOUNT

    return _dash_value_against(observation.capabilities.reach, target.range)


def _dash_value_against(own_reach: float, target_reach: float) -> float:
    """What closing costs the target, which is what the dash is really worth.

    A dash at something that fights at your own range is worth little: it was
    coming to you regardless, and arriving a second earlier is the whole of the
    gain. A dash at something that out-ranges you is worth a great deal, because
    the gap *is* that creature's advantage — closing it does not merely help you
    attack, it takes away the way the target was going to fight at all.

    Read off the target's live reach, so a card nobody has heard of is judged
    correctly and a unit whose range has been cut stops being worth pouncing on
    without anything being re-labelled.
    """
    total = own_reach + target_reach
    if total <= 0:
        return DASH_ON_EQUAL_REACH

    # Half at parity, toward one as the target out-reaches us; rescaled so
    # parity sits at the floor and anything shorter than us cannot go below it.
    denial = clamp_score((target_reach / total - 0.5) * 2)

    return DASH_ON_EQUAL_REACH + (DASH_ON_LONGER_REACH - DASH_ON_EQUAL_REACH) * max(0.0, denial)


def _area_suitability(observation: Observation) -> float:
    """How well an ability centred on the caster would land, by what it covers.

    An area effect aimed at one straggler is a wasted gauge and aimed at four is
    the reason the card exists, so the count of enemies inside its radius is the
    judgement — the same shape as the minimum-targets rule a DM would apply by
    eye. The radius comes from the effect itself; an ability with no area lands
    on whatever the caster is already able to reach.
    """
    ability = observation.ability
    if ability is None:
        return 0.0

    radii = [effect.radius for effect in ability.effects if isinstance(effect, AreaDamage)]
    radius = max(radii) if radii else observation.capabilities.reach

    covered = sum(
        1.0 for enemy in observation.enemies if distance(observation.unit.position, enemy.position) <= radius
    )

    return clamp_score(min(1.0, covered / AREA_WORTH_IT) * ABILITY_PREMIUM)
