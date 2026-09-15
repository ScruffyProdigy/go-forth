"""Generating candidates: everything legal, nothing illegal, in a stable order."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.capabilities import capabilities_of
from app.sim.ai.positioning import useful_range
from app.sim.ai.pursuit import PURSUIT_LEASH
from app.sim.geometry import distance
from app.sim.map import TWO_LANE_MAP
from app.sim.orders import PUSH_ENEMY_BASE, hold
from app.sim.types import Vec2
from tests.sim.ai.helpers import look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND, WISP

MIDFIELD = Vec2(180, 300)
SOUTH_BASE = TWO_LANE_MAP.bases["south"].position


def kinds(candidates: Sequence[Candidate]) -> list[str]:
    return [candidate.kind for candidate in candidates]


def test_hold_is_always_available_so_the_loop_always_has_a_fallback() -> None:
    """A rooted, harmless unit with nowhere to be still decides something."""
    world = make_world([make_unit("w", WISP, "north", MIDFIELD)])

    candidates = generate_candidates(look(world, world.units[0]))

    assert kinds(candidates) == ["hold"]


def test_a_unit_that_cannot_move_gets_no_advance_candidate() -> None:
    world = make_world([make_unit("w", WISP, "north", MIDFIELD)])

    assert "advance" not in kinds(generate_candidates(look(world, world.units[0])))


def test_a_unit_that_cannot_attack_gets_no_attack_candidate() -> None:
    """Even standing on top of an enemy — legality is not a matter of taste."""
    wisp = make_unit("w", WISP, "north", MIDFIELD)
    world = make_world([wisp, make_unit("e", HOUND, "south", MIDFIELD)])

    assert "attack" not in kinds(generate_candidates(look(world, wisp)))


def test_only_enemies_inside_reach_become_attack_candidates() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    near = make_unit("e-near", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y))
    far = make_unit("e-far", HOUND, "south", Vec2(MIDFIELD.x + 200, MIDFIELD.y))
    world = make_world([hound, near, far])

    attacks = [c.target_id for c in generate_candidates(look(world, hound)) if c.kind == "attack"]

    assert attacks == ["e-near"]


def test_a_dead_enemy_is_not_a_candidate() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    corpse = make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y), hp=0)
    world = make_world([hound, corpse])

    assert "attack" not in kinds(generate_candidates(look(world, hound)))


def test_a_unit_may_advance_on_its_station_and_on_the_nearest_enemy() -> None:
    """And the enemy advance stops at useful attack range, not on the enemy.

    Changed by JQ-329. JQ-328 walked at the enemy's own feet and left it to the
    movement phase's standoff clamp to stop short; the destination is now the
    place the unit actually wants to stand, which is its own reach back along the
    line. The two produce nearly the same walk and very different *scoring* — a
    candidate judged at where it would really end up can be compared with one
    that stands still, and one judged at a point it will never reach cannot.
    """
    # A station it is not already standing on, so the walk to it is on offer.
    # The enemy is near enough that closing on it stays inside the pursuit
    # leash; see `test_a_unit_declines_to_set_out_after_something_past_the_leash`.
    hound = make_unit("h", HOUND, "north", MIDFIELD, destination=SOUTH_BASE)
    enemy = make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 60, MIDFIELD.y + 20))
    world = make_world([hound, enemy], orders={"north-t0": PUSH_ENEMY_BASE})

    destinations = {
        (c.destination.x, c.destination.y)
        for c in generate_candidates(look(world, hound))
        if c.kind == "advance" and c.destination is not None
    }

    assert (SOUTH_BASE.x, SOUTH_BASE.y) in destinations

    toward_enemy = [point for point in destinations if point != (SOUTH_BASE.x, SOUTH_BASE.y)]
    assert toward_enemy, "no advance on the nearest enemy was offered"
    reach = useful_range(capabilities_of(hound))
    for point in toward_enemy:
        assert distance(Vec2(*point), enemy.position) == pytest.approx(reach)


def test_a_troop_not_pushing_the_base_never_sees_the_base_as_somewhere_to_go() -> None:
    """JQ-287's restriction, applied before scoring rather than after.

    Filtering here rather than trusting the weights is the point: no trait, and
    no stack of personalities, can talk a defending troop into the enemy base,
    because the option is never on the table to be scored.
    """
    hound = make_unit("h", HOUND, "north", MIDFIELD, destination=SOUTH_BASE)
    world = make_world([hound], orders={"north-t0": hold("B")})

    candidates = generate_candidates(look(world, hound))

    assert kinds(candidates) == ["hold"]


def test_a_troop_pushing_the_base_does_see_it() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD, destination=SOUTH_BASE)
    world = make_world([hound], orders={"north-t0": PUSH_ENEMY_BASE})

    assert "advance" in kinds(generate_candidates(look(world, hound)))


def test_a_unit_already_standing_on_its_station_is_not_offered_a_walk_to_it() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD, destination=MIDFIELD)
    world = make_world([hound])

    assert kinds(generate_candidates(look(world, hound))) == ["hold"]


def test_candidates_come_out_in_a_stable_order_whatever_the_world_list_order() -> None:
    """The order is the tie-break, so it cannot depend on how units are listed.

    `world.units` reorders itself as the dead are swept, so an ordering that
    tracked list position would break ties differently after the first casualty.
    """
    adept = make_unit("a", ADEPT, "north", MIDFIELD)
    enemies = [
        make_unit("e-b", HOUND, "south", Vec2(MIDFIELD.x + 20, MIDFIELD.y)),
        make_unit("e-a", HOUND, "south", Vec2(MIDFIELD.x + 30, MIDFIELD.y)),
        make_unit("e-c", HOUND, "south", Vec2(MIDFIELD.x + 10, MIDFIELD.y)),
    ]

    forwards = generate_candidates(look(make_world([adept, *enemies]), adept))
    backwards = generate_candidates(look(make_world([adept, *reversed(enemies)]), adept))

    assert forwards == backwards
    assert [c.target_id for c in forwards if c.kind == "attack"] == ["e-a", "e-b", "e-c"]


def test_two_enemies_on_one_spot_do_not_produce_the_same_advance_twice() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    spot = Vec2(60, 320)
    world = make_world(
        [hound, make_unit("e-a", HOUND, "south", spot), make_unit("e-b", HOUND, "south", spot)]
    )

    advances = [c for c in generate_candidates(look(world, hound)) if c.kind == "advance"]

    assert len(advances) == len({(c.destination.x, c.destination.y) for c in advances if c.destination})


def test_giving_ground_is_two_verbs_that_execute_differently() -> None:
    """The successor to JQ-328's `test_no_candidate_expresses_a_retreat`.

    That test pinned the absence of this behaviour and said so: a unit standing
    on its station, badly hurt, with enemies in contact, whose only options were
    hold, attack, and an advance that led *toward* the danger. Its docstring
    named this ticket as the thing that would break it, and `CONVENTIONS.md` says
    to retire a pin whose behaviour is superseded rather than teach the sim to
    reproduce it. So it is retired, and this is what replaced it.

    **Two verbs, not one parameterised action,** because they execute in
    different phases and cannot be collapsed:

    * `withdraw` backs off at half speed and keeps shooting — half speed is in
      `intent.movement_scale`, the shooting is simply not suppressed.
    * `retreat` leaves at full speed and shoots at nothing — the suppression is
      in `phases/targeting.acquire_target`, which is where the old fallback
      quietly overruled every non-attack intent.

    A parameterised "give ground, flag: still fighting" would have to be
    half-honoured by the movement phase and half by target acquisition anyway,
    which is two changes wearing one name.
    """
    station = Vec2(180, 300)
    cornered = make_unit("h", HOUND, "north", station, hp=HOUND.max_hp / 5)
    world = make_world(
        [cornered]
        + [make_unit(f"e{i}", HOUND, "south", Vec2(station.x + 5 + i * 4, station.y)) for i in range(3)]
    )
    candidates = generate_candidates(look(world, cornered))

    assert "retreat" in kinds(candidates)

    # And it leads away from the danger, which is the whole of what was missing.
    retreat = next(c for c in candidates if c.kind == "retreat")
    assert retreat.destination is not None
    enemies = [u for u in world.units if u.side == "south"]
    assert min(distance(retreat.destination, e.position) for e in enemies) > min(
        distance(station, e.position) for e in enemies
    )


def test_a_melee_unit_gets_no_withdraw_because_backing_off_slowly_buys_it_nothing() -> None:
    """`withdraw` is for something that outranges what is coming at it.

    Backing away at half speed from a thing with equal reach is spent being hit
    for no gain — the gap you are opening is one it can close inside its own
    weapon. A creature in that position has `retreat` and nothing else, and which
    of the two a unit gets is read off live reach rather than off a label.
    """
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound, make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 5, MIDFIELD.y))])

    assert "withdraw" not in kinds(generate_candidates(look(world, hound)))


def test_a_ranged_unit_withdraws_to_useful_firing_distance_and_no_further() -> None:
    """Range maintenance, and the bound on it, are the same fact.

    The destination is a *point* — its own reach back from the enemy — not a
    direction. So a unit arrives at its firing distance and the candidate stops
    being generated: there is no way for `withdraw` to express an endless
    retreat, which is the ticket's "without endless retreat" made structural
    rather than tuned.
    """
    adept = make_unit("a", ADEPT, "north", MIDFIELD)
    enemy = make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + 20, MIDFIELD.y))
    world = make_world([adept, enemy])

    withdraw = next(c for c in generate_candidates(look(world, adept)) if c.kind == "withdraw")

    assert withdraw.destination is not None
    assert distance(withdraw.destination, enemy.position) == pytest.approx(
        useful_range(capabilities_of(adept))
    )

    # Standing at that distance already, there is nothing left to back away from.
    settled = make_unit("a", ADEPT, "north", MIDFIELD)
    far = make_unit(
        "e", HOUND, "south", Vec2(MIDFIELD.x + useful_range(capabilities_of(settled)), MIDFIELD.y)
    )
    assert "withdraw" not in kinds(generate_candidates(look(make_world([settled, far]), settled)))


def test_an_immobile_unit_never_receives_a_movement_action() -> None:
    """Including the two new ones, which is the easy half to forget.

    A rooted fixture surrounded by things it cannot escape must not be handed a
    retreat it cannot walk. Legality is decided before scoring precisely so that
    no weight, trait or personality can talk a unit into an impossible action.
    """
    wisp = make_unit("w", WISP, "north", MIDFIELD, destination=SOUTH_BASE)
    world = make_world(
        [wisp]
        + [make_unit(f"e{i}", HOUND, "south", Vec2(MIDFIELD.x + 5 + i * 4, MIDFIELD.y)) for i in range(3)]
    )

    assert set(kinds(generate_candidates(look(world, wisp)))) == {"hold"}


def test_no_advance_candidate_ever_walks_away_from_what_it_is_advancing_on() -> None:
    """The bug this shape invites, pinned in the general case.

    `point_along` does not clamp, so "the point a weapon's reach from that enemy"
    is *behind* a unit already nearer than that. An `advance` onto it walks
    backwards at full speed under a verb that is declared first and therefore
    wins every tie — a retreat nobody named, beating the two that are honest
    about it. It was reachable through both the approach and the screen; a
    five-hit sprite with an ash-ram closing preferred a "screen" forty map units
    to its rear.
    """
    for gap in (4.0, 10.0, 40.0, 100.0, 200.0):
        for unit_type in (HOUND, ADEPT):
            me = make_unit("m", unit_type, "north", MIDFIELD)
            enemy = make_unit("e", HOUND, "south", Vec2(MIDFIELD.x + gap, MIDFIELD.y))
            ally = make_unit("a", HOUND, "north", Vec2(MIDFIELD.x - 30, MIDFIELD.y))
            world = make_world([me, ally, enemy])

            here = distance(MIDFIELD, enemy.position)
            for candidate in generate_candidates(look(world, me)):
                if candidate.kind != "advance" or candidate.destination is None:
                    continue
                if candidate.target_id is None:
                    continue  # walking to the station is not a claim about the enemy
                assert distance(candidate.destination, enemy.position) <= here, (
                    f"{unit_type.id} at gap {gap}: {candidate.reason} opens the gap it claims to close"
                )


def test_a_unit_declines_to_set_out_after_something_past_the_leash() -> None:
    """The distance bound, applied before a chase rather than during one.

    Bounding *where the unit would end up* rather than where the quarry is
    standing is the whole subtlety: those differ by the unit's entire reach, and
    the wrong way round forbids an ember-adept from taking one step toward
    something it could then shoot from where it landed. So the adept, whose
    reach is most of the distance, still engages what the hound will not.
    """
    far = Vec2(MIDFIELD.x + PURSUIT_LEASH + 30, MIDFIELD.y)

    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound, make_unit("e", HOUND, "south", far)])
    assert [c for c in generate_candidates(look(world, hound)) if c.target_id is not None] == []

    adept = make_unit("a", ADEPT, "north", MIDFIELD)
    reaching = make_world([adept, make_unit("e", HOUND, "south", far)])
    assert [c for c in generate_candidates(look(reaching, adept)) if c.target_id is not None]
