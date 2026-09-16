"""The record of a run, and the replay that proves it is one.

A demo run is two phones, one server and no second chance. When something looks
wrong afterwards — a spell that seemed not to land, a round that ended in a way
nobody expected — the only honest way to answer is to run it again and watch.
That needs everything the battle was a function of, which is a short list and
would be a much shorter one if the sim were not already deterministic:

* **who it was** — run id, match id, game mode, whether it was a test profile
* **what it was played under** — `RULES_VERSION`, `CONTENT_VERSION`, the sim
  config, the map
* **what went in** — per round: the seed, the base HP it opened on, both plans
  as submitted, both resolved loadouts
* **what the players did** — every accepted cast, with the tick and order the
  *server* assigned it
* **how it came out** — each round's ending, the match's ending, the base HP
  left, and the terminal reason

`replay_run` takes that and re-runs the whole thing headlessly. It is not a
viewer and does not pretend to be one (the ticket rules a viewer out); it is the
assertion that the record is complete. A record you cannot replay is a record
that quietly stopped carrying something, and the only way to find that out is to
try.

## What is deliberately not in here

**No rejected commands.** A rejection changed nothing about the battle, so it
cannot affect a replay; it belongs in `diagnostics.py`, where it can be counted
and correlated with reconnects. Putting them here would make the record grow
with a client's retry loop and imply, falsely, that replaying them matters.

**No snapshots.** State is derived from the inputs above, which is the whole
claim determinism makes. Recording states as well would be recording the answer
next to the working, and the first time the two disagreed nobody would know
which to believe.

**No credentials, and no Lobby endpoints.** Nothing here names a `player_id`, a
service token or a return URL. Seats are `seatKey` and `side`. A run record is
written to be read by someone investigating a match rather than playing in one.

## Reproducing the interactive run

The live round takes a cast the moment it arrives and schedules it on the next
tick. The replay does the same thing from the other end: before stepping into
tick *T* it submits every recorded cast whose tick is *T*, in `order`. Energy is
therefore spent at the same point in the same tick as it was live, which matters
because seat energy accrues per tick — spending a tick later would leave a
different balance and, at a cost boundary, a different set of legal casts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.match import fixtures
from app.match.plan import parse_plan, plan_to_json, resolve_loadout
from app.match.round import AuthoritativeRound, RoundEnding
from app.match.versions import CONTENT_VERSION, RULES_VERSION
from app.match.wire import CastCommand, LoadoutSpell
from app.sim.config import SimConfig
from app.sim.map import MapConfig
from app.sim.run_battle import BattleResult
from app.sim.types import SIDES, Side, Vec2

#: Bumped when the record's own shape changes. Separate from the rules and
#: content versions: a record written by an older server is still replayable if
#: the rules have not moved, and conflating "we store it differently now" with
#: "the game decides differently now" would throw away records needlessly.
RECORD_VERSION = 1


class ReplayError(Exception):
    """A record this server cannot faithfully re-run."""


@dataclass(frozen=True, slots=True)
class RecordedCast:
    """One accepted cast, exactly as the server took it."""

    order: int
    tick: int
    side: Side
    command_id: str
    spell_id: str
    x: float
    y: float

    def to_json(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "tick": self.tick,
            "side": self.side,
            "commandId": self.command_id,
            "spellId": self.spell_id,
            "at": {"x": self.x, "y": self.y},
        }

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> RecordedCast:
        at = raw.get("at") or {}
        return RecordedCast(
            order=int(raw["order"]),
            tick=int(raw["tick"]),
            side=str(raw["side"]),  # type: ignore[arg-type]
            command_id=str(raw["commandId"]),
            spell_id=str(raw["spellId"]),
            x=float(at["x"]),
            y=float(at["y"]),
        )


@dataclass
class RecordedRound:
    """One round: what it opened on, what was done in it, how it ended."""

    number: int
    seed: int
    starting_energy: float
    #: Base HP as the round *opened*. Recorded per round rather than derived,
    #: because that is the no-recovery rule's observable: a round that opened on
    #: full HP after one that ended damaged is the bug, and a record that
    #: recomputed this from the previous round could not show it.
    base_hp_at_start: dict[str, float]
    #: Both plans, in the shape `parse_plan` reads back.
    plans: dict[str, dict[str, Any]]
    #: Both resolved loadouts, with the costs the server priced them at.
    loadouts: dict[str, list[dict[str, Any]]]
    casts: list[RecordedCast] = field(default_factory=list)
    #: The wire ending. None on a round that was still running when the match
    #: was abandoned.
    ending: dict[str, Any] | None = None
    base_hp_at_end: dict[str, float] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "round": self.number,
            "seed": self.seed,
            "startingEnergy": self.starting_energy,
            "baseHpAtStart": dict(self.base_hp_at_start),
            "plans": {side: dict(plan) for side, plan in self.plans.items()},
            "loadouts": {side: [dict(s) for s in spells] for side, spells in self.loadouts.items()},
            "casts": [cast.to_json() for cast in self.casts],
            "ending": dict(self.ending) if self.ending is not None else None,
            "baseHpAtEnd": dict(self.base_hp_at_end) if self.base_hp_at_end is not None else None,
        }

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> RecordedRound:
        ending = raw.get("ending")
        base_hp_at_end = raw.get("baseHpAtEnd")
        return RecordedRound(
            number=int(raw["round"]),
            seed=int(raw["seed"]),
            starting_energy=float(raw["startingEnergy"]),
            base_hp_at_start={k: float(v) for k, v in dict(raw["baseHpAtStart"]).items()},
            plans={k: dict(v) for k, v in dict(raw["plans"]).items()},
            loadouts={k: [dict(s) for s in v] for k, v in dict(raw["loadouts"]).items()},
            casts=[RecordedCast.from_json(entry) for entry in raw.get("casts", ())],
            ending=dict(ending) if isinstance(ending, dict) else None,
            base_hp_at_end=(
                {k: float(v) for k, v in dict(base_hp_at_end).items()}
                if isinstance(base_hp_at_end, dict)
                else None
            ),
        )


@dataclass
class RunRecord:
    """Everything one run of the demo was a function of."""

    run_id: str
    match_id: str
    game_mode: str
    test_profile: bool
    map_id: str
    tick_rate: int
    max_battle_seconds: float
    rounds: list[RecordedRound] = field(default_factory=list)
    #: The match's wire ending. None until the match is over.
    ending: dict[str, Any] | None = None
    #: The one word for how the run stopped: the match ending's kind for a
    #: terminal one (`baseDestroyed`, `abandoned`), and otherwise the final
    #: round's reason (`zoneControl`, `annihilation`, `timeUp`). Stored rather
    #: than derived at read time so a record stays legible after the vocabulary
    #: moves on (Ryan, 2026-09-13).
    terminal_reason: str | None = None
    rounds_won: dict[str, int] = field(default_factory=dict)
    #: Remaining base HP at the end of the run, both sides.
    base_hp: dict[str, float] = field(default_factory=dict)
    record_version: int = RECORD_VERSION
    rules_version: int = RULES_VERSION
    content_version: int = CONTENT_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "recordVersion": self.record_version,
            "rulesVersion": self.rules_version,
            "contentVersion": self.content_version,
            "runId": self.run_id,
            "matchId": self.match_id,
            "gameMode": self.game_mode,
            "testProfile": self.test_profile,
            "mapId": self.map_id,
            "tickRate": self.tick_rate,
            "maxBattleSeconds": self.max_battle_seconds,
            "rounds": [entry.to_json() for entry in self.rounds],
            "ending": dict(self.ending) if self.ending is not None else None,
            "terminalReason": self.terminal_reason,
            "roundsWon": dict(self.rounds_won),
            "baseHp": dict(self.base_hp),
        }

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> RunRecord:
        ending = raw.get("ending")
        return RunRecord(
            run_id=str(raw["runId"]),
            match_id=str(raw["matchId"]),
            game_mode=str(raw["gameMode"]),
            test_profile=bool(raw["testProfile"]),
            map_id=str(raw["mapId"]),
            tick_rate=int(raw["tickRate"]),
            max_battle_seconds=float(raw["maxBattleSeconds"]),
            rounds=[RecordedRound.from_json(entry) for entry in raw.get("rounds", ())],
            ending=dict(ending) if isinstance(ending, dict) else None,
            terminal_reason=raw.get("terminalReason"),
            rounds_won={k: int(v) for k, v in dict(raw.get("roundsWon", {})).items()},
            base_hp={k: float(v) for k, v in dict(raw.get("baseHp", {})).items()},
            record_version=int(raw.get("recordVersion", RECORD_VERSION)),
            rules_version=int(raw.get("rulesVersion", RULES_VERSION)),
            content_version=int(raw.get("contentVersion", CONTENT_VERSION)),
        )


# -------------------------------------------------------------- the recorder --


class RunRecorder:
    """Builds a `RunRecord` as a live session plays, one round at a time.

    Held by `MatchSession` and told about things rather than reaching into it.
    The session is the only thing that knows when a round has really started —
    plans can be locked in either order and a backstop can start one with no
    lock at all — so a recorder that watched state would need the same rules
    again, in a second place, to decide what it was looking at.
    """

    def __init__(
        self,
        *,
        run_id: str,
        match_id: str,
        game_mode: str,
        test_profile: bool,
        map_config: MapConfig,
        sim_config: SimConfig,
    ) -> None:
        self.record = RunRecord(
            run_id=run_id,
            match_id=match_id,
            game_mode=game_mode,
            test_profile=test_profile,
            map_id=map_config.id,
            tick_rate=sim_config.tick_rate,
            max_battle_seconds=sim_config.max_battle_seconds,
        )
        self._current: RecordedRound | None = None

    def round_started(
        self,
        *,
        number: int,
        seed: int,
        starting_energy: float,
        base_hp: Mapping[Side, float],
        plans: Mapping[Side, Any],
        loadouts: Mapping[Side, Sequence[LoadoutSpell]],
    ) -> None:
        entry = RecordedRound(
            number=number,
            seed=seed,
            starting_energy=starting_energy,
            base_hp_at_start={side: float(base_hp[side]) for side in SIDES},
            plans={side: plan_to_json(plans[side]) for side in SIDES},
            loadouts={side: [spell.to_json() for spell in loadouts.get(side, ())] for side in SIDES},
        )
        self._current = entry
        self.record.rounds.append(entry)

    def cast_accepted(
        self, *, side: Side, command_id: str, spell_id: str, at: Vec2, tick: int, order: int
    ) -> None:
        if self._current is None:
            return
        self._current.casts.append(
            RecordedCast(
                order=order,
                tick=tick,
                side=side,
                command_id=command_id,
                spell_id=spell_id,
                x=at.x,
                y=at.y,
            )
        )

    def round_finished(self, *, ending: Mapping[str, Any], base_hp: Mapping[Side, float]) -> None:
        if self._current is None:
            return
        self._current.ending = dict(ending)
        self._current.base_hp_at_end = {side: float(base_hp[side]) for side in SIDES}
        self._current = None

    def match_finished(
        self,
        *,
        ending: Mapping[str, Any],
        terminal_reason: str | None,
        rounds_won: Mapping[Side, int],
        base_hp: Mapping[Side, float],
    ) -> None:
        self.record.ending = dict(ending)
        self.record.terminal_reason = terminal_reason
        self.record.rounds_won = {side: int(rounds_won[side]) for side in SIDES}
        self.record.base_hp = {side: float(base_hp[side]) for side in SIDES}


# ----------------------------------------------------------------- the replay --


@dataclass(frozen=True, slots=True)
class ReplayedRound:
    number: int
    ending: RoundEnding
    base_hp: dict[str, float]
    casts_applied: int
    #: The replayed battle in the sim's own result shape — every tick, every
    #: event, both armies. Carried so a caller can compare a replay to the live
    #: run at full resolution rather than on its outcome, which is the only
    #: comparison strong enough to be evidence: a mirror match on a short round
    #: ends `timeUp` with no winner under almost any seed, so two runs agreeing
    #: on their *ending* says nothing about whether they were the same battle.
    #:
    #: Kept out of the stored record itself — a record holds inputs, not states
    #: (see the module docstring) — and out of reach of `wire.py`, which may
    #: never put the sim's serialisation in front of a client.
    result: BattleResult


@dataclass(frozen=True, slots=True)
class ReplayResult:
    rounds: list[ReplayedRound]
    base_hp: dict[str, float]

    def endings_json(self) -> list[dict[str, Any]]:
        """The endings in the wire's own vocabulary, for comparing to a record."""
        return [_ending_json(entry.ending) for entry in self.rounds]


def _ending_json(ending: RoundEnding) -> dict[str, Any]:
    if ending.kind == "baseDestroyed":
        return {"kind": "baseDestroyed", "winner": ending.winner}
    return {"kind": "roundComplete", "winner": ending.winner, "reason": ending.reason}


def replay_run(record: RunRecord, *, map_config: MapConfig | None = None) -> ReplayResult:
    """Re-run a recorded run headlessly and return what happened this time.

    Raises `ReplayError` rather than producing a different battle when the
    record was written under rules or content this server no longer implements.
    A silent divergence is the failure mode worth spending an exception on: the
    whole value of a replay is that it is the same run, and one that is merely
    *similar* would be used to draw conclusions about a match that never
    happened.
    """
    if record.rules_version != RULES_VERSION:
        raise ReplayError(
            f"run {record.run_id} was played under rules v{record.rules_version}; "
            f"this server is v{RULES_VERSION}"
        )
    if record.content_version != CONTENT_VERSION:
        raise ReplayError(
            f"run {record.run_id} was played on content v{record.content_version}; "
            f"this server is v{CONTENT_VERSION}"
        )

    config = map_config or fixtures.map_config()
    if config.id != record.map_id:
        raise ReplayError(f"run {record.run_id} was played on map {record.map_id!r}, not {config.id!r}")

    sim_config = SimConfig(tick_rate=record.tick_rate, max_battle_seconds=record.max_battle_seconds)

    replayed: list[ReplayedRound] = []
    base_hp: dict[str, float] = {}

    for entry in record.rounds:
        if entry.ending is None:
            # A round that was still running when the match was abandoned has no
            # outcome to reproduce. Stopping here rather than replaying it keeps
            # the replay a claim about finished rounds only.
            break

        plans = {side: parse_plan(entry.plans[side]) for side in SIDES}
        loadouts = {side: resolve_loadout(plans[side]) for side in SIDES}
        round_ = AuthoritativeRound(
            round_number=entry.number,
            map_config=config,
            plans=plans,
            loadouts=loadouts,
            base_hp={side: entry.base_hp_at_start[side] for side in SIDES},
            seed=entry.seed,
            sim_config=sim_config,
            starting_energy=entry.starting_energy,
        )

        pending = sorted(entry.casts, key=lambda cast: (cast.tick, cast.order))
        index = 0
        applied = 0
        while not round_.over:
            # Everything the server scheduled on the tick about to run, in the
            # order it accepted them. Submitted *before* the step, which is
            # where they were submitted live.
            next_tick = round_.world.tick + 1
            while index < len(pending) and pending[index].tick == next_tick:
                recorded = pending[index]
                index += 1
                outcome = round_.cast(
                    recorded.side,
                    CastCommand(
                        command_id=recorded.command_id,
                        spell_id=recorded.spell_id,
                        at=Vec2(recorded.x, recorded.y),
                        # The world's own tick, so the staleness window — which
                        # is about a client's connection and has no meaning in a
                        # replay — can never refuse a cast the server accepted.
                        tick=round_.world.tick,
                    ),
                )
                if not outcome.accepted:
                    raise ReplayError(
                        f"run {record.run_id} round {entry.number}: the server accepted "
                        f"{recorded.command_id!r} live and refuses it on replay ({outcome.rejection})"
                    )
                applied += 1
            round_.step()

        ending = round_.ending
        assert ending is not None
        base_hp = {side: value for side, value in round_.base_hp().items()}
        replayed.append(
            ReplayedRound(
                number=entry.number,
                ending=ending,
                base_hp=dict(base_hp),
                casts_applied=applied,
                result=round_.result(),
            )
        )

        if index < len(pending):
            raise ReplayError(
                f"run {record.run_id} round {entry.number}: {len(pending) - index} recorded cast(s) "
                "were never reached — the replayed round ended earlier than the recorded one"
            )

    return ReplayResult(rounds=replayed, base_hp=base_hp)
