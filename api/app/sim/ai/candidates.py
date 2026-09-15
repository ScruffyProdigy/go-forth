"""Step two: every legal action, and nothing illegal.

Three verbs — advance, attack, hold — which is what the ticket asks for and also
what the existing phases can execute. Anything richer (screening, bounded
pursuit) is JQ-329 and arrives as more candidates through this same door.

**Legality is decided here, before anything is scored.** A rooted summon does not
get an advance candidate it would then have to lose on points; a unit with no
damage gets no attack candidates; a troop not ordered to push the enemy base
never sees the base as somewhere to go. Filtering first is what keeps the
weights honest — a preference can only choose among things that were possible,
so no trait can talk a unit into something it cannot do.

**Ordering is stable.** Candidates come out sorted by a key that does not depend
on list positions or on hash order, because that ordering is also the tie-break:
two actions that score identically must resolve the same way in every replay,
and `world.units` reorders itself as units are removed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.intent import ACTION_KINDS, ActionKind
from app.sim.ai.objective import enemy_base_position
from app.sim.ai.observe import Observation
from app.sim.effects import ORIGIN_SELF
from app.sim.geometry import distance
from app.sim.types import UnitId, Vec2

#: How close the station has to be before advancing on it is pointless.
ARRIVAL_EPSILON = 1e-9


@dataclass(frozen=True)
class Candidate:
    """One thing a unit could do this tick."""

    kind: ActionKind
    #: On `attack` and `cast`, who to hit. On `advance`, who this move is
    #: closing on — an advance on the troop's station has none, and neither does
    #: a cast that lands on the caster. Scoring reads it either way: a unit that
    #: wants a fight has to be able to score walking toward one, or "aggressive"
    #: can only ever mean "swing at whatever wandered into reach".
    target_id: UnitId | None = None
    #: Set on `cast`. Which ability this spends.
    ability_id: str | None = None
    #: Set on `advance` and `hold`. Handed to movement as `unit.destination`.
    destination: Vec2 | None = None


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


def generate_candidates(observation: Observation) -> tuple[Candidate, ...]:
    """Every legal action for this unit this tick, in stable order.

    `hold` is always present, so the list is never empty and the loop always has
    a fallback — a unit with no legs, no damage and nowhere to be still decides
    something rather than falling through to undefined behavior.
    """
    unit = observation.unit
    capabilities = observation.capabilities
    candidates: list[Candidate] = [Candidate(kind="hold", destination=unit.position)]

    if capabilities.can_move:
        approaches: list[tuple[UnitId | None, Vec2]] = [(None, observation.objective.station)]

        # Closing on an enemy is the other reason to move. Only offered to
        # something that could do anything once it arrived.
        if capabilities.can_attack and observation.enemies:
            nearest = min(
                observation.enemies,
                key=lambda enemy: (distance(unit.position, enemy.position), enemy.id),
            )
            approaches.append((nearest.id, nearest.position))

        for target_id, destination in approaches:
            if distance(unit.position, destination) <= ARRIVAL_EPSILON:
                continue
            if _base_is_off_limits(observation, destination):
                continue
            candidates.append(Candidate(kind="advance", target_id=target_id, destination=destination))

    if capabilities.can_attack:
        for enemy in observation.enemies:
            if distance(unit.position, enemy.position) <= capabilities.reach:
                candidates.append(Candidate(kind="attack", target_id=enemy.id))

    candidates.extend(_cast_candidates(observation))

    # Deduplicated on the sort key: two enemies standing on one point would
    # otherwise produce the same advance twice.
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
        return [Candidate(kind="cast", ability_id=ability.id)]

    reach = ability.range if ability.range is not None else observation.capabilities.reach

    return [
        Candidate(kind="cast", target_id=enemy.id, ability_id=ability.id)
        for enemy in observation.enemies
        if distance(observation.unit.position, enemy.position) <= reach
    ]
