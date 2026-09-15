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
from app.sim.ai.intent import MOVING_ACTIONS, movement_scale
from app.sim.ai.observe import Observation
from app.sim.ai.threat import threats_against
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
#: The scale over which a unit stops counting as being at its post, in map
#: units. Not a radius with an edge: `_beyond_post` softens the distance smoothly
#: over roughly this range, so a unit near its station is pulled back weakly and
#: has room to screen, to keep its firing distance, or to step into a fight
#: without the order itself outbidding every one of those.
#:
#: Provisional, like every number here. Roughly a formation slot: wide enough for
#: a screening step and far short of a lane, and well inside `PURSUIT_LEASH` so
#: that the two bounds do not fight — a diversion becomes costly long before it
#: becomes illegal.
STATION_TOLERANCE = 24.0
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


def _dash_of(observation: Observation) -> DashToTarget | None:
    ability = observation.ability
    if ability is None:
        return None
    return next((e for e in ability.effects if isinstance(e, DashToTarget)), None)


def _step_for(observation: Observation, candidate: Candidate) -> float:
    """How far this candidate actually walks, which is not the same for all of them.

    `withdraw` covers half the ground `advance` does. Scoring has to use the same
    scale the movement phase will, or a unit weighs the danger at a position it
    is not going to reach this tick — and the whole point of `withdraw` being
    slower is that the slowness is a cost it pays in the scoring.
    """
    return observation.step * movement_scale(candidate.kind)


def _position_after(observation: Observation, candidate: Candidate) -> Vec2:
    """Where this candidate would leave the unit standing.

    Uses the same `move_toward` the movement phase uses, at the same per-kind
    speed, so the danger a unit weighs is the danger it actually walks into and
    not an approximation of it.

    A cast that dashes is projected the same way, mirroring `_resolve_dash` —
    which is the point of deriving behaviour from ability mechanics rather than
    from a label on the card. A unit weighing a pounce weighs where the pounce
    puts it, so the same danger and objective factors judge it without either
    knowing what a pounce is.
    """
    if candidate.kind in MOVING_ACTIONS and candidate.destination is not None:
        return move_toward(
            observation.unit.position, candidate.destination, _step_for(observation, candidate)
        )

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
    walks *away* from the station — closing on an enemy behind you, or giving
    ground — scores negative, which is how a unit with a heavy objective weight
    refuses a chase.

    **A post is a place, not a point.** Distance is measured to the edge of a
    tolerance around the station rather than to the station itself, so a unit
    already standing at its post can move about within that radius at no cost to
    this factor at all. Without it the factor saturates: one stride is the whole
    denominator, so *every* move away from a post scored a flat -1.0 — stepping
    aside to screen an ally and abandoning a two-hundred-unit march were priced
    identically, at the maximum, and nothing else on the board could outbid it.

    That was measured from both ends. JQ-330 found a melee guard walking straight
    past a mortar shooting its own mage, because interposing scored -1.0 on this
    and reaching its post scored +1.0, at every personality strength that exists;
    their fixture is pinned as "an interception cannot yet outrank the troop's
    own post". From this side, every `withdraw` and `retreat` ate the same flat
    -1.0 and could only ever win when a unit was seconds from death. Both are the
    one bug, and it is here rather than in either set of weights.

    The pull to *march* is untouched: a unit well outside its tolerance still
    closes a full stride and still scores a full 1.0, so a troop crossing the map
    behaves exactly as it did.

    Measured against the full stride rather than the candidate's own, so that
    withdrawing at half speed reads as losing half as much ground rather than as
    losing a full stride's worth at half pace. The denominator has to be one
    fixed length or the factor is not comparable between candidates, which is the
    whole basis for adding it to the others.
    """
    if candidate.kind not in MOVING_ACTIONS or observation.step <= 0:
        return 0.0

    station = observation.objective.station
    before = _beyond_post(distance(observation.unit.position, station))
    after = _beyond_post(distance(position, station))
    return clamp_score((before - after) / observation.step)


def _beyond_post(gap: float) -> float:
    """How far from its post a unit effectively is, softened near the post itself.

    `gap**2 / (gap + tolerance)`: zero at the station, about half the distance at
    one tolerance out, and indistinguishable from `gap - tolerance` far away. So
    a unit near its post is pulled back weakly and a unit crossing the map is
    pulled back at full strength, which is what the factor is for.

    **The obvious form of this — `max(0, gap - tolerance)` — oscillates, and it
    is worth saying why, because it looks completely safe.** Its *value* is
    continuous; its slope is not. Inside the tolerance a step away from the post
    costs nothing, and one step outside it costs a full stride. So a unit walks
    out to the edge (free), finds the next step expensive and walks back in
    (free), finds the step out free again, and alternates between two positions
    one map unit apart for the rest of the battle — measured, on an iron-bulwark
    holding a post: 23.0, 24.0, 23.0, 24.0, for a hundred and seventy ticks,
    committing to a chase and abandoning it on every one of them.

    A decision margin does not fix that, and trying one first is what showed why:
    the two candidates either side of the boundary differ by far more than any
    sane hysteresis, because the *cliff* is what they differ by. `CONVENTIONS.md`
    says a boundary must be an interval rather than a point, and for a gradient
    that means no kink at all rather than a small one.
    """
    if gap <= 0:
        return 0.0
    return gap * gap / (gap + STATION_TOLERANCE)


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
    if target is None or candidate.kind in ("hold", "retreat"):
        # `retreat` declines its target outright — see `phases/targeting.py` —
        # so there is no fight to judge, the same as standing still. It earns
        # its place on danger alone, which is the honest account of what it is
        # for: a unit that retreats has given up on accomplishing anything this
        # tick except surviving it.
        return 0.0

    unit = observation.unit
    max_hp = target.max_hp if target.max_hp > 0 else 1.0

    kills_now = 1.0 if unit.damage >= target.hp else 0.0
    wounded = clamp_score(1.0 - target.hp / max_hp)
    threat = target.damage / (target.damage + unit.damage) if (target.damage + unit.damage) > 0 else 0.0

    suitability = ENGAGEABLE + 0.30 * kills_now + 0.10 * wounded + 0.10 * threat

    if candidate.kind == "cast":
        return clamp_score(suitability * _ability_multiplier(observation, candidate))

    # `withdraw` is scored like a swing rather than like a move, because it is
    # one: backing off at half speed while still shooting is the kiting a unit
    # with reach is *for*. Discounting it as a move would mean a ranged creature
    # could only ever choose between standing in contact and running away, which
    # is the pair of options that made the danger factor useless in the first
    # place.
    if candidate.kind in ("attack", "withdraw"):
        return clamp_score(suitability)

    # Walking toward a target serves the same end as swinging at it, just less
    # directly — so it scores the same way, discounted. Without this an
    # aggressive creature could never choose to close on anything: closing is an
    # advance, advances scored nothing here, and the only factor that credits a
    # move is progress toward the station. "Aggressive" would have meant nothing
    # more than "swings at whatever happens to walk into reach".
    return clamp_score(APPROACH_DISCOUNT * suitability)


def _exposure(observation: Observation, before: Vec2, after: Vec2) -> float:
    """Incoming damage at the position this candidate leaves us in, versus HP.

    Delegates the per-enemy judgement to `threat.py`, which is where the two
    gradients live: how *deep* inside an enemy's reach a position sits, and — new
    in this ticket — how soon an enemy that is not in reach yet would be. The
    second is what makes this factor mean anything at all. JQ-328 counted only
    enemies already able to swing, so a unit forty map units from something
    walking at it scored `danger = 0.00` on every candidate and a wary profile
    weighed the board exactly as a reckless one did.

    Scaled by *current* HP rather than max, so the same spot reads as more
    dangerous to something already hurt. That is the durability term.

    **What this factor can now do, that the version in JQ-328 could not.** It can
    produce a disengagement. `withdraw` and `retreat` exist as candidates, and
    because a move away from a slower enemy lowers that enemy's contribution to
    nothing, backing off *scores* rather than merely being available. Whether it
    is viable falls out of the speed differential and nothing else: an ember
    sprite opens the gap on an ash-ram and cannot on a cinder-hound, so it kites
    one and stands and fights the other without either being labelled.

    **And it still does not keep units apart.** Danger makes closing
    unattractive; a unit whose objective weight outvotes it walks all the way on.
    See "Movement does not guarantee separation" in `CONVENTIONS.md`, and JQ-380
    for the decision — that is a consequence of the press-past capability rather
    than a defect in this rule.
    """
    incoming = sum(
        threat.incoming
        for threat in threats_against(observation.enemies, before, after, observation.seconds_per_tick)
    )

    if incoming <= 0:
        return 0.0

    hp = observation.unit.hp if observation.unit.hp > 0 else 1.0
    return -min(1.0, incoming / hp)


def _danger(observation: Observation, candidate: Candidate, position: Vec2) -> float:
    """Exposure over the whole tick, both ends of it.

    One call, because `threat.py` now prices each enemy against the pair of
    positions rather than against one of them. The old shape here was
    `min(standing, arriving)` — the worse of the two ends — which was the right
    answer for enemies already in contact and the wrong one for everybody else.
    Since standing still is never *less* exposed than leaving, that minimum was
    always the standing figure, and every way of giving ground scored exactly
    what holding scored. The rule now lives per-enemy, where the distinction
    between "already swinging at me" and "still on its way" can actually be made.

    What it preserves is the reason the old rule existed. Scoring a move at its
    destination alone made walking away from a fight strictly safer than standing
    in it, and two armies duly strolled through each other and out the far side:
    every unit disengaged the moment it was hit, nobody could re-engage, and a
    battle that ended in annihilation in eighteen seconds without a decision loop
    ran the full ninety with one. A unit in contact still cannot shed that
    contact by walking, so breaking off still costs.
    """
    return _exposure(observation, observation.unit.position, position)


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
