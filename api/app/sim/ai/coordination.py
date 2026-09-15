"""The troop coordinator: who is asked to answer which threat.

**What it is for.** A troop whose mage is protective should visibly defend its
own, and "every unit independently decides it cares about allies" does not
produce that. It produces four units converging on one archer while a second
archer kills the mage unopposed, because nothing in a per-unit decision knows
what the other three units decided. Somebody has to allocate.

**What it is emphatically not.** It is not a strategist, it does not plan, and
it does not decide anything a unit could decide for itself. Its whole output is
an `Assignment`: this unit, that enemy, on behalf of this ally. A unit reads it
as one more thing to weigh — the `assigned` context — and may score the
assignment below something else and do that instead. The coordinator is a
suggestion with a budget, which is what keeps per-creature decisions the thing
actually driving the battle.

Three lines it does not cross, each of them an acceptance criterion:

* **It never writes a destination.** Stations belong to JQ-287's orders phase
  and, through the plan, to the player. A troop the player told to hold the west
  lane defends itself *there*.
* **It never overrides a capability.** Eligibility is read off live stats, so an
  immobile emplacement is never asked to intercept anything it cannot already
  reach, and an archer asked to answer a threat answers it by shooting.
* **It never commits the whole troop.** At most half the living members may be
  committed at once, whatever the personalities say. A troop that could be
  emptied by one enemy walking at it would be a decoy button, not a defence.

**Commitment, and why it is state.** Recomputing from scratch every tick makes a
defender that is one unit further away than a newcomer get swapped out mid-run,
repeatedly, and nobody ever arrives. So an assignment survives across ticks and
is only re-judged once its troop's commitment window has passed. That is the
"decision commitment" a methodical mage values, and it is *state* — visible on
`Troop`, carried in the snapshot, replayable — rather than a smoothing constant
hidden inside a predicate.

Release is the other half and is immediate, because live-state reaction is worth
more than commitment when the premise is gone: an assignment ends the moment the
defender dies, the target dies, the ally being defended dies, the target stops
threatening that ally, or the target moves out of the defender's reach. No
window protects any of those.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.sim.ai.intent import Assignment, TroopCoordination
from app.sim.ai.profiles import MAX_INFLUENCE, ResolvedPersonality
from app.sim.ai.situation import threatens
from app.sim.geometry import distance
from app.sim.types import UnitId
from app.sim.world import Troop, Unit, World

#: A troop with no personalities coordinates like this. Chosen to be modest: a
#: troop that ships no behavior data should look like one that is minding its
#: own business, and a personality is how a mage says otherwise.
BASE_GUARD_RADIUS = 40.0
BASE_LEASH = 70.0
BASE_COMMITMENT_SECONDS = 1.5
BASE_DEFENDERS = 1.0

#: Ceilings. The radius ones share `MAX_INFLUENCE` with contextual rules, for
#: the same reason: past half the map's width, "local" has stopped being true.
MAX_GUARD_RADIUS = MAX_INFLUENCE
MAX_LEASH = MAX_INFLUENCE
MAX_COMMITMENT_SECONDS = 6.0
MAX_DEFENDERS = 3

#: The share of a troop's living units that may be committed at once. Hard, and
#: above every personality: "leadership cannot commandeer the entire troop for a
#: decoy" is a rule about what leadership *is*, not a tuning value.
MAX_COMMITTED_FRACTION = 0.5


@dataclass(frozen=True)
class CoordinationProfile:
    """A troop's composed coordination habits. Bounded, and derived from data."""

    #: How far beyond its own reach an enemy is noticed as a threat to an ally.
    guard_radius: float
    #: How far past its own reach a defender will travel to answer one.
    leash: float
    #: How long an assignment is honoured before it is re-judged, in ticks.
    commitment_ticks: int
    #: How many units may be committed at once, before the fraction cap.
    defenders: int


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def compose_profile(
    personalities: tuple[ResolvedPersonality, ...],
    seconds_per_tick: float,
) -> CoordinationProfile:
    """Baseline plus every tag's shift, summed in tag order and clamped.

    Summation rather than precedence, exactly as the weights compose: two mages
    who both widen the guard radius widen it further, and neither of them wins
    on the strength of being declared first. The shifts arrive already scaled by
    strength, so a tag at zero moves nothing here either.
    """
    guard_radius = BASE_GUARD_RADIUS
    leash = BASE_LEASH
    commitment_seconds = BASE_COMMITMENT_SECONDS
    defenders = BASE_DEFENDERS

    # `personalities` is sorted by tag, so this addition happens in a fixed
    # order — floating-point addition is not associative and the determinism
    # tests would find it if it were not.
    for personality in personalities:
        shift = personality.coordination
        guard_radius += shift.guard_radius
        leash += shift.leash
        commitment_seconds += shift.commitment_seconds
        defenders += shift.defenders

    return CoordinationProfile(
        guard_radius=_clamp(guard_radius, 0.0, MAX_GUARD_RADIUS),
        leash=_clamp(leash, 0.0, MAX_LEASH),
        commitment_ticks=_ticks(_clamp(commitment_seconds, 0.0, MAX_COMMITMENT_SECONDS), seconds_per_tick),
        defenders=int(_clamp(defenders, 0.0, float(MAX_DEFENDERS))),
    )


def _ticks(seconds: float, seconds_per_tick: float) -> int:
    """Seconds, in ticks. Authored in seconds so a tick-rate change cannot
    silently retune every troop's willingness to stick to a decision."""
    if seconds_per_tick <= 0:
        return 0
    return round(seconds / seconds_per_tick)


def baseline_profile(seconds_per_tick: float) -> CoordinationProfile:
    """What a troop with nothing authored on it coordinates like.

    A function rather than a constant because the commitment window is authored
    in seconds and lives here in ticks, so it cannot be known until the tick
    rate is. Pinning it as a constant would quietly bake one tick rate into the
    baseline and leave every troop that shipped no personality disagreeing with
    every troop that shipped one about how long a second is.
    """
    return compose_profile((), seconds_per_tick)


def profile_for(troop: Troop, world: World, seconds_per_tick: float) -> CoordinationProfile:
    """The coordination habits of this troop's living mages.

    Read off a living mage's composed behavior rather than recomposed from the
    library, so that coordination and weights always agree about what the troop
    believes. Both were settled at battle start; a mage that dies does not
    retune the summons it left behind, here or anywhere else.

    A troop with no living mage has none. That is JQ-289's dissolve arriving
    exactly where it should: the thing a mage was providing stops when the mage
    does, and the summons still standing fall back on their own instincts rather
    than on a leader who is no longer there.
    """
    mage = leading_mage(world, troop)
    if mage is None or mage.ai is None:
        return baseline_profile(seconds_per_tick)
    return compose_profile(mage.ai.behavior.personalities, seconds_per_tick)


def leading_mage(world: World, troop: Troop) -> Unit | None:
    """The living mage this troop's habits are read from, or None.

    Lowest id among the living, and it must have behavior attached — which is
    also how "a battle that ships no behavior library coordinates nothing" stays
    true. Without that second condition the coordinator would happily allocate
    defenders in a battle where no unit has an opinion to act on them with, and
    the allocations would show up in the snapshot: a visible change to a battle
    that was supposed to run exactly as it did before this existed.

    Which mage, among several, is not arbitrary but is also not interesting:
    every member of a troop resolves the same personality set, so they all
    compose the same habits. Taking the lowest id makes the choice stable rather
    than dependent on list order.
    """
    for mage_id in sorted(troop.mage_ids):
        mage = _find(world, mage_id)
        if mage is not None and mage.hp > 0 and mage.ai is not None:
            return mage
    return None


@dataclass(frozen=True)
class Need:
    """One enemy that is hurting one of ours, and wants answering."""

    target_id: UnitId
    protecting_id: UnitId


def coordinate(world: World, troop: Troop, tick: int, seconds_per_tick: float) -> None:
    """Rebuilds one troop's assignments from live state. Mutates the troop.

    Runs before any unit in the troop decides, so every member reads the same
    assignments against the same field.
    """
    members = _living_members(world, troop)
    if not members or leading_mage(world, troop) is None:
        # Dissolved, wiped out, or a battle that ships no behavior data at all.
        troop.coordination = TroopCoordination()
        return

    profile = profile_for(troop, world, seconds_per_tick)
    needs = _needs(world, troop, members, profile)
    by_target = {need.target_id: need for need in needs}

    kept: list[Assignment] = []
    committed: set[UnitId] = set()
    answered: set[UnitId] = set()

    budget = min(profile.defenders, math.floor(len(members) * MAX_COMMITTED_FRACTION))

    for assignment in troop.coordination.assignments:
        if len(kept) >= budget:
            break
        need = by_target.get(assignment.target_id)
        if need is None or need.protecting_id != assignment.protecting_id:
            continue
        if tick - assignment.since_tick >= profile.commitment_ticks:
            # The window has passed: back into the pool, to be re-judged below
            # against whoever is best placed now. It may well win it again.
            continue
        defender = _member(members, assignment.unit_id)
        if defender is None or not _eligible(defender, world, need, profile):
            continue
        kept.append(assignment)
        committed.add(assignment.unit_id)
        answered.add(assignment.target_id)

    fresh: list[Assignment] = []
    for need in needs:
        if len(kept) + len(fresh) >= budget:
            break
        if need.target_id in answered:
            # One defender suffices. A second would be two units doing one
            # unit's job while a second threat went unanswered.
            continue
        defender = _best_defender(members, world, need, profile, committed)
        if defender is None:
            continue
        fresh.append(
            Assignment(
                unit_id=defender.id,
                target_id=need.target_id,
                protecting_id=need.protecting_id,
                since_tick=tick,
            )
        )
        committed.add(defender.id)
        answered.add(need.target_id)

    troop.coordination = TroopCoordination(assignments=tuple(sorted(kept + fresh, key=lambda a: a.unit_id)))


def assignment_for(troop: Troop, unit_id: UnitId) -> Assignment | None:
    return next((a for a in troop.coordination.assignments if a.unit_id == unit_id), None)


def nominated_target_ids(troop: Troop) -> tuple[UnitId, ...]:
    """Every enemy this troop's assignments name, sorted and deduplicated.

    The handoff to JQ-329's candidate generation: a nominated enemy is one some
    unit has been asked to answer, so it gets the full positional treatment
    rather than only being reachable when it happens to be the nearest thing.
    """
    return tuple(sorted({assignment.target_id for assignment in troop.coordination.assignments}))


def _find(world: World, unit_id: UnitId) -> Unit | None:
    return next((unit for unit in world.units if unit.id == unit_id), None)


def _member(members: tuple[Unit, ...], unit_id: UnitId) -> Unit | None:
    return next((unit for unit in members if unit.id == unit_id), None)


def _living_members(world: World, troop: Troop) -> tuple[Unit, ...]:
    """Sorted by id. Built by filtering `world.units`, never by walking a set."""
    return tuple(sorted((u for u in world.units if u.troop_id == troop.id and u.hp > 0), key=lambda u: u.id))


def _needs(
    world: World,
    troop: Troop,
    members: tuple[Unit, ...],
    profile: CoordinationProfile,
) -> tuple[Need, ...]:
    """Every enemy hurting one of ours, worst first, at most one need each.

    One need per enemy rather than one per victim: the answer to an enemy
    standing between two of ours is a defender, and it is the same defender
    either way. Which ally it is recorded against decides only when the
    assignment is released, so it is the one most in need of the help.
    """
    enemies = sorted(
        (u for u in world.units if u.hp > 0 and u.side != troop.side and u.damage > 0),
        key=lambda u: u.id,
    )

    needs: list[Need] = []
    for enemy in enemies:
        victims = [ally for ally in members if _under_threat(enemy, ally, profile)]
        if not victims:
            continue
        needs.append(Need(target_id=enemy.id, protecting_id=min(victims, key=_neediness).id))

    return tuple(sorted(needs, key=lambda need: _priority(need, members)))


def _under_threat(enemy: Unit, ally: Unit, profile: CoordinationProfile) -> bool:
    """Within reach of this ally, or close enough to be about to be.

    `guard_radius` is a margin on the enemy's own reach rather than an absolute
    distance, which is what makes one number work for a melee hound and a
    long-ranged adept: a troop that guards closely still notices the thing that
    is one step from contact, whatever that thing's step happens to be.
    """
    if enemy.damage <= 0:
        return False
    return distance(enemy.position, ally.position) <= enemy.range + profile.guard_radius


def _neediness(unit: Unit) -> tuple[int, float, str]:
    """Mages first, then the most hurt. A total order, so no tie is left open."""
    max_hp = unit.max_hp if unit.max_hp > 0 else 1.0
    return (0 if unit.kind == "mage" else 1, unit.hp / max_hp, unit.id)


def _priority(need: Need, members: tuple[Unit, ...]) -> tuple[int, float, str, str]:
    protected = _member(members, need.protecting_id)
    rank = _neediness(protected) if protected is not None else (2, 1.0, need.protecting_id)
    return (rank[0], rank[1], need.target_id, need.protecting_id)


def _reachable(defender: Unit, target: Unit, profile: CoordinationProfile) -> bool:
    """Whether this unit could do anything about that enemy if it tried.

    An immobile unit is judged on its reach alone, with no leash at all. That is
    the capability rule at its sharpest: a coordinator that handed an emplacement
    a leash would be asking a wall to walk, and the wall would carry an
    assignment it could never act on while a mobile summon went unasked.
    """
    gap = distance(defender.position, target.position)
    if defender.speed <= 0:
        return gap <= defender.range
    return gap <= defender.range + profile.leash


def _eligible(defender: Unit, world: World, need: Need, profile: CoordinationProfile) -> bool:
    """Alive, armed, in range of the job, and not the one being defended."""
    if defender.hp <= 0 or defender.damage <= 0 or defender.id == need.protecting_id:
        return False

    target = _find(world, need.target_id)
    protected = _find(world, need.protecting_id)
    if target is None or target.hp <= 0 or protected is None or protected.hp <= 0:
        return False
    if not threatens(target, protected) and not _under_threat(target, protected, profile):
        return False

    return _reachable(defender, target, profile)


def _best_defender(
    members: tuple[Unit, ...],
    world: World,
    need: Need,
    profile: CoordinationProfile,
    committed: set[UnitId],
) -> Unit | None:
    """The nearest eligible unit that is not already busy; ties go to the lower id.

    Nearest rather than best-suited on purpose. "Best-suited" would need a model
    of matchups that the scoring loop already has and does better, and the unit
    gets to apply it: the assignment says *that one is the problem*, and what to
    do about it is still scored against everything else the unit could do.
    """
    target = _find(world, need.target_id)
    if target is None:
        return None

    eligible = [
        unit for unit in members if unit.id not in committed and _eligible(unit, world, need, profile)
    ]
    if not eligible:
        return None

    return min(eligible, key=lambda unit: (distance(unit.position, target.position), unit.id))
