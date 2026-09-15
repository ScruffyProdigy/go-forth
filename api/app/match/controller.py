"""The authoritative round: planning, reveal, battle, and the ending.

This is the server's whole opinion about a match. It owns the phase, it owns
validation, and it owns the energy — a client renders what it is told and asks
for things it may not get. Nothing here talks to a socket: JQ-309 wraps it in a
Lobby contract and a realtime session, and keeping the state machine
transport-free is what lets this ticket be tested without one.

## Why the battle is stepped rather than run

`run_battle` runs to completion and hands back the whole thing, which is what a
headless demo wants and exactly what a live round cannot use: a cast arrives
*during* the battle, and a function that has already returned cannot be handed
one. So the controller drives `BattleRunner` a tick at a time and accepts casts
between ticks. That is also what makes "the battle continues during disconnect"
true by construction rather than by promise — `advance` is driven by the
server's clock and never consults a client.

## Hidden plans

`plan_for` takes a viewer and refuses to answer about the other side until both
plans are locked. Simultaneity is the point of the plan phase (§6.1): a plan you
can see is a plan you can answer, and the round stops being the guess it exists
to be. Enforced here rather than in a serialiser, because the serialiser is
JQ-309's and this rule is not negotiable at that layer.

## The three edge policies (Ryan, 2026-09-15)

* A missed plan is **auto-locked to the suggested legal default**, not forfeit.
  The outcome records that it was server-supplied.
* A score tie at the backstop is broken on **remaining base HP**, then reported
  as a draw. See `outcome.py`.
* Two bases falling on one tick is a **draw**, under its own reason. See
  `outcome.py`.

## After the end

A terminated match accepts nothing further — no plan, no cast, no tick. There is
no second round and no later availability to fabricate; a fresh run is a fresh
`MatchController`, which opens at full base HP because it is a new match rather
than a healing round transition. Zone score is likewise never inherited: a world
opens at zero and nothing here carries it forward.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, NoReturn

from app.match.energy import SpellEnergy, new_pool
from app.match.events import MatchEvent, MatchEventType
from app.match.outcome import RoundOutcome, terminal_outcome, time_up_outcome
from app.match.packages import MagePackage, PackageCatalog, validate_catalog
from app.match.plan import Plan, PlanRejected, suggested_plan, validate_plan
from app.match.profile import MatchProfile, validate_profile
from app.sim import (
    SIDES,
    ArmySetup,
    BattleRunner,
    BattleSetup,
    MapConfig,
    RosterEntry,
    SchoolConfig,
    Side,
    SpellInjection,
    TroopSetup,
    Vec2,
    create_runner,
    seconds_per_tick,
)

MatchPhase = Literal["planning", "battle", "complete"]

#: How a plan came to be locked. `default` is the missed-plan path, and it is
#: reported rather than hidden: JQ-308 asks for the policy to be explicit, and a
#: demo where one player never planned should say so.
LockSource = Literal["player", "default"]

#: Why a cast was turned away. Like `PlanRejection`, these codes are the
#: contract. A rejection never spends energy — that is the ticket's wording and
#: every branch below returns before `spend`.
CastRejection = Literal[
    "matchOver",
    "wrongPhase",
    "notInLoadout",
    "offMap",
    "unaffordable",
    "stale",
]


class CastRejected(Exception):
    """A cast the server refused. Nothing was spent."""

    def __init__(self, reason: CastRejection, detail: str) -> None:
        super().__init__(detail)
        self.reason: CastRejection = reason
        self.detail = detail


@dataclass(frozen=True)
class LockedPlan:
    plan: Plan
    source: LockSource


def _army(side: Side, plan: Plan, catalog: PackageCatalog) -> ArmySetup:
    """Turns a validated plan into the roster the sim builds a world from.

    One troop per chosen package, carrying that package's fixed entourage. The
    plan supplies the order and nothing else — no position, no stance, no
    facing, which is the constraint `orders.py` exists to hold.
    """
    by_id = catalog.by_id
    return ArmySetup(
        side=side,
        troops=[
            TroopSetup(
                order=troop.order,
                mages=[RosterEntry(by_id[troop.package_id].mage_type_id)],
                summons=list(by_id[troop.package_id].entourage),
            )
            for troop in plan.troops
        ],
    )


@dataclass
class MatchController:
    """One match, from the opening plan phase to its terminal outcome."""

    profile: MatchProfile
    catalog: PackageCatalog
    map_config: MapConfig
    seed: int
    school_configs: Sequence[SchoolConfig] = ()

    phase: MatchPhase = "planning"
    #: Seconds of planning that have elapsed. Advanced by the caller's clock,
    #: because this class has none of its own — the sim's purity rule does not
    #: bind here, but a state machine that reads a wall clock is untestable.
    planning_elapsed: float = 0.0
    runner: BattleRunner | None = None
    outcome: RoundOutcome | None = None
    events: list[MatchEvent] = field(default_factory=list)

    _locked: dict[Side, LockedPlan] = field(default_factory=dict)
    _energy: dict[Side, SpellEnergy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_profile(self.profile)
        # Checked once, here, so that every later rejection is about the plan
        # rather than about the menu it was chosen from.
        validate_catalog(self.catalog, expected=self.profile.packages_available)
        self._emit("phaseChanged", phase="planning", profile=self.profile.label)

    # --- reporting ------------------------------------------------------

    def _emit(self, type_: MatchEventType, **data: object) -> None:
        tick = self.runner.world.tick if self.runner is not None else 0
        self.events.append(MatchEvent(type=type_, tick=tick, data=dict(data)))

    @property
    def available_packages(self) -> tuple[MagePackage, ...]:
        return self.catalog.packages

    @property
    def revealed(self) -> bool:
        """Plans become visible to both sides once both are locked, never before."""
        return len(self._locked) == len(SIDES)

    def suggested(self, side: Side) -> Plan:
        """The legal default this side's plan screen opens on."""
        return suggested_plan(side, self.catalog, self.map_config, self.profile)

    def locked(self, side: Side) -> bool:
        return side in self._locked

    def lock_source(self, side: Side) -> LockSource | None:
        entry = self._locked.get(side)
        return None if entry is None else entry.source

    def plan_for(self, viewer: Side, subject: Side) -> Plan | None:
        """What `viewer` is allowed to know about `subject`'s plan.

        Your own plan the moment you lock it; the opponent's only after the
        reveal. Returning None rather than raising, because "not yet" is the
        ordinary state of this question for most of the plan phase.
        """
        entry = self._locked.get(subject)
        if entry is None:
            return None
        if viewer != subject and not self.revealed:
            return None
        return entry.plan

    def energy(self, side: Side) -> SpellEnergy | None:
        return self._energy.get(side)

    # --- planning -------------------------------------------------------

    def submit_plan(self, side: Side, plan: Plan) -> None:
        """Validates and locks a side's plan. Raises `PlanRejected` if illegal.

        Submission and lock are one act. There is no ordinary planning
        countdown (the ticket rules one out), so an unlocked plan held on the
        server would be a draft nothing ever advances past.
        """
        if self.phase == "complete":
            raise PlanRejected("wrongPhase", "the match is over")
        if self.phase != "planning":
            raise PlanRejected("wrongPhase", f"plans are not accepted during {self.phase}")
        if side in self._locked:
            raise PlanRejected("alreadyLocked", f"{side} has already locked a plan")

        validate_plan(plan, self.catalog, self.map_config, self.profile)
        self._lock(side, plan, "player")

    def _lock(self, side: Side, plan: Plan, source: LockSource) -> None:
        self._locked[side] = LockedPlan(plan=plan, source=source)
        self._emit("planLocked", side=side, source=source)
        if self.revealed:
            self._emit(
                "plansRevealed",
                plans={s: self._locked[s].plan for s in SIDES},
            )
            self._start_battle()

    def advance_planning(self, seconds: float) -> None:
        """Runs the planning clock forward.

        Only the backstop reads it. It is deliberately generous and is not shown
        as a countdown: what it protects against is a player who never answers,
        not a player who is slow.
        """
        if self.phase != "planning":
            return

        self.planning_elapsed += seconds
        if self.planning_elapsed < self.profile.plan_backstop_seconds:
            return

        # Auto-lock in a fixed order rather than by iterating the dict of who is
        # missing, so that a double no-show produces the same match every time.
        for side in SIDES:
            if side not in self._locked:
                self._lock(side, self.suggested(side), "default")

    # --- the battle -----------------------------------------------------

    def _start_battle(self) -> None:
        setup = BattleSetup(
            unit_types=list(self.catalog.unit_types),
            armies=[_army(side, self._locked[side].plan, self.catalog) for side in SIDES],
            base_hp=dict(self.profile.base_hp),
            spells=list(self.catalog.spells),
        )
        self.runner = create_runner(
            self.map_config,
            self.school_configs,
            setup,
            self.seed,
            self.profile.sim,
        )
        per_tick = self.profile.spell_energy_per_second * seconds_per_tick(self.profile.sim)
        self._energy = {
            side: new_pool(
                start=self.profile.spell_energy_start,
                per_tick=per_tick,
                cap=self.profile.spell_energy_cap,
            )
            for side in SIDES
        }
        self.phase = "battle"
        self._emit("phaseChanged", phase="battle", profile=self.profile.label)

    @property
    def tick(self) -> int:
        return 0 if self.runner is None else self.runner.world.tick

    def advance(self, ticks: int = 1) -> None:
        """Runs the battle forward on the server's clock.

        Consults no client, which is what "the battle continues during
        disconnect" means: a side that has gone away stops casting and its
        troops fight on under the orders it already gave.
        """
        for _ in range(ticks):
            if self.phase != "battle" or self.runner is None:
                return
            self._advance_one()

    def _advance_one(self) -> None:
        runner = self.runner
        assert runner is not None  # guarded by the caller

        for side in SIDES:
            self._energy[side].tick()
        runner.step()

        ending = terminal_outcome(runner.world, self.profile)
        if ending is None and runner.finished:
            ending = time_up_outcome(runner.world, self.profile)
        if ending is not None:
            self._finish(ending)

    def run_round(self) -> RoundOutcome:
        """Advances until the round ends, for a caller with nothing to inject.

        Refuses a match still in planning rather than returning an ending that
        does not exist: there is no battle to advance, and silently doing
        nothing would look like an instant draw.
        """
        if self.phase == "planning":
            raise ValueError("the round has not started; both sides must lock a plan first")
        if self.outcome is None and self.phase == "complete":  # pragma: no cover - unreachable
            raise ValueError("the match is complete but recorded no outcome")

        while self.phase == "battle":
            self.advance()

        assert self.outcome is not None
        return self.outcome

    def _finish(self, ending: RoundOutcome) -> None:
        self.outcome = ending
        self.phase = "complete"
        self._emit(
            "roundEnded",
            reason=ending.reason,
            winner=ending.winner,
            decided_by=ending.decided_by,
            base_hp=dict(ending.base_hp),
            zone_score=dict(ending.zone_score),
            profile=ending.profile_label,
        )
        # A single-round profile has no round that is not also the match, but
        # the two events stay distinct: JQ-187 adds rounds that end without the
        # match ending, and a client that learned to read one event for both
        # would have to be retaught.
        self._emit(
            "matchEnded",
            reason=ending.reason,
            winner=ending.winner,
            ends_match=ending.ends_match,
            destroyed_bases=list(ending.destroyed_bases),
            base_hp=dict(ending.base_hp),
            profile=ending.profile_label,
        )
        self._emit("phaseChanged", phase="complete", profile=ending.profile_label)

    # --- casting --------------------------------------------------------

    def loadout(self, side: Side) -> tuple[str, ...]:
        """The spells this side locked in. Empty before it locks a plan."""
        entry = self._locked.get(side)
        return () if entry is None else entry.plan.spell_ids

    def cost_of(self, spell_id: str) -> float:
        return self.catalog.cost_of(spell_id, self.profile.default_spell_cost)

    def cast_spell(
        self, side: Side, spell_id: str, location: Vec2, at_tick: int | None = None
    ) -> SpellInjection:
        """Accepts a cast, or raises `CastRejected` having spent nothing.

        `at_tick` is what the *client* believes the tick is. It is checked
        against the server's rather than trusted, which is what makes a stale
        cast — one composed before a lagging client caught up — a rejection
        instead of a spell landing somewhere the player never meant. Omitting it
        means "now", which is the server-driven path.
        """
        if self.phase == "complete":
            self._reject(side, spell_id, "matchOver", "the match is over")
        if self.phase != "battle" or self.runner is None:
            self._reject(side, spell_id, "wrongPhase", f"spells are not cast during {self.phase}")

        runner = self.runner
        assert runner is not None  # narrowed by the phase check above
        world_tick = runner.world.tick

        if at_tick is not None and at_tick != world_tick:
            self._reject(
                side,
                spell_id,
                "stale",
                f"cast was composed at tick {at_tick}, and the battle is at {world_tick}",
            )

        if spell_id not in self.loadout(side):
            # Covers an unknown spell and a real one nobody locked in. Both are
            # the same answer to the player: not yours to cast.
            self._reject(side, spell_id, "notInLoadout", f"{spell_id} is not in {side}'s round loadout")

        if not self._on_map(location):
            self._reject(side, spell_id, "offMap", f"{location} is off the map")

        cost = self.cost_of(spell_id)
        pool = self._energy[side]
        if not pool.can_afford(cost):
            self._reject(
                side,
                spell_id,
                "unaffordable",
                f"{spell_id} costs {cost} and {side} holds {pool.current}",
            )

        # The earliest tick a cast can land on. The spells phase for the current
        # tick has already run, so landing it on `world_tick` would be swept up
        # by the next one and silently arrive late.
        injection = SpellInjection(tick=world_tick + 1, spell_id=spell_id, location=location, side=side)
        runner.inject(injection)
        pool.spend(cost)
        self._emit("spellAccepted", side=side, spell_id=spell_id, cost=cost, lands_on=injection.tick)
        return injection

    def _reject(self, side: Side, spell_id: str, reason: CastRejection, detail: str) -> NoReturn:
        """Records the refusal and raises it.

        Every rejection funnels through here so the event is emitted once,
        whichever entry point the caller used — and so that "a rejection never
        spends energy" reads as a single `raise` reached before any `spend`,
        rather than as a property of six separate branches that each have to
        remember.
        """
        self._emit("spellRejected", side=side, spell_id=spell_id, reason=reason)
        raise CastRejected(reason, detail)

    def try_cast(
        self, side: Side, spell_id: str, location: Vec2, at_tick: int | None = None
    ) -> CastRejection | None:
        """`cast_spell`, reporting the rejection rather than raising it.

        What a session loop wants: a refused cast is an ordinary event in a
        realtime round, not an exceptional one.
        """
        try:
            self.cast_spell(side, spell_id, location, at_tick)
        except CastRejected as rejected:
            return rejected.reason
        return None

    def _on_map(self, location: Vec2) -> bool:
        config = self.map_config
        return 0 <= location.x <= config.size_width and 0 <= location.y <= config.size_height


def new_match(
    *,
    profile: MatchProfile,
    catalog: PackageCatalog,
    map_config: MapConfig,
    seed: int,
    school_configs: Sequence[SchoolConfig] = (),
) -> MatchController:
    """A fresh match, at full base HP and zero score.

    The only way to start one. JQ-308 is explicit that a fresh demo run
    initializes a new match rather than healing its way into one, so there is
    deliberately no `reset` on the controller to reach for.
    """
    return MatchController(
        profile=profile,
        catalog=catalog,
        map_config=map_config,
        seed=seed,
        school_configs=school_configs,
    )


def base_hp_snapshot(controller: MatchController) -> Mapping[Side, float]:
    """What the bases have left right now.

    JQ-308 asks for base HP to be carried in controller inputs *and* outputs.
    `MatchProfile.base_hp` is the input; this is the output, readable mid-battle
    rather than only from a finished round, so JQ-187's reset matrix has
    something to carry without waiting for a terminal outcome.
    """
    if controller.runner is None:
        config = controller.map_config
        return {side: controller.profile.base_hp.get(side, config.bases[side].max_hp) for side in SIDES}
    return {side: controller.runner.world.bases[side].hp for side in SIDES}
