"""Step two: every legal action, and nothing illegal.

Six verbs now — advance, attack, cast, withdraw, retreat, hold — where JQ-328
shipped four. The two new ones are the ways of giving ground, and they are two
rather than one parameterised action because they execute differently:
**withdraw** backs off at half speed and keeps shooting, **retreat** leaves at
full speed and shoots at nothing. A single action with a flag would have to be
half-executed by the movement phase and half by target acquisition anyway, and
naming them separately is what lets a profile prefer one over the other.

**The candidate set is bounded and deterministic, not searched.** Every unit gets
at most a handful of positions per tick: its station, a standoff against each
enemy worth answering, a screen in front of what that enemy threatens, a
withdrawal to useful firing distance, and one line of retreat. No grid, no
sampling, no nearest-neighbour sweep — the ticket asks for a small deterministic
candidate set rather than an unbounded search, and the reason is not performance.
It is that a bounded set can be enumerated in a test and an unbounded one cannot.

**Legality is decided here, before anything is scored.** A rooted summon gets no
movement candidates at all rather than losing them on points; a unit with no
damage gets no attack candidates; a troop not ordered to push the enemy base
never sees the base as somewhere to go; a unit in chase recovery gets no pursuit.
Filtering first is what keeps the weights honest — a preference can only choose
among things that were possible, so no trait can talk a unit into something it
cannot do, and no personality can talk one into a chase its bounds forbid.

**Ordering is stable.** Candidates come out sorted by a key that does not depend
on list positions or on hash order, because that ordering is also the tie-break:
two actions that score identically must resolve the same way in every replay, and
`world.units` reorders itself as units are removed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.intent import (
    ACTION_KINDS,
    ENGAGING,
    HOLDING_STATION,
    INTERCEPTING,
    MAINTAINING_RANGE,
    PRESSING_OBJECTIVE,
    PURSUING,
    PURSUIT_STARTED,
    RETREATING,
    RETURNED_TO_STATION,
    SCREENING,
    SCREENING_INFERRED,
    ActionKind,
)
from app.sim.ai.objective import enemy_base_position
from app.sim.ai.observe import Observation
from app.sim.ai.positioning import (
    GIVE_GROUND_LOOKAHEAD,
    give_ground_position,
    outranges,
    protected_by,
    screen_position,
    standoff_position,
    useful_range,
)
from app.sim.ai.pursuit import can_engage, eligible_targets
from app.sim.ai.threat import pressing, pressure, threats_against
from app.sim.effects import ORIGIN_SELF
from app.sim.geometry import distance
from app.sim.types import UnitId, Vec2
from app.sim.world import Unit

#: How close the station has to be before advancing on it is pointless.
ARRIVAL_EPSILON = 1e-9

#: How much incoming damage, as a fraction of a unit's remaining hit points,
#: makes disengaging worth considering at all. See `_retreat_candidates`.
#: Provisional: a quarter of what is left, which a fresh creature shrugs off and
#: a hurt one cannot.
RETREAT_PRESSURE = 0.25

#: How close to reaching us an enemy has to be before backing off while still
#: shooting is worth doing, in seconds of its own approach. See
#: `_withdraw_candidates`. Provisional.
WITHDRAW_LEAD_SECONDS = 1.0


@dataclass(frozen=True)
class Candidate:
    """One thing a unit could do this tick."""

    kind: ActionKind
    #: On `attack` and `cast`, who to hit. On `advance`, who this move is
    #: closing on — an advance on the troop's station has none, and neither does
    #: a cast that lands on the caster. On `withdraw`, who is being backed away
    #: from. Scoring reads it either way: a unit that wants a fight has to be
    #: able to score walking toward one, or "aggressive" can only ever mean
    #: "swing at whatever wandered into reach".
    target_id: UnitId | None = None
    #: Set on `cast`. Which ability this spends.
    ability_id: str | None = None
    #: Set on the moving kinds and on `hold`. Handed to movement as
    #: `unit.destination`.
    destination: Vec2 | None = None
    #: One of `intent.REASONS`. Carried onto the winning intent for diagnostics;
    #: deliberately **not** part of the sort key, so that naming a candidate
    #: differently can never change which one wins.
    reason: str = ""
    #: On a screen, the ally being covered — None when it is this unit's post.
    #: Diagnostics, like `reason`, and out of the sort key for the same reason.
    protecting_id: UnitId | None = None


def _sort_key(candidate: Candidate) -> tuple[int, str, str, float, float]:
    destination = candidate.destination
    return (
        ACTION_KINDS.index(candidate.kind),
        candidate.target_id or "",
        candidate.ability_id or "",
        destination.x if destination else 0.0,
        destination.y if destination else 0.0,
    )


def _base_is_off_limits(observation: Observation, destination: Vec2) -> bool:
    """JQ-287's restriction: only a troop pushing the base may head for it.

    The predicate is theirs and the base's *health* is theirs; all this does is
    decline to offer the base as somewhere to walk. A unit under any other order
    never gets the candidate, so it cannot be scored into taking it.
    """
    if observation.objective.may_attack_base:
        return False
    base = enemy_base_position(observation.map_config, observation.unit)
    return destination == base


def _nearest_enemy(observation: Observation) -> Unit | None:
    if not observation.enemies:
        return None
    return min(
        observation.enemies,
        key=lambda enemy: (distance(observation.unit.position, enemy.position), enemy.id),
    )


def _answerable(observation: Observation) -> tuple[Unit, ...]:
    """The enemies this unit generates positions against, sorted by id.

    Three sources, unioned and deduplicated: whoever the troop coordinator
    nominated (JQ-330's seam), whatever this unit is already chasing, and the
    nearest enemy. The nearest is always in the set so that a unit with no
    coordinator and no commitment behaves as it did before this ticket; the
    other two are what make an assignment and a chase expressible at all.

    Every one of them is then filtered through `eligible_targets`, so a chase
    this unit's bounds forbid never becomes a candidate — including one the
    coordinator asked for. Coordination decides *who is worth answering*;
    eligibility decides *what this unit may legally do about it*, and the second
    is not overridable by the first.
    """
    eligible = set(eligible_targets(observation))

    wanted: set[UnitId] = set(observation.nominated_target_ids)
    if observation.commitment is not None:
        wanted.add(observation.commitment.target_id)
    nearest = _nearest_enemy(observation)
    if nearest is not None:
        wanted.add(nearest.id)

    # Walks `enemies`, which `observe` sorted by id, rather than iterating the
    # sets — which iterate in hash order, randomized per process.
    return tuple(enemy for enemy in observation.enemies if enemy.id in wanted and enemy.id in eligible)


def _closing_reason(observation: Observation, target: Unit) -> str:
    """What to call an advance on this enemy, for the record.

    Three different things wear the same verb, and a reader of a trace needs to
    tell them apart: answering an assignment, continuing a chase already
    committed to, and starting a new one. Something already in reach is none of
    them — that is just engaging what is in front of you.
    """
    if can_engage(observation.capabilities, distance(observation.unit.position, target.position)):
        return ENGAGING
    commitment = observation.commitment
    if commitment is not None and commitment.target_id == target.id:
        return PURSUING
    if target.id in observation.nominated_target_ids:
        return INTERCEPTING
    return PURSUIT_STARTED


def _station_candidates(observation: Observation) -> list[Candidate]:
    """Walking back to the post the orders phase assigned this tick.

    Named `returned_to_station` while the unit is in chase recovery and
    `pressing_objective` otherwise. Same action, same destination — the reason is
    the only difference, and it is the difference between "resuming its task" and
    "getting on with its task", which is worth being able to read.
    """
    station = observation.objective.station
    if distance(observation.unit.position, station) <= ARRIVAL_EPSILON:
        return []
    if _base_is_off_limits(observation, station):
        return []

    reason = RETURNED_TO_STATION if observation.recovery_remaining > 0 else PRESSING_OBJECTIVE
    return [Candidate(kind="advance", destination=station, reason=reason)]


def _approach_candidates(observation: Observation, target: Unit) -> list[Candidate]:
    """Closing on one enemy, and interposing in front of what it threatens.

    Both stand at this unit's own useful range from the target rather than on top
    of it, which is the "useful attack range" the ticket asks for and is also
    what stops a ranged unit walking into contact to use a weapon it could have
    fired from where it stood.

    The screen is only offered to something that can actually hold a line — a
    unit with no attack interposes its body and nothing else, which is a way of
    dying rather than a way of screening.

    **Neither is offered to a unit that can already fight the target**, and that
    guard is doing two jobs.

    The safety one: both positions sit exactly `gap` from the target, and
    `point_along` does not clamp, so asking for them from nearer than `gap` hands
    back a point *behind* the unit. An `advance` onto it walks backwards at full
    speed, silently, scoring as a retreat that nobody named and winning ties
    against the two verbs that are honest about it, since `advance` is declared
    first. Measured before the guard: a five-hit ember-sprite with an ash-ram
    closing preferred a "screen" forty map units to its rear. Refusing to offer
    either from inside weapon reach makes "the destination is nearer the target
    than the unit is" true by construction — reach is never below `gap`, which is
    nine tenths of it.

    The behavioural one: **a unit that can already fight from where it stands
    does not need to move to screen.** Standing and shooting *is* the screen, and
    `hold` covers it. An earlier version tested against `gap` rather than reach,
    which left a band a tenth of a reach wide where a unit could hit a target and
    was *still* offered a step toward it. JQ-330 measured the consequence on a
    merged branch: an archer sixty-three units from a mortar it could shoot at
    sixty-five preferred, by 0.0244, to walk four units closer and call it
    screening. It kept firing throughout — only `retreat` suppresses an attack,
    so nothing was given up — but it was fine-tuning its spacing rather than
    responding to anything, which is the same fussiness `_withdraw_candidates`
    already refuses on the other side of the weapon.

    So the three cases partition cleanly now. Nearer than useful range with
    something closing in: `withdraw`. Inside reach: `attack`. Outside reach:
    these.
    """
    gap = useful_range(observation.capabilities)
    position = observation.unit.position
    reason = _closing_reason(observation, target)

    if can_engage(observation.capabilities, distance(position, target.position)):
        return []

    candidates = []
    approach = standoff_position(position, target.position, gap)
    if not _base_is_off_limits(observation, approach):
        candidates.append(Candidate(kind="advance", target_id=target.id, destination=approach, reason=reason))

    if observation.capabilities.can_attack:
        covered = protected_by(observation.unit, observation.allies, target, observation.objective.station)
        screen = screen_position(target.position, covered.position, gap)
        if distance(position, screen) > ARRIVAL_EPSILON and not _base_is_off_limits(observation, screen):
            candidates.append(
                Candidate(
                    kind="advance",
                    target_id=target.id,
                    destination=screen,
                    reason=SCREENING if covered.assigned else SCREENING_INFERRED,
                    protecting_id=covered.unit_id,
                )
            )

    return candidates


def _closing_in(observation: Observation, enemy: Unit, gap: float) -> bool:
    """Whether `enemy` is within about a second of being able to swing at us.

    Read off the enemy's own reach and speed, so a quick hound triggers this from
    much further out than a slow ram does, and neither is labelled.
    """
    return gap <= enemy.range + enemy.speed * WITHDRAW_LEAD_SECONDS


def _withdraw_candidates(observation: Observation, answerable: tuple[Unit, ...]) -> list[Candidate]:
    """Backing off to useful firing distance, still shooting.

    Three conditions, and each one rules out a different way of getting this
    wrong.

    **It must outrange the enemy.** Against equal or longer reach, backing off
    slowly buys nothing and is spent being hit; `retreat`, which stops fighting
    altogether, is the honest alternative and this should not exist.

    **The enemy must be nearer than useful firing distance.** This is also what
    bounds the behaviour: the destination is a fixed point rather than a
    direction, so a unit arrives at its firing distance and the candidate stops
    being generated. There is no way for `withdraw` to express an endless
    retreat — the ticket's "without endless retreat", made structural instead of
    tuned.

    **And the enemy must actually be closing in.** Without this a long-armed
    creature fusses: `useful_range` is nine tenths of reach, so anything inside
    that triggers a withdrawal however harmless it is, and a unit with a reach of
    120 backs away from something a hundred units off that could never touch it.
    Measured — it broke a JQ-328 test outright, where two creatures differing
    only in reach were meant to show the long-armed one *engaging*. Range
    maintenance is a response to something arriving, not a preferred distance to
    hover at.
    """
    capabilities = observation.capabilities
    if not capabilities.can_move or not capabilities.can_attack:
        return []

    gap = useful_range(capabilities)
    position = observation.unit.position

    candidates = []
    for enemy in answerable:
        here = distance(position, enemy.position)
        if not outranges(capabilities, enemy) or here >= gap:
            continue
        if not _closing_in(observation, enemy, here):
            continue
        candidates.append(
            Candidate(
                kind="withdraw",
                target_id=enemy.id,
                destination=standoff_position(position, enemy.position, gap),
                reason=MAINTAINING_RANGE,
            )
        )

    return candidates


def _retreat_candidates(observation: Observation) -> list[Candidate]:
    """Leaving, at full speed, without swinging at anything on the way out.

    One candidate at most, along the single line away from everything that is
    currently a threat. There is no menu of escape routes: a unit either has an
    away or is surrounded, and offering it three slightly different aways would
    be an unbounded search wearing a small number.

    **Offered only under real pressure.** Retreating is disengagement — it
    suppresses attacking outright — so it is a survival action, and a unit at
    full health with something merely walking toward it is not in survival
    territory. Left ungated it is not: it costs nothing that `hold` does not also
    cost, and buys the whole closing half of the danger, so a healthy unit at its
    post backs away from anything that approaches. Measured that way across five
    seeds: retreat went from under one percent of decisions to twelve, and two of
    the five battles ran the full ninety seconds with neither base falling,
    because both armies spent them giving ground to each other.

    The gate is the unit's own incoming damage against its own remaining hit
    points, so it tightens as a creature is hurt without anything being labelled
    or any stance being set — a fresh ash-ram ignores what a bloodied ember-sprite
    runs from, and the same sprite at full health ignores it too.

    The bearing comes from the threats that actually weigh something, judged from
    where the unit is standing and not moving, so a unit does not back away from
    a corpse or from something that could never reach it.
    """
    capabilities = observation.capabilities
    if not capabilities.can_move:
        return []

    position = observation.unit.position
    threats = threats_against(observation.enemies, position, position, observation.seconds_per_tick)

    if pressure(threats, observation.unit.hp) < RETREAT_PRESSURE:
        return []

    destination = give_ground_position(
        position, tuple(threat.unit.position for threat in pressing(threats)), GIVE_GROUND_LOOKAHEAD
    )
    if destination is None or _base_is_off_limits(observation, destination):
        return []

    return [Candidate(kind="retreat", destination=destination, reason=RETREATING)]


def generate_candidates(observation: Observation) -> tuple[Candidate, ...]:
    """Every legal action for this unit this tick, in stable order.

    `hold` is always present, so the list is never empty and the loop always has
    a fallback — a unit with no legs, no damage and nowhere to be still decides
    something rather than falling through to undefined behavior.
    """
    unit = observation.unit
    capabilities = observation.capabilities
    answerable = _answerable(observation)

    candidates: list[Candidate] = [Candidate(kind="hold", destination=unit.position, reason=HOLDING_STATION)]

    if capabilities.can_move:
        candidates.extend(_station_candidates(observation))

        # Closing on an enemy is the other reason to move. Only offered to
        # something that could do anything once it arrived.
        if capabilities.can_attack:
            for target in answerable:
                candidates.extend(_approach_candidates(observation, target))

        candidates.extend(_withdraw_candidates(observation, answerable))
        candidates.extend(_retreat_candidates(observation))

    if capabilities.can_attack:
        for enemy in observation.enemies:
            if distance(unit.position, enemy.position) <= capabilities.reach:
                candidates.append(Candidate(kind="attack", target_id=enemy.id, reason=ENGAGING))

    candidates.extend(_cast_candidates(observation))

    # Deduplicated on the sort key: two enemies standing on one point would
    # otherwise produce the same advance twice, and an approach and a screen
    # coincide whenever the unit is already on the line it wants to hold.
    unique: dict[tuple[int, str, str, float, float], Candidate] = {}
    for candidate in candidates:
        unique.setdefault(_sort_key(candidate), candidate)

    return tuple(sorted(unique.values(), key=_sort_key))


def _cast_candidates(observation: Observation) -> list[Candidate]:
    """Spending a ready ability, once per target it could legally be aimed at.

    Legality only. Whether spending it *now* is a good idea — rather than
    holding it for a better moment — is a preference, and preferences are scored
    rather than filtered. That split is what lets a creature that values the
    objective and one that values a kill disagree about the same full gauge.

    A gauge that is not full produces nothing here at all, which is the same
    rule as a rooted unit getting no advance: the loop never scores the
    impossible.
    """
    ability = observation.ability
    if ability is None or observation.unit.energy < ability.energy_cost:
        return []

    if ability.origin == ORIGIN_SELF:
        # Lands on the caster, so there is exactly one way to spend it.
        return [Candidate(kind="cast", ability_id=ability.id, reason=ENGAGING)]

    reach = ability.range if ability.range is not None else observation.capabilities.reach

    return [
        Candidate(kind="cast", target_id=enemy.id, ability_id=ability.id, reason=ENGAGING)
        for enemy in observation.enemies
        if distance(observation.unit.position, enemy.position) <= reach
    ]
