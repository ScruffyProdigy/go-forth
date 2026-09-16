"""The authoritative match session: seats, phases, the tick loop, the result.

One instance per live match. It owns the phase the match is in, the round in
progress, and the single fact every seat's snapshot is projected from. Nothing
below it reads a clock either — `tick()` is called by the driver in `clock.py`,
so a test can run a whole match in microseconds and the server can run one in
real time, off the same code.

## The phases

    planning ──both seats locked──▶ battle ──round ends──▶ roundOver
                                                             │
                                     more rounds to play ◀───┤
                                                             ▼
                                                         matchOver

A base destroyed skips straight to `matchOver` from wherever it happened. That
is the 2026-09-13 rule and it is enforced in one place, `_finish_round`, rather
than being a condition every transition has to remember.

## What the demo may not claim

`RoundPolicy.test_profile` is carried from the mode manifest all the way into
`reportMatchResult`. A single round is not a completed best-of-five, so the
opening demo's terminal ending is `testComplete` on the wire and `CANCELLED`
— unrated — to the Lobby. The round winner still travels in both, because the
run should be legible; what it must not be is counted as a series somebody won.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from app.lobby.client import LobbyClient, MatchResultStatus
from app.lobby.manifest import GameMode, RoundPolicy
from app.match import fixtures, wire
from app.match.commands import CommandLedger, LedgerEntry
from app.match.diagnostics import DiagnosticsLog
from app.match.plan import (
    PlanError,
    SubmittedPlan,
    default_plan,
    parse_plan,
    plan_to_json,
    resolve_loadout,
    validate_plan,
)
from app.match.round import AuthoritativeRound, RoundEnding
from app.match.run_record import RunRecord, RunRecorder
from app.match.wire import CastCommand, CastRejection, LoadoutSpell
from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig
from app.sim.map import MapConfig
from app.sim.types import SIDES, Side

log = logging.getLogger(__name__)

Phase = Literal["planning", "battle", "roundOver", "matchOver"]

#: How long a finished round is shown before the next plan phase opens. In ticks
#: so it runs on the same clock as everything else. Provisional.
ROUND_OVER_TICKS = 60

#: The backstop that advances a plan phase when a seat never locks in. JQ-308
#: owns the missed-plan policy proper; this is the "generous backstop" half of
#: its rule, so a demo cannot hang forever on a player who put their phone down.
#: Sixty seconds at the default tick rate.
PLANNING_BACKSTOP_TICKS = 20 * 60


def _terminal_reason(match_ending: Mapping[str, Any], round_ending: Mapping[str, Any]) -> str:
    """The one word for how a run stopped (Ryan, 2026-09-13).

    A match ending and a round ending both carry a `kind`, and a result that
    reported only one of them is unreadable in a different way each time. A run
    that ended `testComplete` says nothing about *why* the last round stopped;
    one that ended `baseDestroyed` must not be reported as though a lane was
    scored out. So: the match's kind when it is terminal in its own right, and
    otherwise the round's reason.

    It travels in the run record and in the Lobby metadata, which is what makes
    "the base fell" survive into a history row rather than living only in a
    result screen nobody kept.
    """
    kind = str(match_ending.get("kind") or "")
    if kind in ("baseDestroyed", "abandoned"):
        return kind
    reason = round_ending.get("reason")
    return str(reason) if reason else kind


@dataclass
class Seat:
    """One seat of the match, and the player who holds it."""

    seat_key: str
    side: Side
    #: Set once a Lobby-linked player claims it. None on an unclaimed seat.
    lobby_user_id: str | None = None
    player_id: str | None = None
    display_name: str | None = None
    #: Whether a socket is currently holding this seat. A dropped socket is not
    #: a player who left: the battle runs on, the seat is held, and the player
    #: is expected back (integration guide §6).
    connected: bool = False
    #: Set when the player genuinely left, which is the only thing that closes
    #: their way back in.
    departed: bool = False
    #: How many sockets have ever held this seat. The first is an arrival; every
    #: one after it is a return, and a diagnostic that could not tell the two
    #: apart could not show a reconnect loop — which is what a player on a bad
    #: connection actually experiences (JQ-310).
    sockets_seen: int = 0


@dataclass
class _RoundState:
    plans: dict[Side, SubmittedPlan] = field(default_factory=dict)
    locked: dict[Side, bool] = field(default_factory=lambda: {side: False for side in SIDES})
    loadouts: dict[Side, list[LoadoutSpell]] = field(default_factory=dict)


class MatchSession:
    """A live match. Every mutation returns having left the session consistent."""

    def __init__(
        self,
        *,
        run_id: str,
        external_match_id: str,
        mode: GameMode,
        seats: Mapping[str, Side],
        map_config: MapConfig | None = None,
        sim_config: SimConfig = DEFAULT_SIM_CONFIG,
        seed: int = 1,
        lobby_client: LobbyClient | None = None,
        diagnostics: DiagnosticsLog | None = None,
        starting_energy: float = fixtures.STARTING_ENERGY,
    ) -> None:
        self.run_id = run_id
        self.external_match_id = external_match_id
        self.mode = mode
        self.policy: RoundPolicy = mode.round_policy
        self.map_config = map_config or fixtures.map_config()
        self.sim_config = sim_config
        self.seed = seed
        self.lobby_client = lobby_client
        #: What each seat opens a round's spell pool with. Held here rather than
        #: read from `fixtures` at each use: the round takes it as an argument
        #: and the run record stores it, and three readers of one provisional
        #: constant is three places for them to stop agreeing.
        self.starting_energy = starting_energy

        self.seats: dict[str, Seat] = {
            seat_key: Seat(seat_key=seat_key, side=side) for seat_key, side in seats.items()
        }
        self._side_to_seat: dict[Side, str] = {side: seat_key for seat_key, side in seats.items()}

        self.phase: Phase = "planning"
        self.round_number = 1
        self.rounds_won: dict[Side, int] = {side: 0 for side in SIDES}
        # Opened at the map's own maximum. Nothing refills these between rounds.
        self._base_hp: dict[Side, float] = {side: self.map_config.bases[side].max_hp for side in SIDES}

        self._round_state = _RoundState()
        self._round: AuthoritativeRound | None = None
        self._last_round_result: dict[str, Any] | None = None
        self._match_result: dict[str, Any] | None = None
        self._phase_ticks = 0
        #: Set once the Lobby has been told, so a retry is idempotent on our side
        #: as well as on theirs.
        self._reported = False

        #: One answer per command id, for the whole match (JQ-310). On the
        #: session rather than the round, so a retry that arrives after its
        #: round ended is still answered with what actually happened.
        self._ledger = CommandLedger()
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticsLog()
        self._recorder = RunRecorder(
            run_id=run_id,
            match_id=external_match_id,
            game_mode=mode.key,
            test_profile=self.policy.test_profile,
            map_config=self.map_config,
            sim_config=self.sim_config,
        )

    # ---------------------------------------------------------------- seats --

    def seat_for_side(self, side: Side) -> Seat:
        return self.seats[self._side_to_seat[side]]

    def side_for_seat(self, seat_key: str) -> Side | None:
        seat = self.seats.get(seat_key)
        return seat.side if seat else None

    def seat_for_player(self, player_id: str) -> Seat | None:
        for seat in self.seats.values():
            if seat.player_id == player_id:
                return seat
        return None

    def seat_for_lobby_user(self, lobby_user_id: str) -> Seat | None:
        for seat in self.seats.values():
            if seat.lobby_user_id == lobby_user_id:
                return seat
        return None

    @property
    def over(self) -> bool:
        return self.phase == "matchOver"

    @property
    def fully_seated(self) -> bool:
        """Whether every seat has been claimed at least once.

        "At least once" and not "is connected right now": a player who dropped
        their socket is still seated and still expected back (integration guide
        §6), so this asks whether the match ever filled, not who is looking at
        it this second.
        """
        return all(seat.player_id is not None for seat in self.seats.values())

    @property
    def round(self) -> AuthoritativeRound:
        """The round in progress.

        Raises outside the battle phase rather than returning None. Every caller
        that wants this is already inside a battle, and an optional here means a
        `None` check at each of them that can only ever be dead code.
        """
        if self._round is None:
            raise RuntimeError(f"no round in progress: the match is in {self.phase!r}")
        return self._round

    # ------------------------------------------------------------- planning --

    def plan_for(self, side: Side) -> SubmittedPlan:
        """This seat's plan: what it locked in, or the legal suggested default.

        A seat that never locked in still fields an army. JQ-308 owns the
        missed-plan policy; what matters here is that "did nothing" resolves to
        a plan the server would have accepted rather than to an empty field.
        """
        existing = self._round_state.plans.get(side)
        if existing is not None:
            return existing
        return default_plan(self.map_config)

    def locked(self, side: Side) -> bool:
        return self._round_state.locked[side]

    def lock_in(self, side: Side, raw_plan: Any) -> None:
        """Take a seat's plan. Raises `PlanError` on anything it will not field.

        Locking is final for the round. A second lock from the same seat is
        refused rather than silently replacing the first: hidden simultaneous
        choice is the point of the phase (§3.2), and a seat that could re-lock
        after seeing its own deployment would be planning with information the
        other seat does not have.
        """
        if self.phase != "planning":
            raise PlanError("the planning phase is over")
        if self._round_state.locked[side]:
            raise PlanError("this seat has already locked in")

        plan = parse_plan(raw_plan)
        validate_plan(plan, self.map_config)

        self._round_state.plans[side] = plan
        self._round_state.loadouts[side] = resolve_loadout(plan)
        self._round_state.locked[side] = True

        if all(self._round_state.locked[s] for s in SIDES):
            self._start_battle()

    def _start_battle(self) -> None:
        for side in SIDES:
            if side not in self._round_state.plans:
                plan = default_plan(self.map_config)
                self._round_state.plans[side] = plan
                self._round_state.loadouts[side] = resolve_loadout(plan)

        # Derived from the run and the round rather than taken from a clock, so
        # a match replayed from its run id reproduces every battle in it.
        seed = self.seed + self.round_number
        self._round = AuthoritativeRound(
            round_number=self.round_number,
            map_config=self.map_config,
            plans=self._round_state.plans,
            loadouts=self._round_state.loadouts,
            base_hp=self._base_hp,
            seed=seed,
            sim_config=self.sim_config,
            starting_energy=self.starting_energy,
        )
        # Recorded here and not on the first tick: this is the moment both plans
        # are fixed and the base HP the round opens on is settled, which is
        # exactly the state a replay has to start from.
        self._recorder.round_started(
            number=self.round_number,
            seed=seed,
            starting_energy=self.starting_energy,
            base_hp=self._base_hp,
            plans=self._round_state.plans,
            loadouts=self._round_state.loadouts,
        )
        self.phase = "battle"
        self._phase_ticks = 0

    # ---------------------------------------------------------------- casts --

    def cast(self, side: Side, command: CastCommand) -> dict[str, Any]:
        """Answer one cast, as a `castOutcome` message ready to send.

        **Exactly one answer per command id, forever.** A retry — the client
        heard nothing and sent the same cast again — is answered from the ledger
        without the round being touched, so a lost acknowledgment costs a player
        nothing and a resend costs them no energy. Everything a cast could be
        refused for is decided once, at the moment the id is first seen.
        """
        seen = self._ledger.find(side, command.command_id)
        if seen is not None:
            self._note_command(
                "command.retried",
                side=side,
                command_id=command.command_id,
                outcome="accepted" if seen.accepted else "rejected",
                reason=seen.reason,
            )
            return seen.to_message()

        if self.phase != "battle" or self._round is None:
            # `wrongPhase` while planning, `roundOver` once a round has been
            # decided: a client that casts during the plan screen has a bug, and
            # one that casts a beat after the round ended has a connection.
            reason: CastRejection = "wrongPhase" if self.phase == "planning" else "roundOver"
            return self._answer(side, LedgerEntry(command.command_id, accepted=False, reason=reason))

        outcome = self._round.cast(side, command)
        if not outcome.accepted:
            return self._answer(
                side,
                LedgerEntry(
                    command.command_id,
                    accepted=False,
                    reason=outcome.rejection,
                    round_number=self.round_number,
                ),
            )

        assert outcome.tick is not None and outcome.order is not None
        self._recorder.cast_accepted(
            side=side,
            command_id=command.command_id,
            spell_id=command.spell_id,
            at=command.at,
            tick=outcome.tick,
            order=outcome.order,
        )
        return self._answer(
            side,
            LedgerEntry(
                command.command_id,
                accepted=True,
                round_number=self.round_number,
                tick=outcome.tick,
                order=outcome.order,
            ),
        )

    def _answer(self, side: Side, entry: LedgerEntry) -> dict[str, Any]:
        """Record the answer and return it, so the two can never disagree."""
        stored = self._ledger.record(side, entry)
        if not stored.accepted:
            self._note_command(
                "command.rejected",
                side=side,
                command_id=stored.command_id,
                reason=stored.reason,
                phase=self.phase,
            )
        return stored.to_message()

    def _note_command(self, kind: str, **fields: Any) -> None:
        self.diagnostics.record(
            channel="command",
            kind=kind,
            match_id=self.external_match_id,
            run_id=self.run_id,
            round=self.round_number,
            **fields,
        )

    def note_connection(self, kind: str, **fields: Any) -> None:
        """A connection event on this match, for the transport to call.

        Here rather than in `ws.py` so a socket does not have to carry the run
        id and match id around to say something happened, and so every
        connection diagnostic in the codebase is emitted through one door.
        """
        self.diagnostics.record(
            channel="connection",
            kind=kind,
            match_id=self.external_match_id,
            run_id=self.run_id,
            phase=self.phase,
            round=self.round_number,
            **fields,
        )

    @property
    def ledger(self) -> CommandLedger:
        return self._ledger

    @property
    def run_record(self) -> RunRecord:
        """The record of this run so far. Complete once the match is over."""
        return self._recorder.record

    # ----------------------------------------------------------------- tick --

    def tick(self) -> bool:
        """Advance the match one tick. True when something changed.

        The one entry point the clock drives. Every phase advances here — the
        battle by stepping the sim, the two waiting phases by counting down —
        so there is exactly one place where time passes and one place a test has
        to drive.
        """
        self._phase_ticks += 1

        if self.phase == "planning":
            # The backstop advances a plan phase a *seated* player never
            # finished. It must not advance one nobody has arrived for: an
            # unclaimed seat would otherwise be handed the suggested default and
            # play out a whole battle against a player who never showed up, and
            # the result would be reported as a real run. What to do about a
            # match that never fills — a forfeit timeout, an abandon — is
            # JQ-308's policy to write; until then this simply waits.
            if self.fully_seated and self._phase_ticks >= PLANNING_BACKSTOP_TICKS:
                self._start_battle()
                return True
            return False

        if self.phase == "battle":
            assert self._round is not None
            self._round.step()
            if self._round.over:
                self._finish_round()
            return True

        if self.phase == "roundOver":
            if self._phase_ticks >= ROUND_OVER_TICKS:
                self._next_round()
                return True
            return False

        return False

    def _finish_round(self) -> None:
        assert self._round is not None
        ending = self._round.ending
        assert ending is not None

        # Base HP is read off the finished round and carried forward as-is.
        # Nothing between here and the next round touches it: that is the
        # no-recovery half of the 2026-09-13 rule, and it is one assignment
        # rather than a rule spread across the transition.
        self._base_hp = self._round.base_hp()

        bases = wire.base_hp(self._round.world, self.map_config)
        zones = wire.zone_states(self._round.world, self.map_config)
        zone_score = {side: self._round.world.zone_score[side] for side in SIDES}

        if ending.kind == "baseDestroyed":
            # No assertion on the winner: a tick that took both bases ends the
            # match with nobody having won it.
            wire_ending = wire.base_destroyed(ending.winner)
        else:
            assert ending.reason is not None
            wire_ending = wire.round_complete(ending.winner, ending.reason)

        if ending.winner is not None:
            self.rounds_won[ending.winner] += 1

        self._last_round_result = wire.round_result(
            round_number=self.round_number,
            ending=wire_ending,
            bases=bases,
            zones=zones,
            zone_score=zone_score,
        )
        self._recorder.round_finished(ending=wire_ending, base_hp=self._base_hp)

        terminal = self._match_ending(ending)
        if terminal is not None:
            self._match_result = wire.match_result(
                ending=terminal,
                rounds_won=dict(self.rounds_won),
                bases=bases,
                last_round=self._last_round_result,
            )
            self._recorder.match_finished(
                ending=terminal,
                terminal_reason=_terminal_reason(terminal, wire_ending),
                rounds_won=self.rounds_won,
                base_hp=self._base_hp,
            )
            self.phase = "matchOver"
        else:
            self.phase = "roundOver"
        self._phase_ticks = 0

    def _match_ending(self, ending: RoundEnding) -> dict[str, Any] | None:
        """The match's terminal ending, or None if there are rounds left to play.

        The two profiles stop on **different counts**, and conflating them is a
        real bug rather than a nicety. Starter ends when somebody has *won*
        `rounds_to_win` rounds. A test profile ends once it has *played* that
        many — win, lose or draw. The demo is a mirror match on a symmetric map,
        so a drawn round is an ordinary outcome, and a demo that ended only on a
        win would quietly roll into a second round and never stop.
        """
        if ending.kind == "baseDestroyed":
            # Winner may be None: both bases fell on one tick, which is a draw
            # and still terminal.
            # Takes precedence over the round count, and over the test profile:
            # a base destroyed is a real terminal outcome even in a demo, and
            # reporting it as "the test finished" would hide the game's rule.
            return wire.match_ending_base_destroyed(ending.winner)

        if self.policy.test_profile:
            if self.round_number >= self.policy.rounds_to_win:
                # The demo played its rounds. Nobody has won a *match*.
                return wire.match_ending_test_complete(ending.winner)
            return None

        for side in SIDES:
            if self.rounds_won[side] >= self.policy.rounds_to_win:
                return wire.match_ending_rounds_won(side)

        return None

    def _next_round(self) -> None:
        self.round_number += 1
        self._round_state = _RoundState()
        self._round = None
        self.phase = "planning"
        self._phase_ticks = 0

    def abandon(self, winner: Side | None = None) -> None:
        """End the match without playing it out — both seats gone, or a forfeit."""
        if self.over:
            return
        bases = (
            wire.base_hp(self._round.world, self.map_config)
            if self._round is not None
            else {
                side: {"hp": self._base_hp[side], "maxHp": self.map_config.bases[side].max_hp}
                for side in SIDES
            }
        )
        ending = wire.match_ending_abandoned(winner)
        self._match_result = wire.match_result(
            ending=ending,
            rounds_won=dict(self.rounds_won),
            bases=bases,
            last_round=self._last_round_result
            or wire.round_result(
                round_number=self.round_number,
                ending=wire.round_complete(None, "timeUp"),
                bases=bases,
                zones=[],
                zone_score={side: 0.0 for side in SIDES},
            ),
        )
        self._recorder.match_finished(
            ending=ending,
            terminal_reason="abandoned",
            rounds_won=self.rounds_won,
            # Read off the live world when there is one: a match abandoned
            # mid-battle stopped where the battle had got to, and the carried
            # `_base_hp` is where the *previous* round left it.
            base_hp={side: float(bases[side]["hp"]) for side in SIDES},
        )
        self.phase = "matchOver"
        self._phase_ticks = 0

    # ------------------------------------------------------------ snapshots --

    def snapshot_for(self, side: Side) -> dict[str, Any]:
        """The whole of what one seat may know. The only way a view is built."""
        return wire.match_snapshot(
            run_id=self.run_id,
            match_id=self.external_match_id,
            you=side,
            round_number=self.round_number,
            rounds_won=dict(self.rounds_won),
            bases=self._bases_json(),
            phase=self._phase_json(side),
            test_profile=self.policy.test_profile,
        )

    def _bases_json(self) -> dict[Side, dict[str, float]]:
        if self._round is not None:
            return wire.base_hp(self._round.world, self.map_config)
        return {
            side: {"hp": self._base_hp[side], "maxHp": self.map_config.bases[side].max_hp} for side in SIDES
        }

    def _phase_json(self, side: Side) -> dict[str, Any]:
        if self.phase == "planning":
            return wire.planning_phase(
                plan=self._plan_json(side),
                locked=self._round_state.locked[side],
                deployment=self._deployment_preview(side),
                loadout=self._round_state.loadouts.get(side, []),
                energy=self.starting_energy,
            )

        if self.phase == "battle":
            assert self._round is not None
            return wire.battle_phase(self._battle_json(side))

        if self.phase == "roundOver":
            assert self._last_round_result is not None
            return wire.round_over_phase(self._last_round_result)

        assert self._match_result is not None
        return wire.match_over_phase(self._match_result)

    def _plan_json(self, side: Side) -> dict[str, Any]:
        """This seat's plan screen: the suggestion, or what it actually locked in.

        The roster, the mage cap and the opening energy come from the fixture
        either way — they are what the screen is *built* from, and they do not
        change when a player commits. What changes is `troops` and `spellSlots`,
        which after a lock-in are the player's own.

        This is the half of reclaim that is easy to miss, because nothing looks
        broken without it: a player who refreshes after locking in is shown the
        suggested default, concludes their lock-in vanished, and re-plans a
        round the server has already accepted their army for.
        """
        screen = fixtures.opening_plan_json(self.round_number, self.map_config)
        submitted = self._round_state.plans.get(side)
        if submitted is None:
            return screen
        return {**screen, **plan_to_json(submitted)}

    def _deployment_preview(self, side: Side) -> dict[str, Any] | None:
        """Your own troops, on the field, once you have locked in.

        A player who locks in first gets the board rather than a spinner. It
        carries **only your side**: the opponent may not even have locked yet,
        and a snapshot that included their deployment would leak their plan to
        anyone reading the network tab.

        Built by standing up a round of its own rather than by starting the real
        one early — starting the real one would begin the battle for the seat
        that has not locked in.
        """
        if not self._round_state.locked[side]:
            return None

        plan = self._round_state.plans[side]
        preview = AuthoritativeRound(
            round_number=self.round_number,
            map_config=self.map_config,
            plans={s: plan for s in SIDES},
            loadouts={side: self._round_state.loadouts.get(side, [])},
            base_hp=self._base_hp,
            seed=self.seed + self.round_number,
            sim_config=self.sim_config,
        )
        return wire.battle_snapshot(
            world=preview.world,
            map_config=self.map_config,
            you=side,
            energy=self.starting_energy,
            loadout=self._round_state.loadouts.get(side, []),
            casts=[],
            only_your_units=True,
        )

    def _battle_json(self, side: Side) -> dict[str, Any]:
        assert self._round is not None
        return wire.battle_snapshot(
            world=self._round.world,
            map_config=self.map_config,
            you=side,
            energy=self._round.energy_for(side),
            loadout=self._round.loadout_for(side),
            casts=self._round.casts(),
        )

    # --------------------------------------------------------- lobby report --

    def result_report(self) -> tuple[MatchResultStatus, list[str], dict[str, Any]] | None:
        """`(status, winnerLobbyUserIds, metadata)` for `reportMatchResult`.

        None until the match is over. The test profile reports `CANCELLED`,
        which the guide defines as leaving the match unrated — the honest
        status for a run that played one round of a best-of-five. The winner
        still travels in `metadata` so the run is legible in match history.
        """
        if not self.over or self._match_result is None:
            return None

        ending = self._match_result["ending"]
        kind = ending.get("kind")
        winner_side = ending.get("winner") or ending.get("roundWinner")

        winners: list[str] = []
        if winner_side in SIDES:
            seat = self.seat_for_side(cast("Side", winner_side))
            if seat.lobby_user_id:
                winners.append(seat.lobby_user_id)

        metadata: dict[str, Any] = {
            "gameMode": self.mode.key,
            "testProfile": self.policy.test_profile,
            "runId": self.run_id,
            "rounds": self.round_number,
            "ending": kind,
            # Carried into match history so "the base fell" outlives the result
            # screen (Ryan, 2026-09-13).
            "terminalReason": self.run_record.terminal_reason,
            "roundsWon": dict(self.rounds_won),
            "baseHp": self._match_result["baseHp"],
        }

        if kind == "abandoned":
            return "ABANDONED", winners, metadata
        if self.policy.test_profile:
            # Not COMPLETED: a single round is not a finished series, and a
            # rated result claiming one would move standings on a demo.
            metadata["roundWinner"] = winner_side
            return "CANCELLED", [], metadata
        return "COMPLETED", winners, metadata

    async def report_to_lobby(self) -> bool:
        """Tell the Lobby the match is over. Best effort, and safe to repeat.

        Retried rather than tracked: `reportMatchResult` is keyed by match id on
        the Lobby's side, so a second call after a timeout reports the same
        terminal state rather than a second one. `_reported` keeps this server
        from making pointless calls on a match already acknowledged — checked
        here rather than only described, which is what it was until JQ-310's
        retry test ran the finish path twice and watched two reports go out.
        Harmless on the Lobby's side, and still a call this server knew it did
        not need to make.
        """
        if self._reported:
            return True
        report = self.result_report()
        if report is None or self.lobby_client is None:
            return False
        status, winners, metadata = report
        ok = await self.lobby_client.report_match_result(
            self.external_match_id,
            status,
            winners,
            metadata,
        )
        if ok:
            self._reported = True
        else:
            log.warning("[match] %s could not report its result; will retry", self.external_match_id)
        return ok

    @property
    def reported(self) -> bool:
        return self._reported
