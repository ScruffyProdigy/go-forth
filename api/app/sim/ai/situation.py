"""Reading a named situation off the field, for one candidate.

`vocabulary.py` declares what the situations *are* and why they exist. This is
the half that answers them: given a unit's view of the field and one thing it
could do, does this context hold?

Three properties every predicate here keeps, because contexts decide which
authored rules fire and a rule that fires unpredictably is worse than no rule:

* **Pure and per-candidate.** Nothing is cached between candidates and nothing
  is written anywhere. The same candidate against the same field always answers
  the same way.
* **Ordered inputs only.** Allies and enemies arrive from `observe` sorted by
  id, and every aggregate below walks them in that order. A mean over a set
  would be a different last bit in a fresh interpreter.
* **A distance, never a count of ticks.** A context is a fact about the field as
  it stands, so that a rule reading it reacts to live state rather than to
  something remembered. Commitment — the deliberate refusal to react — lives in
  the coordinator, where it is visible as state rather than hidden in a
  predicate.

`influence` comes from the rule being evaluated, so two tags may look different
distances at the same situation. That is the "influence range" dimension: a mage
that guards its troop closely and one that guards it across a lane are the same
tag at two radii, not two tags.
"""

from __future__ import annotations

from app.sim.ai.candidates import Candidate
from app.sim.ai.observe import Observation
from app.sim.ai.vocabulary import (
    CLOSING_ACTIONS,
    COMMITTING_ACTIONS,
    CONTEXTS,
    HOLDING_ACTIONS,
    Context,
)
from app.sim.geometry import distance
from app.sim.types import Vec2
from app.sim.world import Unit

#: At or below this share of its maximum, a target counts as vulnerable however
#: hard it hits. Provisional, and deliberately generous: "vulnerable" is meant
#: to describe an opening worth taking, not a corpse.
VULNERABLE_FRACTION = 0.5


def holds(
    context: Context,
    observation: Observation,
    candidate: Candidate,
    position: Vec2,
    influence: float,
) -> bool:
    """Whether `context` is true of this candidate. `position` is where it ends."""
    if context == "committing":
        return candidate.kind in COMMITTING_ACTIONS
    if context == "closing":
        return candidate.kind in CLOSING_ACTIONS and candidate.target_id is not None
    if context == "holding":
        return candidate.kind in HOLDING_ACTIONS
    if context == "ally-threatened":
        return _ally_threatened(observation, candidate, influence)
    if context == "assigned":
        return _assigned(observation, candidate)
    if context == "supported":
        return _support_count(observation, position, influence) > 0
    if context == "isolated":
        return _support_count(observation, position, influence) == 0
    if context == "leaves-allies":
        return _leaves_allies(observation, position, influence)
    if context == "vulnerable-target":
        return _vulnerable(observation, candidate)
    raise ValueError(f"{context!r} is not a context; expected one of {CONTEXTS}")


def troop_allies(observation: Observation) -> tuple[Unit, ...]:
    """Living allies in this unit's own troop, in the order `observe` sorted them.

    A troop is the unit of support in this game (design doc 4.2), so it is also
    the unit a coordination rule is allowed to talk about. An ally two troops
    away is not somebody this mage's personality has any say over, and counting
    it would let a protective mage quietly guard the whole army.
    """
    return tuple(ally for ally in observation.allies if ally.troop_id == observation.unit.troop_id)


def _enemy(observation: Observation, unit_id: str | None) -> Unit | None:
    if unit_id is None:
        return None
    return next((enemy for enemy in observation.enemies if enemy.id == unit_id), None)


def threatens(attacker: Unit, victim: Unit) -> bool:
    """Whether `attacker` can hurt `victim` where it currently stands.

    Read off live reach and live damage rather than off anything declared, so a
    disarmed or shortened-reach enemy stops being a threat the tick it happens
    and a card nobody has heard of is judged correctly.
    """
    return attacker.damage > 0 and distance(attacker.position, victim.position) <= attacker.range


def _ally_threatened(observation: Observation, candidate: Candidate, influence: float) -> bool:
    """Is this candidate aimed at something that is hurting one of ours, nearby?

    Deliberately says nothing about what to do. A melee guard reads this and
    closes; an archer reads the same thing and shoots from where it stands; a
    rooted emplacement reads it and can only keep swinging at whatever is
    already in front of it. One motivation, three executions, and the difference
    between them is capabilities rather than three authored variants of the
    same personality.
    """
    target = _enemy(observation, candidate.target_id)
    if target is None:
        return False

    return any(
        threatens(target, ally) and distance(observation.unit.position, ally.position) <= influence
        for ally in troop_allies(observation)
    )


def _assigned(observation: Observation, candidate: Candidate) -> bool:
    assignment = observation.assignment
    return assignment is not None and candidate.target_id == assignment.target_id


def _support_count(observation: Observation, position: Vec2, influence: float) -> int:
    return sum(1 for ally in troop_allies(observation) if distance(position, ally.position) <= influence)


def _leaves_allies(observation: Observation, position: Vec2, influence: float) -> bool:
    """Does this candidate walk away from the troop, past what it will tolerate?

    Both halves are needed. Being far from the troop is not in itself a reason
    to refuse a candidate — a skirmisher that opened the battle out on a flank
    would then be unable to do anything at all. It is *increasing* that distance,
    from a point already past the leash, that a protective mage objects to.
    """
    allies = troop_allies(observation)
    if not allies:
        return False

    centre = _centre(allies)
    after = distance(position, centre)

    return after > influence and after > distance(observation.unit.position, centre)


def _centre(allies: tuple[Unit, ...]) -> Vec2:
    """The troop's centre of mass, summed in the order `observe` sorted it."""
    return Vec2(
        sum(ally.position.x for ally in allies) / len(allies),
        sum(ally.position.y for ally in allies) / len(allies),
    )


def _vulnerable(observation: Observation, candidate: Candidate) -> bool:
    """Hurt, or finishable by this unit's swing. A temporary advantage."""
    target = _enemy(observation, candidate.target_id)
    if target is None:
        return False

    max_hp = target.max_hp if target.max_hp > 0 else 1.0
    return observation.unit.damage >= target.hp or target.hp / max_hp <= VULNERABLE_FRACTION
