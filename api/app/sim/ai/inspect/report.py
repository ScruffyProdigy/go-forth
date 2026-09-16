"""Records in, explanation out — in one form for a person and one for a diff.

Two renderings of the same records, because the ticket wants two different
things from them. `render_text` is for the question "why did that hound run
past the mage", read once by a person during a playtest. `as_dicts` and
`render_json` are for "this run and that run disagree at tick 340", which is a
comparison, and comparisons want stable keys rather than aligned columns.

Both are **pure functions returning strings**. Nothing here opens a file or
prints: this module is inside the sim's import graph, which `tests/sim/
test_purity.py` holds to no I/O at all. `app/scripts/decision_report.py` is what
writes the output to a terminal.

Every iteration order here is a list or a declared tuple. No dict is walked for
output and no set is walked at all — see `CONVENTIONS.md` on why a `set` of
strings iterates differently in every fresh Python process, and why that would
make the JSON half useless for the one job it has.
"""

from __future__ import annotations

import json

from app.sim.ai.factors import FactorContribution
from app.sim.ai.inspect.record import CandidateRecord, PersonalityRecord, TraceRecord
from app.sim.ai.intent import Assignment
from app.sim.types import Vec2

#: What a decision with no JQ-329 reason attached renders as. Distinguishable
#: from a reason that happens to be short, and honest about which it is.
NO_REASON = "unexplained"


def _position(vec: Vec2 | None) -> str:
    return f"({vec.x:g}, {vec.y:g})" if vec is not None else "-"


def _action(candidate: CandidateRecord) -> str:
    """The verb, plus whichever of its objects that verb actually has."""
    parts: list[str] = [candidate.kind]
    if candidate.target_id is not None:
        parts.append(f"-> {candidate.target_id}")
    if candidate.ability_id is not None:
        parts.append(f"[{candidate.ability_id}]")
    if candidate.destination is not None and candidate.target_id is None:
        parts.append(f"to {_position(candidate.destination)}")
    return " ".join(parts)


def _why(candidate: CandidateRecord, reason: str) -> str:
    """The reason, and who it was done for when that is recorded.

    Deliberately not parsed: JQ-329 owns the reason vocabulary and narrows it as
    the behaviors grow — `screening` covered every screen until it came to mean
    only the assigned kind. Appending "for <ally>" whenever an ally is present
    reads correctly for any reason that has one, and stays correct for reasons
    that do not exist yet.
    """
    text = reason or NO_REASON
    if candidate.protecting_id is not None:
        return f"{text} for {candidate.protecting_id}"
    return text


def _contributions(contributions: tuple[FactorContribution, ...]) -> str:
    """Each factor's raw verdict and the weight that scaled it, in one line.

    Both halves rather than the product alone: a factor contributing nothing
    because the unit does not care about it and one contributing nothing because
    the field is neutral are different findings, and only showing the product
    makes them look identical.
    """
    return ", ".join(f"{c.factor} {c.raw:+.2f}x{c.weight:g}={c.contribution:+.2f}" for c in contributions)


def _personality(personality: PersonalityRecord) -> str:
    """A tag and its strength, and where that strength came from if known.

    `overridden is None` means the behavior layer does not record provenance yet
    (JQ-330). Printing neither word is the point — a reader who sees "strength
    1.5" and no provenance knows it was not reported, whereas a reader who sees
    "default" would believe something nobody checked.
    """
    if personality.overridden is None:
        return f"{personality.tag} {personality.strength:g}"

    # More than one mage named this tag, so a single "overridden" would
    # attribute one mage's choice to both. Name them instead.
    if len(personality.sources) > 1:
        detail = ", ".join(
            f"{source.mage_id} {source.strength:g}{' overridden' if source.overridden else ' default'}"
            for source in personality.sources
        )
        return f"{personality.tag} {personality.strength:g} (from {detail})"

    source = "overridden" if personality.overridden else "default"
    return f"{personality.tag} {personality.strength:g} ({source})"


def _influences(candidate: CandidateRecord) -> str:
    """Which authored tag moved which weight here, and what woke it up.

    The complement to `_contributions`: that says what the unit weighed, this
    says who put the weight there. A tag silent on this candidate does not
    appear, which is how a contextual rule shows itself.
    """
    return ", ".join(f"{i.tag}/{i.context} {i.factor} {i.delta:+.2f}" for i in candidate.influences)


def _assignment_line(assignment: Assignment | None) -> str:
    if assignment is None:
        return ""
    return (
        f"\n    assigned {assignment.target_id}"
        f" for {assignment.protecting_id} since tick {assignment.since_tick}"
    )


def _behavior_line(record: TraceRecord) -> str:
    traits = ", ".join(record.traits) if record.traits else "none"
    personalities = (
        "; ".join(_personality(p) for p in record.personalities) if record.personalities else "none"
    )
    return f"    traits: {traits}\n    personalities: {personalities}"


def _record_text(record: TraceRecord) -> str:
    lines = [
        f"tick {record.tick}  {record.unit_id} ({record.type_id}, {record.side}/{record.troop_id})",
        f"    posted at {_position(record.station)}"
        f"{'' if record.may_attack_base else '  [base off limits]'}"
        f"{_assignment_line(record.assignment)}",
        _behavior_line(record),
        f"    weights: {', '.join(f'{factor} {value:g}' for factor, value in record.weights)}",
        f"    chose {_action(record.chosen)}  {record.chosen.score:+.3f}"
        f"  ({_why(record.chosen, record.reason)})",
        f"      {_contributions(record.chosen.contributions)}",
    ]

    if record.chosen.influences:
        lines.append(f"      via {_influences(record.chosen)}")

    if record.rivals:
        beaten = record.candidate_count - 1 - len(record.rivals)
        tail = f" (+{beaten} more)" if beaten > 0 else ""
        lines.append(f"    over {len(record.rivals)} of {record.candidate_count - 1} rivals{tail}:")
        for rival in record.rivals:
            lines.append(f"      {_action(rival)}  {rival.score:+.3f}")
            lines.append(f"        {_contributions(rival.contributions)}")
            if rival.influences:
                lines.append(f"        via {_influences(rival)}")
    else:
        lines.append("    no other candidate was legal")

    return "\n".join(lines)


def render_text(records: tuple[TraceRecord, ...], dropped: int = 0) -> str:
    """The whole trace, as something to read top to bottom."""
    if not records:
        return "no decisions were traced — check the trace's tick window and unit filter\n"

    body = "\n\n".join(_record_text(record) for record in records)
    footer = f"\n\n{len(records)} decisions traced"
    if dropped:
        footer += f", {dropped} dropped at the trace's record cap"
    return f"{body}{footer}\n"


def _candidate_dict(candidate: CandidateRecord) -> dict[str, object]:
    return {
        "kind": candidate.kind,
        "target": candidate.target_id,
        "ability": candidate.ability_id,
        "destination": (
            {"x": candidate.destination.x, "y": candidate.destination.y}
            if candidate.destination is not None
            else None
        ),
        "protecting": candidate.protecting_id,
        "score": candidate.score,
        "influences": [
            {"tag": i.tag, "context": i.context, "factor": i.factor, "delta": i.delta}
            for i in candidate.influences
        ],
        "contributions": [
            {
                "factor": c.factor,
                "raw": c.raw,
                "weight": c.weight,
                "contribution": c.contribution,
            }
            for c in candidate.contributions
        ],
    }


def as_dicts(records: tuple[TraceRecord, ...]) -> list[dict[str, object]]:
    """The trace as plain data — JSON-able, comparable, no formatting decisions."""
    return [
        {
            "tick": record.tick,
            "unit": {
                "id": record.unit_id,
                "troop": record.troop_id,
                "side": record.side,
                "typeId": record.type_id,
            },
            "assignment": {
                "station": {"x": record.station.x, "y": record.station.y},
                "mayAttackBase": record.may_attack_base,
                "coordinated": (
                    {
                        "targetId": record.assignment.target_id,
                        "protectingId": record.assignment.protecting_id,
                        "sinceTick": record.assignment.since_tick,
                    }
                    if record.assignment is not None
                    else None
                ),
            },
            "behavior": {
                "traits": list(record.traits),
                "personalities": [
                    {
                        "tag": p.tag,
                        "strength": p.strength,
                        "overridden": p.overridden,
                        "sources": [
                            {"mageId": q.mage_id, "strength": q.strength, "overridden": q.overridden}
                            for q in p.sources
                        ],
                    }
                    for p in record.personalities
                ],
                "weights": [{"factor": factor, "weight": value} for factor, value in record.weights],
            },
            "reason": record.reason,
            "chosen": _candidate_dict(record.chosen),
            "rivals": [_candidate_dict(rival) for rival in record.rivals],
            "candidateCount": record.candidate_count,
        }
        for record in records
    ]


def render_json(records: tuple[TraceRecord, ...], dropped: int = 0) -> str:
    """One JSON document. Keys in insertion order, which is declaration order."""
    return json.dumps(
        {
            "traced": len(records),
            "dropped": dropped,
            "decisions": as_dicts(records),
        },
        separators=(",", ":"),
    )
