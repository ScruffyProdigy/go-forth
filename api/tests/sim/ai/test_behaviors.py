"""The behaviours themselves, driven through the real tick phases.

Everything here runs `TICK_PHASES` on a hand-placed field rather than calling the
evaluator directly, because most of what this ticket delivers is a *collaboration*
between phases: the decision picks a verb, movement decides how fast to walk it,
target acquisition decides whether to swing during it. A unit-level test of any
one of those would pass with the other two wired up wrongly.

JQ-331 assembles these into its scenario harness. They are kept here, in the
shape the rest of the suite uses, so that the behaviour and the pin on it live
together — a scenario runner that also owned the assertions would make a change
to positioning look like a change to the inspector.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from app.sim.ai.attach import attach_behavior
from app.sim.ai.candidates import generate_candidates
from app.sim.ai.capabilities import capabilities_of
from app.sim.ai.fixtures import sample_library
from app.sim.ai.intent import (
    PURSUIT_ENDED_REASONS,
    REASONS,
    SCREENING,
    WITHDRAW_SPEED_SCALE,
    ActionKind,
    Commitment,
    Intent,
    UnitAi,
)
from app.sim.ai.observe import observe
from app.sim.ai.positioning import useful_range
from app.sim.ai.profiles import BehaviorLibrary, CreatureProfile
from app.sim.ai.pursuit import PURSUIT_LEASH
from app.sim.config import DEFAULT_SIM_CONFIG
from app.sim.context import create_tick_context
from app.sim.geometry import distance
from app.sim.map import TWO_LANE_MAP
from app.sim.orders import Order, hold
from app.sim.phases import TICK_PHASES
from app.sim.rng import create_rng
from app.sim.schools import resolve_side_multipliers
from app.sim.types import Vec2
from app.sim.units import UnitType, build_unit_type_catalog
from app.sim.world import Unit, World
from tests.sim.ai.helpers import SECONDS_PER_TICK, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND, RAM, SPRITE, WISP

#: A post in the East lane's hotspot, and a troop ordered to hold it.
#:
#: **Not the default.** `helpers.make_world` puts a troop under Push, whose
#: station is the enemy base most of a map away — so a unit "returning to its
#: station" marches *forward*, and a test that measures drift from a starting
#: point measures the push instead. Every scenario here about leaving a post and
#: coming back to it has to be staged under an order that has a post.
HOLD_EAST = {"north-t0": hold("E"), "south-t0": hold("E")}
POST = Vec2(295.0, 284.5)

HERE = POST

#: Rooted, and able to fight back. `WISP` is immobile too but dies to a stiff
#: breeze, and a fixture that is dead by tick two cannot demonstrate that it was
#: never offered an action it could not take.
BULWARK = UnitType(
    id="ember-bulwark",
    kind="summon",
    schools=("fire",),
    max_hp=400,
    damage=6,
    range=26,
    speed=0,
    attack_cooldown_seconds=1,
)

ROSTER = [ADEPT, HOUND, RAM, SPRITE, WISP, BULWARK]

#: A hound that would rather have a kill than a post.
#:
#: The sample profiles will not chase, and that is correct rather than a
#: shortcoming: leaving a post costs a full stride of objective progress and an
#: approach earns back at most half a point of target suitability, so an ordinary
#: creature under a hold order holds. Which means the sample profiles cannot
#: demonstrate the *bounds* on chasing, because they never start one. This is the
#: ticket's "hunters exploit exposed targets within configured task bounds",
#: written as the data it is supposed to be — and the bounds still hold it.
HUNTERS = BehaviorLibrary(
    profiles=(
        CreatureProfile(
            type_id=HOUND.id,
            base_weights={
                "objective_progress": 0.25,
                "target_suitability": 3.0,
                "danger": 0.5,
                "ally_support": 0.5,
            },
        ),
    )
)


class Run:
    """A battle played out on a hand-placed field, and what each unit did."""

    def __init__(self, world: World, history: list[dict[str, Intent]]) -> None:
        self.world = world
        self.history = history

    def unit(self, unit_id: str) -> Unit:
        return next(u for u in self.world.units if u.id == unit_id)

    def intents(self, unit_id: str) -> list[Intent]:
        return [tick[unit_id] for tick in self.history if unit_id in tick]

    def actions(self, unit_id: str) -> list[str]:
        return [intent.kind for intent in self.intents(unit_id)]

    def reasons(self, unit_id: str) -> list[str]:
        return [intent.reason for intent in self.intents(unit_id)]


def play(
    units: Sequence[Unit],
    ticks: int = 60,
    unit_types: Sequence[UnitType] = (),
    library: BehaviorLibrary | None = None,
    orders: Mapping[str, Order] | None = None,
) -> Run:
    """Runs the real phase list, recording every unit's intent each tick.

    Behaviour is attached from `ai/fixtures.sample_library` rather than left
    neutral, and that is not a detail. Neutral weights are the configuration
    *least* inclined to leave a post for anything: a full stride away from the
    station costs a whole point of objective progress, and an approach can earn
    back at most half a point of target suitability, so at equal weights a unit
    only ever fights what walks into it. Every behaviour this ticket adds is a
    preference, and a preference cannot be demonstrated by a creature that has
    none. The sample profiles give the hound `aggressive` and the adept `wary`,
    which is the whole point of the package: behaviour is data.
    """
    world = make_world(list(units), orders=orders)
    catalog = build_unit_type_catalog(list(unit_types or ROSTER))
    attach_behavior(world.units, world.troops, library or sample_library(), catalog)
    for unit in world.units:
        if unit.ai is None:
            unit.ai = UnitAi()

    ctx = create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(11),
        unit_types=list(unit_types or ROSTER),
    )

    history: list[dict[str, Intent]] = []
    for _ in range(ticks):
        world.tick += 1
        for phase in TICK_PHASES:
            phase.run(world, ctx)
        history.append(
            {u.id: u.ai.intent for u in world.units if u.ai is not None and u.ai.intent is not None}
        )

    return Run(world, history)


def test_a_ranged_unit_keeps_its_distance_from_something_that_has_to_close() -> None:
    """Range maintenance, end to end.

    The adept outranges the ram by seventy map units and is quicker than it. It
    should end the run no nearer than it started — and, crucially, should still
    be shooting while it does that, which is what makes this a `withdraw` rather
    than a `retreat`.
    """
    adept = make_unit("a", ADEPT, "north", HERE, destination=HERE)
    ram = make_unit("r", RAM, "south", Vec2(HERE.x + 30, HERE.y), destination=HERE)
    run = play([adept, ram])

    opening = 30.0
    closing = distance(run.unit("a").position, run.unit("r").position)

    assert closing > opening, "the adept let a slower melee unit walk right up to it"
    assert run.unit("r").hp < RAM.max_hp, "it backed off without ever firing"


def test_withdrawing_walks_at_half_speed_and_retreating_at_full() -> None:
    """The one difference that cannot be expressed as a parameter.

    Half speed lives in `intent.movement_scale` and is applied by the movement
    phase; if the two disagreed, a unit would weigh the danger at a position it
    was not going to reach. Asserted against the phase rather than the constant
    so that the scale being *read* is what is pinned.
    """
    scales: tuple[tuple[ActionKind, float], ...] = (
        ("withdraw", WITHDRAW_SPEED_SCALE),
        ("retreat", 1.0),
        ("advance", 1.0),
    )
    for kind, expected in scales:
        walker = make_unit("w", HOUND, "north", HERE)
        world = make_world([walker])
        walker.ai = UnitAi()
        far = Vec2(HERE.x - 400, HERE.y)
        walker.ai.intent = Intent(kind=kind, destination=far)
        walker.destination = far

        ctx = create_tick_context(
            config=DEFAULT_SIM_CONFIG,
            map_config=TWO_LANE_MAP,
            multipliers=resolve_side_multipliers([]),
            rng=create_rng(1),
        )
        movement = next(phase for phase in TICK_PHASES if phase.name == "movement")
        movement.run(world, ctx)

        covered = distance(HERE, walker.position)
        full = HOUND.speed * ctx.seconds_per_tick
        assert covered == pytest.approx(full * expected), f"{kind} walked {covered}, not {full * expected}"


def test_a_retreating_unit_does_not_shoot_what_it_is_running_from() -> None:
    """The change JQ-328 said would be needed, and why it is in `targeting.py`.

    `acquire_target` fell back to nearest-in-range for every intent that was not
    an `attack`, so advance, hold and cast all swung anyway. A retreat had no way
    to decline. It does now, and `withdraw` deliberately does not use it — that
    is the whole distinction between the two verbs.
    """
    quarry = make_unit("q", HOUND, "south", Vec2(HERE.x + 5, HERE.y))
    world = make_world([make_unit("r", HOUND, "north", HERE), quarry])
    runner = world.units[0]
    runner.ai = UnitAi()
    runner.ai.intent = Intent(kind="retreat", destination=Vec2(HERE.x - 400, HERE.y))

    ctx = create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(1),
    )
    combat = next(phase for phase in TICK_PHASES if phase.name == "combat")
    combat.run(world, ctx)

    assert quarry.hp == HOUND.max_hp

    # And the same unit withdrawing does swing, which is the point of two verbs.
    runner.ai.intent = Intent(kind="withdraw", destination=Vec2(HERE.x - 400, HERE.y))
    runner.cooldown_remaining = 0
    combat.run(world, ctx)

    assert quarry.hp < HOUND.max_hp


def test_a_guard_and_an_archer_answer_one_nominated_threat_from_their_own_distances() -> None:
    """Screening is capability-derived, which is what makes one assignment reusable.

    Both are handed the identical job through JQ-330's seam — *that* enemy is the
    one to answer — and neither is labelled a guard or an archer. The hound's
    screen lands in the threat's face because its weapon is a bite; the adept's
    lands most of a lane back because its weapon is not. One rule, two positions,
    no branch on a creature id anywhere.

    Asserted on the candidate rather than on where the units end up after a run.
    A formation pulls both of them toward the same hotspot within a few ticks, so
    an end-of-run position measures JQ-287's placement rather than this ticket's,
    and measured exactly that: both cards finished at an identical 48.75.
    """
    # Beyond even the adept's reach, so both cards have to move to interpose.
    # A unit that can already shoot the threat from where it stands does not get
    # a screen at all — standing and shooting is the screen, and `hold` is that.
    # Outside the adept's reach, so both cards have to move to interpose, and
    # inside the hound's pursuit leash, so both are allowed to.
    threat_at = Vec2(HERE.x + 100, HERE.y)
    # Off the threat-to-screener line on purpose. Colinear, the screen and the
    # plain approach are the same point and deduplicate into one candidate —
    # correctly, since on the line the two moves *are* the same move, but it
    # makes for a test that proves nothing about screening.
    ally_at = Vec2(HERE.x - 40, HERE.y + 50)

    screens = {}
    for card in (HOUND, ADEPT):
        screener = make_unit("s", card, "north", HERE, destination=HERE)
        ally = make_unit("f", WISP, "north", ally_at, destination=ally_at)
        threat = make_unit("t", RAM, "south", threat_at, destination=ally_at)
        world = make_world([screener, ally, threat])

        observation = observe(world, screener, TWO_LANE_MAP, SECONDS_PER_TICK, nominated_target_ids=["t"])
        screening = [c for c in generate_candidates(observation) if c.reason == SCREENING]

        assert screening, f"{card.id} was nominated a threat and offered no screen"
        assert len(screening) == 1, "one threat, one screen — the set stays bounded"
        screens[card.id] = screening[0]

    gaps = {
        card_id: distance(candidate.destination, threat_at)
        for card_id, candidate in screens.items()
        if candidate.destination is not None
    }

    assert gaps[HOUND.id] < gaps[ADEPT.id], "both screened from the same distance"
    for card in (HOUND, ADEPT):
        assert gaps[card.id] <= card.range, f"{card.id} screened from outside its own weapon"
        # And on the line the threat has to come down, not off to one side.
        destination = screens[card.id].destination
        assert destination is not None
        assert distance(destination, threat_at) + distance(destination, ally_at) == pytest.approx(
            distance(threat_at, ally_at)
        )


def test_repeated_bait_cannot_walk_a_unit_off_the_field() -> None:
    """The bound that is easy to leave out, checked against the thing it prevents.

    A quarry that keeps stepping just out of reach is the classic exploit: every
    tick the chase looks worth continuing, and a unit with no memory of having
    already chased will follow it to the edge of the map. The leash caps one trip
    and recovery caps how often a trip can start, so total displacement stays
    bounded however long the bait keeps at it.

    The bait is teleported back to a fixed offset every tick, which is a stronger
    test than a bait that merely runs: it can never be caught, never tires, and
    never makes a mistake. If anything bounds this, it is the bounds.
    """
    # Starts *inside* the hound's reach, so engaging it is free and the hound
    # takes the hook; from then on it sits a hair outside, which is the whole
    # trick. A bait that was never worth chasing tests nothing.
    hunter = make_unit("h", HOUND, "north", HERE, destination=HERE)
    bait = make_unit("b", SPRITE, "south", Vec2(HERE.x + HOUND.range - 4, HERE.y))
    world = make_world([hunter, bait], orders=HOLD_EAST)
    attach_behavior(world.units, world.troops, HUNTERS, build_unit_type_catalog(ROSTER))
    for unit in world.units:
        if unit.ai is None:
            unit.ai = UnitAi()

    ctx = create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(3),
        unit_types=ROSTER,
    )

    furthest = 0.0
    endings: set[str] = set()
    for _ in range(400):
        world.tick += 1
        for phase in TICK_PHASES:
            phase.run(world, ctx)
        if hunter.ai is not None and hunter.ai.intent is not None:
            endings.add(hunter.ai.intent.reason)
        furthest = max(furthest, distance(HERE, hunter.position))
        # Whatever the hunter did, the bait is one step beyond its reach again.
        bait.position = Vec2(hunter.position.x + HOUND.range + 4, hunter.position.y)
        bait.hp = SPRITE.max_hp

    assert furthest <= PURSUIT_LEASH + HOUND.speed, (
        f"walked {furthest:.1f} from its post chasing bait it could never catch"
    )
    assert endings & set(PURSUIT_ENDED_REASONS), (
        f"never gave up on uncatchable bait; only saw {sorted(endings)}"
    )


def test_an_immobile_fixture_decides_something_and_never_tries_to_walk() -> None:
    """A rooted unit is where an impossible action would show up first.

    It has no legs, no weapon and three enemies in contact, which is every reason
    to want to leave and no way to do it. It must still decide — the loop always
    has a fallback — and the decision must never be one the movement phase would
    have to refuse.
    """
    fixture = make_unit("w", BULWARK, "north", HERE, destination=Vec2(HERE.x - 200, HERE.y))
    enemies = [
        make_unit(f"e{i}", HOUND, "south", Vec2(HERE.x + 6 + i * 3, HERE.y), destination=HERE)
        for i in range(3)
    ]
    run = play([fixture, *enemies], ticks=20)

    assert run.actions("w"), "the fixture never decided anything"
    assert set(run.actions("w")) <= {"hold", "attack"}
    assert run.unit("w").position == HERE, "an immobile unit moved"


def test_a_unit_resumes_its_task_after_the_thing_it_was_chasing_dies() -> None:
    """Release has to be prompt, and returning has to need no bookkeeping.

    The station is rewritten by the orders phase every tick, so "go back to your
    post" is what a unit does by running out of better ideas — the mechanism
    JQ-287 and JQ-328 both leaned on. What this pins is that a commitment does
    not outlive its quarry and quietly go on suppressing that.
    """
    drawn_off = Vec2(POST.x + 70, POST.y)
    hunter = make_unit("h", HOUND, "north", drawn_off)
    doomed = make_unit("d", WISP, "south", Vec2(drawn_off.x + 10, drawn_off.y))
    world = make_world([hunter, doomed], orders=HOLD_EAST)
    attach_behavior(world.units, world.troops, sample_library(), build_unit_type_catalog(ROSTER))
    hunter.ai = hunter.ai or UnitAi()
    hunter.ai.commitment = Commitment(target_id="d", started_tick=0, origin=drawn_off, opening_gap=10.0)

    ctx = create_tick_context(
        config=DEFAULT_SIM_CONFIG,
        map_config=TWO_LANE_MAP,
        multipliers=resolve_side_multipliers([]),
        rng=create_rng(5),
        unit_types=ROSTER,
    )

    for _ in range(40):
        world.tick += 1
        for phase in TICK_PHASES:
            phase.run(world, ctx)

    assert all(u.id != "d" for u in world.units), "the quarry never died, so nothing was released"

    # Read back off the world rather than through the local: the phases mutate
    # this, and a narrowed local would let a type checker conclude the
    # assertion below can never fire.
    settled = next(u for u in world.units if u.id == "h")
    assert settled.ai is not None and settled.ai.commitment is None, (
        "still committed to something that no longer exists"
    )
    assert distance(settled.position, POST) < distance(drawn_off, POST), "did not head back"


def test_every_reason_emitted_is_one_of_the_published_ones() -> None:
    """JQ-331 prints these, so the set is a contract rather than a convenience."""
    adept = make_unit("a", ADEPT, "north", HERE, destination=Vec2(HERE.x + 200, HERE.y))
    hound = make_unit("h", HOUND, "south", Vec2(HERE.x + 60, HERE.y), destination=HERE)
    run = play([adept, hound], ticks=60)

    seen = set(run.reasons("a")) | set(run.reasons("h"))

    assert seen, "no reason was ever emitted"
    assert seen <= set(REASONS), f"{sorted(seen - set(REASONS))} is not a published reason"


def test_a_unit_does_not_oscillate_between_two_positions() -> None:
    """Sustained flip-flopping is the failure this candidate set invites.

    Two mirrored options a hair apart, re-derived from scratch every tick, will
    alternate for ever unless something holds a choice steady. Measured over the
    placeholder armies the rate is under one percent of decisions; this stages
    the arrangement most likely to produce it — a unit between two identical
    enemies — and asks for no long alternating run at all.
    """
    middle = make_unit("m", HOUND, "north", HERE, destination=HERE)
    left = make_unit("l", RAM, "south", Vec2(HERE.x - 45, HERE.y), destination=HERE)
    right = make_unit("r", RAM, "south", Vec2(HERE.x + 45, HERE.y), destination=HERE)
    run = play([middle, left, right], ticks=120)

    choices = [(i.kind, i.target_id) for i in run.intents("m")]
    flips = sum(
        1 for i in range(2, len(choices)) if choices[i] == choices[i - 2] and choices[i] != choices[i - 1]
    )

    assert flips <= len(choices) // 10, f"{flips} reversals in {len(choices)} decisions"


def test_useful_range_is_not_inside_the_walking_standoff() -> None:
    """Two constants in two files that cannot import each other, pinned together.

    `ai/` cannot import `phases/` without closing an import cycle, so the fraction
    a unit *wants* to stand at and the fraction movement will *let* it walk to are
    declared separately. If the wanted distance were the nearer of the two, a unit
    would push toward a destination it can never reach and never stop pushing —
    the same class of trap `CONVENTIONS.md` records twice under "Boundaries in the
    sim's geometry", where a stopping rule and an acting rule met at one point.
    """
    from app.sim.phases.movement import engagement_standoff

    for card in ROSTER:
        unit = make_unit("u", card, "north", HERE)
        assert useful_range(capabilities_of(unit)) >= engagement_standoff(unit)
