"""One authoritative round: the sim, stepped by the server, under seat commands.

The sim ships `run_battle`, which runs a battle to its end and hands back every
tick at once. That is the right shape for the determinism harness and the wrong
one for a live match — a round the server has already finished cannot accept a
cast at tick 400. So this drives `step_battle` a tick at a time and owns the
three things a live round has that a batch run does not:

* **Seat energy.** Unit gauges are the sim's (§4.4). The pool a *player* spends
  on spells (§4.7) is the match layer's, because the sim has no concept of a
  seat. Tracked here, spent here, and sent to one seat only — the opponent's
  energy is hidden information, and knowing it tells you which spell is coming.
* **Casts arriving mid-battle.** A cast becomes a `SpellInjection` scheduled on
  the *next* tick, never the tick the client named: a client-chosen tick is
  either in the past, which cannot be honoured, or in the future, which is a
  free delayed cast nobody else can see coming.
* **When the round stops**, and whether that ended the round or the match.

Determinism is preserved rather than assumed: the round is stepped, not
replayed, so the same seed with the same casts at the same ticks produces the
same battle. Casts are the only nondeterministic input, and they enter through
a sorted queue for exactly that reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.match import fixtures
from app.match.plan import SubmittedPlan, loadout_spells, to_army_setup
from app.match.wire import CastCommand, CastRejection, LoadoutSpell, ResolvedCast
from app.sim.ai.fixtures import sample_library
from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig
from app.sim.events import BattleEvent
from app.sim.loadout import LoadoutSnapshot
from app.sim.map import MapConfig
from app.sim.run_battle import BattleResult, create_runner
from app.sim.spells import SpellInjection
from app.sim.types import SIDES, Side, Vec2, opposing
from app.sim.world import BattleSetup, World, is_alive

#: Seat energy regained per second of battle. Provisional (JQ-309's scheduling
#: note): fast enough that a 90-second round affords two or three casts, slow
#: enough that opening with everything is a real choice. The cadence is
#: JQ-292/187's to settle; JQ-297 settled only what a *spell* costs.
ENERGY_PER_SECOND = 4.0

#: Seat energy ceiling. Provisional, and the reason one exists at all: without a
#: cap, a player who casts nothing for 90 seconds arrives at the next round able
#: to empty their whole loadout at once.
ENERGY_CAP = 120.0

#: Zone score that ends a round early. Provisional. A round that can only end on
#: the 90-second backstop has no way to reward holding both lanes, which is the
#: one thing the two-lane map exists to make interesting.
SCORE_THRESHOLD = 240.0


@dataclass(slots=True)
class SeatEnergy:
    """One seat's spell pool, kept as two ledgers rather than a running total.

    `current` is derived from `start + generated - spent` instead of being a
    field the two sides adjust, so the books cannot come apart. That is not
    fastidiousness: at 4 energy a second on a 20 Hz tick the increment is 0.2,
    which is not representable in binary, and a balance mutated 1800 times over
    a single round drifts away from its own history. Measured on the previous
    accumulating version: off by 7e-15 after ten ticks and one spend — enough to
    make a cast at exactly the cost boundary land differently depending on how
    long the round had been going, which is the kind of bug nobody reproduces.

    The same hazard `sim/config.to_ticks` calls out for durations ("subtracting
    0.05 twenty times does not reliably land on zero"), answered the same way.
    """

    start: float
    cap: float
    generated: float = 0.0
    spent: float = 0.0

    @property
    def current(self) -> float:
        return self.start + self.generated - self.spent

    def accrue(self, gain: float) -> None:
        """Adds a tick's worth, clipped at the cap."""
        self.generated += min(gain, max(0.0, self.cap - self.current))

    def can_afford(self, cost: float) -> bool:
        return self.current >= cost

    def spend(self, cost: float) -> None:
        self.spent += cost


@dataclass(frozen=True, slots=True)
class RoundEnding:
    """Why the round stopped, and what that did to the match.

    `kind` is the distinction Ryan's 2026-09-13 correction turns on: a base
    destroyed ends the **match** on the spot; everything else ends a round. They
    are separate kinds rather than two reasons under one, so no renderer and no
    result report can treat base destruction as merely one round lost.
    """

    kind: Literal["roundComplete", "baseDestroyed"]
    #: The side that won. None on a drawn `roundComplete`, and on a
    #: `baseDestroyed` where *both* bases fell on the same tick — a draw that is
    #: still a match ending rather than a round one.
    winner: Side | None
    #: Present on `roundComplete` only.
    reason: Literal["zoneControl", "annihilation", "timeUp"] | None = None


@dataclass(frozen=True, slots=True)
class CastOutcome:
    accepted: bool
    command_id: str
    rejection: CastRejection | None = None


class AuthoritativeRound:
    """A round in progress. Nothing here reads a clock — the session ticks it."""

    def __init__(
        self,
        *,
        round_number: int,
        map_config: MapConfig,
        plans: Mapping[Side, SubmittedPlan],
        #: One per seat, frozen at lock-in. The round reads spells from here and
        #: from nowhere else — see `plan.resolve_snapshot`.
        snapshots: Mapping[Side, LoadoutSnapshot],
        base_hp: Mapping[Side, float],
        seed: int,
        sim_config: SimConfig = DEFAULT_SIM_CONFIG,
        starting_energy: float = fixtures.STARTING_ENERGY,
    ) -> None:
        self.round_number = round_number
        self.map_config = map_config
        self.sim_config = sim_config
        self.seed = seed
        self._snapshots = dict(snapshots)
        self._loadouts = {side: loadout_spells(snapshots[side]) for side in SIDES}
        self._energy = {
            side: SeatEnergy(start=min(starting_energy, ENERGY_CAP), cap=ENERGY_CAP) for side in SIDES
        }
        self._casts: list[ResolvedCast] = []
        self._ending: RoundEnding | None = None

        setup = BattleSetup(
            unit_types=fixtures.unit_types(),
            armies=[to_army_setup(plans[side], side) for side in SIDES],
            behavior=sample_library(),
            # Base damage persists across a match — nothing here refills a base
            # (JQ-187), so what the previous round left is what this one opens on.
            base_hp={side: base_hp[side] for side in SIDES},
            abilities=fixtures.abilities(),
            # Built from the two snapshots rather than from a catalogue. This is
            # the "battle execution consumes the authoritative snapshot" rule in
            # JQ-297 made structural: the effects the sim will fire are the ones
            # the plan screen showed, and there is no other copy of them to
            # drift from. Ids are namespaced per side, since both seats can
            # equip one spell and resolve it to different numbers.
            spells=[spell for side in SIDES for spell in snapshots[side].sim_spells()],
        )

        # Built by the sim rather than assembled here. The rng, the resonance
        # count, the multipliers, the catalogs and the tick context are all
        # `run_battle`'s opening sequence, and a second copy of it in this file
        # was a copy that could drift — silently, since nothing compares the
        # two. It already had: the copy left `cast_policy` at its default, so a
        # unit in a live round decided its casts by a different rule from the
        # same unit in a headless replay of the same battle.
        self._runner = create_runner(map_config, [], setup, seed, sim_config)
        self._limit = self._runner.limit

    # ------------------------------------------------------------- reading --

    @property
    def world(self) -> World:
        """The live world. Owned by the runner; exposed because everything that
        projects a snapshot reads it."""
        return self._runner.world

    @property
    def ending(self) -> RoundEnding | None:
        """None while the round is still running."""
        return self._ending

    @property
    def over(self) -> bool:
        return self._ending is not None

    def energy_for(self, side: Side) -> float:
        return self._energy[side].current

    def loadout_for(self, side: Side) -> list[LoadoutSpell]:
        return list(self._loadouts[side])

    def casts(self) -> list[ResolvedCast]:
        """Accepted casts, both sides, in the order the server took them."""
        return list(self._casts)

    def base_hp(self) -> dict[Side, float]:
        return {side: self.world.bases[side].hp for side in SIDES}

    def result(self) -> BattleResult:
        """The battle so far, in the sim's own result shape.

        What `run_battle` would have returned, so a played round can be
        serialised, digested or diffed with the same tools as a headless one —
        which is what the cross-process determinism check needs, and what a
        replay will need after it.
        """
        return self._runner.result()

    # ------------------------------------------------------------- stepping --

    def step(self) -> tuple[BattleEvent, ...]:
        """Advance one tick. A no-op once the round is over."""
        if self._ending is not None:
            return ()

        events = self._runner.step()

        # Seat energy accrues on the same clock as the battle, so a round that
        # is paused is not a round in which everyone quietly gets rich.
        gain = ENERGY_PER_SECOND * self._runner.ctx.seconds_per_tick
        for side in SIDES:
            self._energy[side].accrue(gain)

        self._ending = self._decide_ending()
        return events

    def _decide_ending(self) -> RoundEnding | None:
        """What, if anything, has ended — checked in precedence order.

        A base falling is settled before anything else that happened on the same
        tick, matching `run_battle`. It has to be: a tick in which a base falls
        *and* a side is wiped out is a match lost, not a round won.

        The order is the policy, so it is written out rather than left to be
        read off the branches:

        1. **Both bases at zero** — a draw, still under `baseDestroyed`. Two
           spells can land on one tick and nothing serialises them against each
           other, so this is reachable rather than theoretical (Ryan,
           2026-09-15). Checked before the single-base case because a loop that
           walked `SIDES` and returned on the first would silently award the
           match to south, which is an accident of iteration order rather than
           a rule anyone chose.
        2. **One base at zero** — that side loses the match on the spot, beating
           a score threshold crossed on the same tick.
        3. **A side wiped out.**
        4. **The score threshold**, then the backstop. Both are settled by
           `_outcome_on_score`, which breaks an exact tie on remaining base HP.
        """
        fallen = tuple(side for side in SIDES if self.world.bases[side].hp <= 0)
        if len(fallen) == len(SIDES):
            return RoundEnding(kind="baseDestroyed", winner=None)
        if fallen:
            return RoundEnding(kind="baseDestroyed", winner=opposing(fallen[0]))

        living = {side: any(u.side == side and is_alive(u) for u in self.world.units) for side in SIDES}
        if not all(living.values()):
            survivors = [side for side in SIDES if living[side]]
            winner = survivors[0] if len(survivors) == 1 else None
            return RoundEnding(kind="roundComplete", winner=winner, reason="annihilation")

        leader = self._score_leader()
        if leader is not None and self.world.zone_score[leader] >= SCORE_THRESHOLD:
            return RoundEnding(kind="roundComplete", winner=leader, reason="zoneControl")

        if self.world.tick >= self._limit:
            return RoundEnding(kind="roundComplete", winner=self._outcome_on_score(), reason="timeUp")

        return None

    def _score_leader(self) -> Side | None:
        """Whoever is ahead on zone score, or None on an exact tie."""
        north, south = (self.world.zone_score[side] for side in SIDES)
        if north > south:
            return "north"
        if south > north:
            return "south"
        return None

    def _outcome_on_score(self) -> Side | None:
        """The backstop's winner: zone score, then remaining base HP, then a draw.

        An exact score tie is reachable — the demo is a mirror match — and Ryan
        settled it on 2026-09-15: break it on the base each side has left. A
        side that spent the round chipping the enemy base has done something a
        pure zone comparison throws away, and the number is already carried
        across rounds, so nothing new has to be tracked to read it.

        Level on both is a genuine draw and is reported as one. Awarding it to
        whichever side the code checked first would be the least explicable loss
        in the game.
        """
        leader = self._score_leader()
        if leader is not None:
            return leader

        north, south = (self.world.bases[side].hp for side in SIDES)
        if north > south:
            return "north"
        if south > north:
            return "south"
        return None

    # ---------------------------------------------------------- casting --

    def cast(self, side: Side, command: CastCommand) -> CastOutcome:
        """Take a seat's cast, or refuse it. **Never spends on a refusal.**

        Every branch below returns before touching `self._energy`, which is the
        property worth stating: a rejected cast that had already charged the
        player would be indistinguishable, from the seat, from a cast that
        landed and did nothing.
        """
        if self._ending is not None:
            return CastOutcome(False, command.command_id, "roundOver")

        spell = next((entry for entry in self._loadouts[side] if entry.spell_id == command.spell_id), None)
        if spell is None:
            # Covers both "not in this round's loadout" and "not a spell at all".
            # One answer for both: which of the two it was is not information a
            # client needs, and distinguishing them enumerates the catalogue.
            return CastOutcome(False, command.command_id, "notEquipped")

        if not self._on_map(command.at):
            return CastOutcome(False, command.command_id, "outOfBounds")

        if not self._energy[side].can_afford(spell.cost):
            return CastOutcome(False, command.command_id, "notEnoughEnergy")

        # Scheduled on the next tick, never the tick the client named. The sim
        # refuses an injection at a tick that has already run, and honouring a
        # future one would hand a client a delayed cast of its own choosing.
        target_tick = self.world.tick + 1

        injection = SpellInjection(
            tick=target_tick,
            # The seat's own resolved copy, never the definition id the client
            # named. Both seats' Fireballs are in one catalog under different
            # ids, and casting the definition id would either miss the catalog
            # or — worse, if one day it did not — fire the opponent's numbers.
            spell_id=self._snapshots[side].sim_spell_id(spell.spell_id),
            location=command.at,
            # Filled in from the seat, never read off the wire: a client that
            # could name its own side could cast as its opponent.
            side=side,
        )
        # Inserted into the already-sorted queue rather than re-sorting it, so a
        # cast taken live lands exactly where the opening `schedule_injections`
        # would have put it. Two spells on one tick must not resolve differently
        # depending on whether they were scheduled up front or arrived live.
        self._runner.inject(injection)

        self._energy[side].spend(spell.cost)
        self._casts.append(
            ResolvedCast(
                command_id=command.command_id,
                spell_id=spell.spell_id,
                spell_name=spell.name,
                cast_by=side,
                at=command.at,
                tick=target_tick,
            )
        )
        return CastOutcome(True, command.command_id)

    def _on_map(self, at: Vec2) -> bool:
        config = self.map_config
        return 0 <= at.x <= config.size_width and 0 <= at.y <= config.size_height


def zone_score_json(world: World) -> dict[str, Any]:
    return {side: world.zone_score[side] for side in SIDES}
