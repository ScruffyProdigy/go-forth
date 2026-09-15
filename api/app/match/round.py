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
from app.match.plan import SubmittedPlan, to_army_setup
from app.match.wire import CastCommand, CastRejection, LoadoutSpell, ResolvedCast
from app.sim.abilities import build_ability_catalog
from app.sim.ai.fixtures import sample_library
from app.sim.config import DEFAULT_SIM_CONFIG, SimConfig, max_ticks
from app.sim.context import create_tick_context
from app.sim.energy import resolve_school_energy_rules
from app.sim.events import BattleEvent
from app.sim.map import MapConfig
from app.sim.resonance import count_resonance
from app.sim.rng import create_rng
from app.sim.run_battle import step_battle
from app.sim.schools import resolve_side_multipliers
from app.sim.spells import SpellInjection, build_spell_catalog, schedule_injections
from app.sim.types import SIDES, Side, Vec2, opposing
from app.sim.units import build_unit_type_catalog
from app.sim.world import BattleSetup, World, create_world, is_alive

#: Seat energy regained per second of battle. Provisional (JQ-309's scheduling
#: note): fast enough that a 90-second round affords two or three casts, slow
#: enough that opening with everything is a real choice. JQ-297 replaces it.
ENERGY_PER_SECOND = 4.0

#: Seat energy ceiling. Provisional, and the reason one exists at all: without a
#: cap, a player who casts nothing for 90 seconds arrives at the next round able
#: to empty their whole loadout at once.
ENERGY_CAP = 120.0

#: Zone score that ends a round early. Provisional. A round that can only end on
#: the 90-second backstop has no way to reward holding both lanes, which is the
#: one thing the two-lane map exists to make interesting.
SCORE_THRESHOLD = 240.0


@dataclass(frozen=True, slots=True)
class RoundEnding:
    """Why the round stopped, and what that did to the match.

    `kind` is the distinction Ryan's 2026-09-13 correction turns on: a base
    destroyed ends the **match** on the spot; everything else ends a round. They
    are separate kinds rather than two reasons under one, so no renderer and no
    result report can treat base destruction as merely one round lost.
    """

    kind: Literal["roundComplete", "baseDestroyed"]
    #: The side that won. None only on a drawn `roundComplete`.
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
        loadouts: Mapping[Side, list[LoadoutSpell]],
        base_hp: Mapping[Side, float],
        seed: int,
        sim_config: SimConfig = DEFAULT_SIM_CONFIG,
        starting_energy: float = fixtures.STARTING_ENERGY,
    ) -> None:
        self.round_number = round_number
        self.map_config = map_config
        self.sim_config = sim_config
        self.seed = seed
        self._loadouts = {side: list(loadouts.get(side, [])) for side in SIDES}
        self._energy = {side: min(starting_energy, ENERGY_CAP) for side in SIDES}
        self._casts: list[ResolvedCast] = []
        self._ending: RoundEnding | None = None
        self._limit = max_ticks(sim_config)

        setup = BattleSetup(
            unit_types=fixtures.unit_types(),
            armies=[to_army_setup(plans[side], side) for side in SIDES],
            behavior=sample_library(),
            # Base damage persists across a match — nothing here refills a base
            # (JQ-187), so what the previous round left is what this one opens on.
            base_hp={side: base_hp[side] for side in SIDES},
            abilities=fixtures.abilities(),
            spells=fixtures.sim_spells(),
        )

        rng = create_rng(seed)
        self.world: World = create_world(map_config, setup, rng)
        self._spell_catalog = build_spell_catalog(setup.spells)

        # Resonance is established off the opening world and never recounted, so
        # a mage falling at tick 400 costs the mage and not the resonance the
        # side brought (Ryan, 2026-09-15). Same order as `run_battle`: nothing
        # between `create_world` and here touches the rng.
        established = count_resonance(self.world)
        self._ctx = create_tick_context(
            config=sim_config,
            map_config=map_config,
            multipliers=resolve_side_multipliers([], established),
            rng=rng,
            resonance=established,
            unit_types=build_unit_type_catalog(setup.unit_types),
            energy_rules=resolve_school_energy_rules([]),
            abilities=build_ability_catalog(setup.abilities),
            spells=self._spell_catalog,
        )

    # ------------------------------------------------------------- reading --

    @property
    def ending(self) -> RoundEnding | None:
        """None while the round is still running."""
        return self._ending

    @property
    def over(self) -> bool:
        return self._ending is not None

    def energy_for(self, side: Side) -> float:
        return self._energy[side]

    def loadout_for(self, side: Side) -> list[LoadoutSpell]:
        return list(self._loadouts[side])

    def casts(self) -> list[ResolvedCast]:
        """Accepted casts, both sides, in the order the server took them."""
        return list(self._casts)

    def base_hp(self) -> dict[Side, float]:
        return {side: self.world.bases[side].hp for side in SIDES}

    # ------------------------------------------------------------- stepping --

    def step(self) -> tuple[BattleEvent, ...]:
        """Advance one tick. A no-op once the round is over."""
        if self._ending is not None:
            return ()

        events = tuple(step_battle(self.world, self._ctx))

        # Seat energy accrues on the same clock as the battle, so a round that
        # is paused is not a round in which everyone quietly gets rich.
        gain = ENERGY_PER_SECOND * self._ctx.seconds_per_tick
        for side in SIDES:
            self._energy[side] = min(ENERGY_CAP, self._energy[side] + gain)

        self._ending = self._decide_ending()
        return events

    def _decide_ending(self) -> RoundEnding | None:
        """What, if anything, has ended — checked in precedence order.

        A base falling is settled before anything else that happened on the same
        tick, matching `run_battle`. It has to be: a tick in which a base falls
        *and* a side is wiped out is a match lost, not a round won.
        """
        for side in SIDES:
            if self.world.bases[side].hp <= 0:
                return RoundEnding(kind="baseDestroyed", winner=opposing(side))

        living = {side: any(u.side == side and is_alive(u) for u in self.world.units) for side in SIDES}
        if not all(living.values()):
            survivors = [side for side in SIDES if living[side]]
            winner = survivors[0] if len(survivors) == 1 else None
            return RoundEnding(kind="roundComplete", winner=winner, reason="annihilation")

        leader = self._score_leader()
        if leader is not None and self.world.zone_score[leader] >= SCORE_THRESHOLD:
            return RoundEnding(kind="roundComplete", winner=leader, reason="zoneControl")

        if self.world.tick >= self._limit:
            return RoundEnding(kind="roundComplete", winner=self._score_leader(), reason="timeUp")

        return None

    def _score_leader(self) -> Side | None:
        """Whoever is ahead on zone score, or None on an exact tie.

        An exact tie is a draw rather than a coin flip. It is reachable — the
        demo is a mirror match — and a round awarded to whichever side the code
        happened to check first would be the least explicable loss in the game.
        """
        north, south = (self.world.zone_score[side] for side in SIDES)
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

        if self._energy[side] < spell.cost:
            return CastOutcome(False, command.command_id, "notEnoughEnergy")

        # Scheduled on the next tick, never the tick the client named. The sim
        # refuses an injection at a tick that has already run, and honouring a
        # future one would hand a client a delayed cast of its own choosing.
        target_tick = self.world.tick + 1

        injection = SpellInjection(
            tick=target_tick,
            spell_id=spell.spell_id,
            location=command.at,
            # Filled in from the seat, never read off the wire: a client that
            # could name its own side could cast as its opponent.
            side=side,
        )
        self.world.pending_spells = schedule_injections(
            [*self.world.pending_spells, injection], self._spell_catalog
        )

        self._energy[side] -= spell.cost
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
