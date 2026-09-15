"""Flat, immutable records of what one unit decided, and a bounded recorder.

Everything here **flattens on the way in**. A record holds a copy of the values
it reports, never a reference to the `Decision`, the `Observation` or the `Unit`
they came from. That is not defensive habit: JQ-329 puts multi-tick pursuit
commitment on `UnitAi`, and JQ-330 puts coordinator assignments on `Troop`, both
of which are rewritten in place as the battle goes on. A recorder holding
references would show tick 40's commitment next to tick 12's decision and read
like the sim had rewritten history.

The recorder is **bounded** because the alternative is not a developer tool. An
opening-demo battle is 1800 ticks; at twenty units that is 36,000 records if
nothing says otherwise. `TraceConfig` says otherwise — a tick window, a set of
units, a cap — and whatever the cap turns away is counted rather than silently
lost, so a truncated report says it is truncated.

Nothing in this module reads the rng, writes to the world, or is read back by
anything that scores. It is downstream of every decision it describes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.ai.decide import Decision
from app.sim.ai.factors import FACTORS, FactorContribution, FactorName, PersonalityInfluence
from app.sim.ai.intent import ActionKind, Assignment
from app.sim.ai.observe import Observation
from app.sim.ai.profiles import PersonalityTag, ResolvedBehavior, TraitTag, defaulted
from app.sim.types import Side, TroopId, UnitId, Vec2

#: What a record keeps when the behavior layer has not said. JQ-330 is adding
#: per-source provenance to `ResolvedBehavior`; until it lands, "was this
#: strength the definition's default or an explicit override" has no answer in
#: the data, and reporting a guess as a fact would be worse than reporting
#: nothing. `_personalities_of` below is the single place that changes.
UNKNOWN = None


@dataclass(frozen=True)
class PersonalitySourceRecord:
    """One mage's reference to a tag, and where that reference's strength came from."""

    mage_id: UnitId
    strength: float
    overridden: bool


@dataclass(frozen=True)
class PersonalityRecord:
    """One personality tag's say in one unit's behavior."""

    tag: PersonalityTag
    #: The strength that actually applied, after composition.
    strength: float
    #: True when *any* reference supplied an explicit strength — JQ-330's
    #: `defaulted()`, inverted. Exact for a one-mage troop, which is every troop
    #: `create_world` builds; `sources` is the unabridged answer, since two mages
    #: can name one tag with only one of them overriding.
    #:
    #: One flag per tag, which is the honest shape only while a troop has one
    #: mage — as every troop in `create_world` does today. JQ-330's
    #: `ResolvedPersonality` carries a `sources` tuple, one entry per mage that
    #: named the tag, each with its own `overridden`; two mages in one troop can
    #: name the same tag with only one of them overriding. Collapsing that to a
    #: single flag would attribute one mage's choice to both. If multi-mage
    #: troops become a thing, this field grows a `sources` tuple beside it
    #: rather than trying to answer for all of them at once.
    overridden: bool | None = UNKNOWN
    #: One entry per mage that named this tag, sorted by mage id.
    sources: tuple[PersonalitySourceRecord, ...] = ()


@dataclass(frozen=True)
class CandidateRecord:
    """One scored action, and the factors that got it that score."""

    kind: ActionKind
    target_id: UnitId | None
    ability_id: str | None
    destination: Vec2 | None
    score: float
    contributions: tuple[FactorContribution, ...]
    #: Which authored tags spoke to *this* candidate, and in which situation
    #: (JQ-330). Per candidate rather than per unit because that is the whole
    #: point of a contextual rule: the same tag is loud on one candidate and
    #: silent on the next. Empty when no tag had anything to say.
    influences: tuple[PersonalityInfluence, ...] = ()


@dataclass(frozen=True)
class TraceRecord:
    """One unit's decision on one tick, flat enough to print or diff."""

    tick: int
    unit_id: UnitId
    troop_id: TroopId
    side: Side
    type_id: str
    #: Where JQ-287's orders phase had this unit posted when it decided.
    station: Vec2
    #: Whether its troop's order permitted the enemy base as an objective.
    may_attack_base: bool
    traits: tuple[TraitTag, ...]
    personalities: tuple[PersonalityRecord, ...]
    #: The composed weights, in declared factor order — never dict order.
    weights: tuple[tuple[FactorName, float], ...]
    chosen: CandidateRecord
    #: The best of the losing candidates, strongest first. Bounded by
    #: `TraceConfig.rivals`; `candidate_count` says how many there really were.
    rivals: tuple[CandidateRecord, ...]
    candidate_count: int
    #: Why the unit says it chose this — JQ-329 owns the vocabulary and writes
    #: it onto `Intent`. Empty until that lands, and never branched on here.
    reason: str = ""
    #: What this unit's troop asked it to answer, if anything (JQ-330). Flattened
    #: at record time: `Troop.coordination` is rebuilt every tick, so a reference
    #: would show the current allocation beside an old decision.
    assignment: Assignment | None = None


@dataclass(frozen=True)
class TraceConfig:
    """What to keep. The defaults keep everything, up to the cap."""

    #: Only these units, or every unit when None. A frozenset because this is a
    #: membership test and nothing iterates it — set order is not reproducible
    #: across processes, and this module's output has to be.
    unit_ids: frozenset[UnitId] | None = None
    first_tick: int = 0
    #: Inclusive. None means "to the end of the battle".
    last_tick: int | None = None
    #: The hard cap. Twenty units across a hundred ticks, which is a long enough
    #: look at a 90-second battle to explain something and short enough to read.
    max_records: int = 2000
    #: How many losing candidates to keep per decision. The ticket asks for the
    #: "top competing scores", not all of them.
    rivals: int = 3


DEFAULT_TRACE_CONFIG = TraceConfig()


def _weights_of(behavior: ResolvedBehavior) -> tuple[tuple[FactorName, float], ...]:
    """Walked in declared factor order. See `factors.FACTORS` on why."""
    return tuple((factor, behavior.weights[factor]) for factor in FACTORS)


def _personalities_of(behavior: ResolvedBehavior) -> tuple[PersonalityRecord, ...]:
    """The one place that knows how the behavior layer spells personalities.

    JQ-330 replaces `ResolvedBehavior.personalities` — today a `(tag, strength)`
    pair — with a `ResolvedPersonality` carrying per-source provenance, the
    authored summary line and the contextual rules. When it lands, this function
    is the edit; every record, report and scenario above it keeps working. Per
    that ticket, it becomes:

        return tuple(
            PersonalityRecord(tag=p.tag, strength=p.strength, overridden=not defaulted(p))
            for p in behavior.personalities
        )

    with `defaulted` imported from `app.sim.ai.profiles`. Note that `defaulted`
    collapses every source to "did any reference override", which is the right
    answer for a one-mage troop and a lie for any other — see
    `PersonalityRecord.overridden`.
    """
    return tuple(
        PersonalityRecord(
            tag=personality.tag,
            strength=personality.strength,
            overridden=not defaulted(personality),
            sources=tuple(
                PersonalitySourceRecord(
                    mage_id=source.mage_id,
                    strength=source.strength,
                    overridden=source.overridden,
                )
                for source in personality.sources
            ),
        )
        for personality in behavior.personalities
    )


def _reason_of(decision: Decision) -> str:
    """JQ-329's reason vocabulary, once `Intent` carries it.

    `Decision` does not hold the intent — `intent_of` builds it afterwards — so
    there is nothing to read yet and nothing to invent. Returning empty is the
    honest answer, and the report renders it as unexplained rather than as a
    reason called "".
    """
    reason = getattr(decision, "reason", "")
    return reason if isinstance(reason, str) else ""


class DecisionTrace:
    """Collects decisions as they are made, within its bounds.

    Not frozen, and deliberately not part of the world: it is the one mutable
    thing in the decision path, which is exactly why it hangs off `TickContext`
    rather than off `World`. `run_battle` deep-copies the world every tick, and
    a trace that got copied with it would fork into 1800 traces.
    """

    def __init__(self, config: TraceConfig = DEFAULT_TRACE_CONFIG) -> None:
        self.config = config
        self._records: list[TraceRecord] = []
        #: How many decisions the cap turned away. Out-of-window decisions are
        #: not dropped — they were never asked for.
        self.dropped = 0

    @property
    def records(self) -> tuple[TraceRecord, ...]:
        return tuple(self._records)

    def wants(self, tick: int, unit_id: UnitId) -> bool:
        """Whether this decision is in scope, before anything is built for it.

        Public, but nothing outside this class calls it. An earlier docstring
        claimed the decision phase asks first, so that a narrowed trace would
        cost the other units a comparison rather than a record — which described
        a caller that was never written, and an optimisation that would buy
        nothing if it were, since `record` performs this same check before it
        builds anything. Kept public because it is a reasonable question to ask
        a trace; the rationale is corrected because it was fiction.
        """
        config = self.config
        if tick < config.first_tick:
            return False
        if config.last_tick is not None and tick > config.last_tick:
            return False
        return config.unit_ids is None or unit_id in config.unit_ids

    def record(self, tick: int, observation: Observation, decision: Decision) -> None:
        """Flattens one decision into a record, if it is wanted and there is room."""
        unit = observation.unit
        if not self.wants(tick, unit.id):
            return

        if len(self._records) >= self.config.max_records:
            self.dropped += 1
            return

        behavior = unit.ai.behavior if unit.ai is not None else None
        chosen, rivals = _split(decision, self.config.rivals)

        self._records.append(
            TraceRecord(
                tick=tick,
                unit_id=unit.id,
                troop_id=unit.troop_id,
                side=unit.side,
                type_id=unit.type_id,
                station=observation.objective.station,
                may_attack_base=observation.objective.may_attack_base,
                traits=behavior.traits if behavior else (),
                personalities=_personalities_of(behavior) if behavior else (),
                weights=_weights_of(behavior) if behavior else (),
                chosen=chosen,
                rivals=rivals,
                candidate_count=len(decision.considered),
                reason=_reason_of(decision),
                assignment=observation.assignment,
            )
        )


def _split(decision: Decision, keep: int) -> tuple[CandidateRecord, tuple[CandidateRecord, ...]]:
    """The winner, and the strongest losers behind it.

    Sorted by score descending, with the original scoring order breaking ties —
    `sorted` is stable, so walking `considered` in order and sorting on the
    score alone reproduces the loop's own tie-break rather than inventing a
    second one.

    **One asymmetry, and it only appears with jitter on.** `decision.considered`
    holds the scores as scored; `decision.score` is the winner's *after*
    `decide.py` added its seeded nudge. The winner is reported with the
    authoritative total and the losers with what they scored, because those are
    the only two numbers the decision keeps — the losers' jittered scores are
    discarded inside `_with_jitter` and never reach here. So on a profile with
    `tie_break_jitter` above zero, a rival can show a score up to the jitter
    above the winner's. Every sample profile leaves jitter at zero, where the
    two are the same number and the question does not arise.
    """
    chosen = None
    losers: list[CandidateRecord] = []

    for entry in decision.considered:
        record = CandidateRecord(
            kind=entry.candidate.kind,
            target_id=entry.candidate.target_id,
            ability_id=entry.candidate.ability_id,
            destination=entry.candidate.destination,
            score=entry.score,
            contributions=entry.contributions,
            influences=entry.influences,
        )
        if chosen is None and entry.candidate == decision.selected:
            # Scored before jitter; the decision's own total is authoritative.
            chosen = CandidateRecord(
                kind=record.kind,
                target_id=record.target_id,
                ability_id=record.ability_id,
                destination=record.destination,
                score=decision.score,
                contributions=decision.contributions,
                influences=decision.influences,
            )
            continue
        losers.append(record)

    if chosen is None:  # pragma: no cover - `selected` always comes from `considered`
        raise ValueError(f"decision for {decision.unit_id} selected a candidate it never scored")

    return chosen, tuple(sorted(losers, key=lambda r: -r.score)[:keep])
