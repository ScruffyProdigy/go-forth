"""One authoritative round: stepping, casting, and how it ends.

The round is where the sim stops being a batch job. Everything here is about
what a *live* round has that `run_battle` does not — seat energy, casts arriving
mid-battle, and a stopping rule that distinguishes a round from a match.
"""

from __future__ import annotations

import pytest

from app.match import fixtures
from app.match.plan import default_plan, resolve_snapshot
from app.match.round import ENERGY_CAP, SCORE_THRESHOLD, AuthoritativeRound
from app.match.wire import CastCommand
from app.sim.config import SimConfig
from app.sim.spellbook import read_field
from app.sim.types import SIDES, Vec2

MAP = fixtures.map_config()


def make_round(*, seconds: float = 6, seed: int = 5, energy: float = 100.0) -> AuthoritativeRound:
    plan = default_plan(MAP)
    snapshots = {side: resolve_snapshot(plan, side) for side in SIDES}
    return AuthoritativeRound(
        round_number=1,
        map_config=MAP,
        plans={side: plan for side in SIDES},
        snapshots=snapshots,
        base_hp={side: 1000.0 for side in SIDES},
        seed=seed,
        sim_config=SimConfig(max_battle_seconds=seconds),
        starting_energy=energy,
    )


def run_to_end(rnd: AuthoritativeRound, limit: int = 5000) -> int:
    ticks = 0
    while not rnd.over and ticks < limit:
        rnd.step()
        ticks += 1
    return ticks


# ------------------------------------------------------------- the battle --


def test_a_round_starts_with_both_armies_on_the_field() -> None:
    rnd = make_round()
    sides = {unit.side for unit in rnd.world.units}
    assert sides == {"north", "south"}


def test_a_round_ends_and_says_why() -> None:
    rnd = make_round(seconds=4)
    run_to_end(rnd)
    assert rnd.over
    ending = rnd.ending
    assert ending is not None
    assert ending.kind in ("roundComplete", "baseDestroyed")


def test_stepping_past_the_end_is_a_no_op() -> None:
    rnd = make_round(seconds=2)
    run_to_end(rnd)
    tick = rnd.world.tick
    for _ in range(10):
        assert rnd.step() == ()
    # A finished round must not keep simulating under a client that kept asking.
    assert rnd.world.tick == tick


def test_the_same_seed_and_the_same_casts_give_the_same_battle() -> None:
    """Stepped rather than replayed, so determinism has to survive the stepping."""
    first = make_round(seed=99, seconds=4)
    second = make_round(seed=99, seconds=4)
    run_to_end(first)
    run_to_end(second)

    assert first.world.tick == second.world.tick
    assert first.base_hp() == second.base_hp()
    assert [(u.id, u.hp, u.position) for u in sorted(first.world.units, key=lambda u: u.id)] == [
        (u.id, u.hp, u.position) for u in sorted(second.world.units, key=lambda u: u.id)
    ]


# --------------------------------------------------------------- energy --


def test_seat_energy_accrues_on_the_battle_clock() -> None:
    rnd = make_round(energy=0.0)
    assert rnd.energy_for("north") == 0.0
    for _ in range(20):  # one second at the default tick rate
        rnd.step()
    assert rnd.energy_for("north") == pytest.approx(4.0)


def test_seat_energy_is_capped() -> None:
    rnd = make_round(energy=ENERGY_CAP + 500)
    # Without a cap, a player who casts nothing for 90 seconds arrives at the
    # next round able to empty their whole loadout at once.
    assert rnd.energy_for("north") == ENERGY_CAP


# ---------------------------------------------------------------- casts --


def _cast(spell_id: str = "fireball", x: float = 180.0, y: float = 280.0, cid: str = "c1") -> CastCommand:
    return CastCommand(command_id=cid, spell_id=spell_id, at=Vec2(x, y), tick=0)


def test_an_affordable_cast_is_accepted_and_charged() -> None:
    rnd = make_round(energy=100.0)
    rnd.step()
    before = rnd.energy_for("north")

    outcome = rnd.cast("north", _cast())
    assert outcome.accepted
    assert rnd.energy_for("north") == pytest.approx(before - 35.0)
    assert [c.spell_id for c in rnd.casts()] == ["fireball"]


def test_a_cast_is_scheduled_on_the_next_tick_not_the_one_the_client_named() -> None:
    rnd = make_round(energy=100.0)
    for _ in range(10):
        rnd.step()

    # The client says tick 0 — a tick that has long since run.
    rnd.cast("north", CastCommand(command_id="c1", spell_id="fireball", at=Vec2(180, 280), tick=0))
    resolved = rnd.casts()[0]
    # Honouring a client-chosen tick means either a cast in the past, which
    # cannot happen, or a free delayed cast nobody else can see coming.
    assert resolved.tick == rnd.world.tick + 1


def test_the_cast_carries_the_seats_side_not_the_clients_claim() -> None:
    rnd = make_round(energy=100.0)
    rnd.step()
    rnd.cast("south", _cast())
    # `side` is filled in from the seat. A client trusted to name its own side
    # is a client that can cast as its opponent.
    assert rnd.casts()[0].cast_by == "south"
    assert rnd.world.pending_spells[0].side == "south"


def test_a_cast_reaches_the_sims_pending_queue() -> None:
    rnd = make_round(energy=100.0)
    rnd.step()
    rnd.cast("north", _cast())
    assert len(rnd.world.pending_spells) == 1
    # Nothing about damage crosses: the sim looks effects up in its own
    # catalogue, so a client that lies about a payload changes nothing.
    assert rnd.world.pending_spells[0].spell_id == "north:fireball"


def test_a_cast_actually_fires(  # the queue is not enough — it has to land
) -> None:
    rnd = make_round(energy=100.0, seconds=6)
    rnd.step()
    rnd.cast("north", _cast())
    for _ in range(5):
        rnd.step()
    assert rnd.world.pending_spells == [], "the spells phase should have taken it"


# ---------------------------------------------------------- refusals --


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (_cast(spell_id="not-a-spell"), "notEquipped"),
        (_cast(x=-5.0), "outOfBounds"),
        (_cast(y=99_999.0), "outOfBounds"),
    ],
)
def test_an_illegal_cast_is_refused(command: CastCommand, reason: str) -> None:
    rnd = make_round(energy=100.0)
    rnd.step()
    outcome = rnd.cast("north", command)
    assert not outcome.accepted
    assert outcome.rejection == reason


def test_an_unaffordable_cast_is_refused() -> None:
    rnd = make_round(energy=0.0)
    rnd.step()
    outcome = rnd.cast("north", _cast())
    assert outcome.rejection == "notEnoughEnergy"


def test_a_refusal_never_spends() -> None:
    """The property worth stating: a charged rejection is indistinguishable,
    from the seat, from a cast that landed and did nothing."""
    rnd = make_round(energy=100.0)
    rnd.step()
    before = rnd.energy_for("north")

    for command in (_cast(spell_id="nope"), _cast(x=-1.0)):
        rnd.cast("north", command)

    assert rnd.energy_for("north") == before
    assert rnd.casts() == []
    assert rnd.world.pending_spells == []


def test_a_cast_after_the_round_is_over_is_refused() -> None:
    rnd = make_round(seconds=2, energy=100.0)
    run_to_end(rnd)
    outcome = rnd.cast("north", _cast())
    assert outcome.rejection == "roundOver"


def test_a_cast_does_not_disturb_the_opponents_energy() -> None:
    rnd = make_round(energy=100.0)
    rnd.step()
    south_before = rnd.energy_for("south")
    rnd.cast("north", _cast())
    assert rnd.energy_for("south") == south_before


# ------------------------------------------------------------- endings --


def test_a_destroyed_base_ends_the_round_as_base_destroyed() -> None:
    rnd = make_round(seconds=90)
    # Reaching this in a real battle takes a long time and a lucky seed, so the
    # world is put into the state directly: what is under test is the stopping
    # rule, not how long it takes to get there.
    rnd.world.bases["south"].hp = 0
    rnd.step()

    ending = rnd.ending
    assert ending is not None
    assert ending.kind == "baseDestroyed"
    # The side whose base fell loses; the other side wins the *match*.
    assert ending.winner == "north"


def test_base_destruction_beats_everything_else_on_the_same_tick() -> None:
    rnd = make_round(seconds=90)
    rnd.world.bases["south"].hp = 0
    # Wipe the north army out on the same tick. Annihilation alone would end the
    # round with a winner; a base falling ends the match.
    for unit in rnd.world.units:
        if unit.side == "north":
            unit.hp = 0
    rnd.step()

    ending = rnd.ending
    assert ending is not None
    assert ending.kind == "baseDestroyed"


def test_an_exact_tie_on_zone_score_is_a_draw() -> None:
    rnd = make_round(seconds=1)
    run_to_end(rnd)
    ending = rnd.ending
    assert ending is not None
    if ending.reason == "timeUp" and rnd.world.zone_score["north"] == rnd.world.zone_score["south"]:
        # Reachable: the demo is a mirror match. A round awarded to whichever
        # side the code checked first would be the least explicable loss in the
        # game.
        assert ending.winner is None


def test_the_side_ahead_on_zone_score_takes_a_timed_out_round() -> None:
    rnd = make_round(seconds=90)
    rnd.world.zone_score["north"] = 10.0
    rnd.world.zone_score["south"] = 3.0
    rnd.world.tick = 1799
    rnd.step()

    ending = rnd.ending
    assert ending is not None
    assert ending.reason == "timeUp"
    assert ending.winner == "north"


def test_base_hp_is_carried_out_of_the_round_untouched() -> None:
    rnd = make_round(seconds=4)
    rnd.world.bases["north"].hp = 812.5
    run_to_end(rnd)
    # Nothing between here and the next round refills a base (JQ-187), so what
    # comes out is what the next round opens on.
    assert rnd.base_hp()["north"] <= 812.5


# --- the outcome policies (JQ-308) -----------------------------------------
#
# Staged by putting the world into the state under test rather than by finding a
# round that happens to reach it. That is the only way to put two endings on the
# *same tick*, which is exactly where the precedence rules live.


def test_both_bases_falling_on_one_tick_is_a_draw() -> None:
    """Ryan, 2026-09-15: symmetric event, symmetric result. Reachable, because
    two spells can land on one tick with nothing serialising them."""
    rnd = make_round()
    rnd.step()
    for side in SIDES:
        rnd.world.bases[side].hp = 0
    rnd.step()

    ending = rnd.ending
    assert ending is not None
    assert ending.kind == "baseDestroyed"
    assert ending.winner is None


def test_a_mutual_destruction_does_not_quietly_become_a_south_win() -> None:
    """The bug this replaces: a loop walking SIDES returned on the first base at
    zero, so a double destruction was awarded to `opposing("north")`. An
    accident of iteration order, not a rule anyone chose."""
    rnd = make_round()
    rnd.step()
    for side in SIDES:
        rnd.world.bases[side].hp = 0
    rnd.step()

    assert rnd.ending is not None and rnd.ending.winner is None


def test_one_base_falling_still_loses_the_match_for_that_side() -> None:
    """The complement: making mutual destruction a draw must not stop an
    ordinary base destruction naming a winner."""
    rnd = make_round()
    rnd.step()
    rnd.world.bases["south"].hp = 0
    rnd.step()

    ending = rnd.ending
    assert ending is not None
    assert ending.kind == "baseDestroyed"
    assert ending.winner == "north"


def test_a_fallen_base_beats_a_score_threshold_on_the_same_tick() -> None:
    """Precedence, and the one that matters: the side whose base just fell does
    not get to win on points for the same tick."""
    rnd = make_round()
    rnd.step()
    rnd.world.zone_score["south"] = SCORE_THRESHOLD + 100
    rnd.world.bases["south"].hp = 0
    rnd.step()

    assert rnd.ending is not None
    assert rnd.ending.kind == "baseDestroyed"
    assert rnd.ending.winner == "north"


def test_an_exact_score_tie_at_the_backstop_breaks_on_base_hp() -> None:
    """Ryan, 2026-09-15. Rewards the chip damage a pure zone comparison throws
    away, using a number already carried across rounds."""
    rnd = make_round(seconds=1)
    run_to_end(rnd)
    assert rnd.ending is not None and rnd.ending.reason == "timeUp"

    rnd = make_round(seconds=1)
    while not rnd.over:
        rnd.world.zone_score["north"] = 40
        rnd.world.zone_score["south"] = 40
        rnd.world.bases["north"].hp = 900
        rnd.world.bases["south"].hp = 700
        rnd.step()

    ending = rnd.ending
    assert ending is not None
    assert ending.reason == "timeUp"
    assert ending.winner == "north"


def test_a_tie_on_score_and_base_hp_is_still_a_draw() -> None:
    """Never invent a winner. A draw is a real answer."""
    rnd = make_round(seconds=1)
    while not rnd.over:
        rnd.world.zone_score["north"] = 40
        rnd.world.zone_score["south"] = 40
        rnd.world.bases["north"].hp = 800
        rnd.world.bases["south"].hp = 800
        rnd.step()

    assert rnd.ending is not None
    assert rnd.ending.winner is None


def test_zone_score_still_decides_when_it_is_not_tied() -> None:
    """The base-HP tiebreak is a tiebreak, not a second criterion: a side ahead
    on zone score wins even with the weaker base."""
    rnd = make_round(seconds=1)
    while not rnd.over:
        rnd.world.zone_score["north"] = 10
        rnd.world.zone_score["south"] = 90
        rnd.world.bases["north"].hp = 1000
        rnd.world.bases["south"].hp = 200
        rnd.step()

    assert rnd.ending is not None
    assert rnd.ending.winner == "south"


# --- seat energy accounting -------------------------------------------------


def test_the_energy_books_balance_over_a_whole_round() -> None:
    """JQ-308 asks for energy accounting to be tested. The balance is derived
    from two ledgers, so this asserts neither ledger was skipped — and that the
    derived form does not drift the way an accumulated total did."""
    rnd = make_round(seconds=6, energy=100.0)
    spell = rnd.loadout_for("north")[0]

    casts = 0
    while not rnd.over:
        outcome = rnd.cast(
            "north",
            CastCommand(
                command_id=f"c{rnd.world.tick}",
                spell_id=spell.spell_id,
                at=Vec2(187.5, 290.0),
                tick=rnd.world.tick,
            ),
        )
        casts += 1 if outcome.accepted else 0
        rnd.step()

    pool = rnd._energy["north"]
    assert casts > 0
    assert pool.spent == casts * spell.cost
    assert pool.current == pool.start + pool.generated - pool.spent


def test_energy_never_exceeds_the_cap_however_long_the_round_runs() -> None:
    rnd = make_round(seconds=20, energy=ENERGY_CAP)
    for _ in range(200):
        rnd.step()
    assert rnd.energy_for("north") == ENERGY_CAP


def test_a_refused_cast_spends_nothing() -> None:
    rnd = make_round(energy=0.0)
    spell = rnd.loadout_for("north")[0]
    rnd.step()
    before = rnd.energy_for("north")

    outcome = rnd.cast(
        "north",
        CastCommand(command_id="x", spell_id=spell.spell_id, at=Vec2(187.5, 290.0), tick=rnd.world.tick),
    )
    assert not outcome.accepted and outcome.rejection == "notEnoughEnergy"
    assert rnd.energy_for("north") == before


# ------------------------------------------------- the loadout after lock-in --


def _kill_every_mage(rnd: AuthoritativeRound, side: str) -> int:
    """Kills this seat's mages where the sim can see it. Returns how many fell.

    Reaching into the world rather than playing a battle out until they die: the
    claim under test is that the *loadout* does not read the world, and the
    cheapest way to prove that is to make the world as wrong as possible and
    look again.
    """
    fallen = 0
    for unit in rnd.world.units:
        if unit.side == side and unit.kind == "mage":
            unit.hp = 0
            fallen += 1
    return fallen


def test_a_contributor_dying_does_not_remove_a_button() -> None:
    """JQ-297's provisional playtest policy, at the layer that has to honour it.

    Every Ember Adept on the field grants the Fireball *and* raises its numbers.
    Killing all three would, on a live re-resolution, take the spell off the
    menu mid-battle — a button vanishing from under the player's thumb.
    """
    rnd = make_round(seconds=8)
    before = rnd.loadout_for("north")
    rnd.step()

    assert _kill_every_mage(rnd, "north") == fixtures.MAGE_CAP
    rnd.step()

    assert rnd.loadout_for("north") == before


def test_a_contributor_dying_does_not_change_a_cost_or_an_effect() -> None:
    rnd = make_round(seconds=8)
    spell = rnd.loadout_for("north")[0]
    rnd.step()
    _kill_every_mage(rnd, "north")
    rnd.step()

    after = rnd.loadout_for("north")[0]
    assert after.cost == spell.cost
    assert after.effect == spell.effect
    assert after.tag_support == spell.tag_support


def test_a_cast_after_every_contributor_has_died_fires_the_snapshot_numbers() -> None:
    """The half that matters most: not the label, the damage.

    A loadout that kept its printed cost while the sim fired a re-derived,
    unsupported Fireball would look correct on every screen and be wrong in the
    only place it counts.
    """
    rnd = make_round(seconds=8, energy=200.0)
    rnd.step()
    _kill_every_mage(rnd, "north")

    # Cast before the next step rather than after it. Losing every mage wipes
    # the side out — the troop bond dissolves its summons with it — and a wiped
    # side ends the round, which would refuse the cast for a reason that has
    # nothing to do with what is being tested.
    spell = rnd.loadout_for("north")[0]
    outcome = rnd.cast(
        "north",
        CastCommand(command_id="c1", spell_id=spell.spell_id, at=Vec2(187.5, 290.0), tick=rnd.world.tick),
    )
    assert outcome.accepted

    queued = rnd.world.pending_spells[0]
    assert queued.spell_id == "north:fireball"
    blast = rnd._runner.ctx.spells[queued.spell_id].effects[0]
    # 28 + 3 x 8, capped at 24. The support that bought it is dead; the number
    # is the one the plan screen showed.
    assert read_field(blast, "damage.amount") == 52
