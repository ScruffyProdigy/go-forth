"""Generating candidates: everything legal, nothing illegal, in a stable order."""

from __future__ import annotations

from collections.abc import Sequence

from app.sim.ai.candidates import Candidate, generate_candidates
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
    # A station it is not already standing on, so the walk to it is on offer.
    hound = make_unit("h", HOUND, "north", MIDFIELD, destination=SOUTH_BASE)
    enemy = make_unit("e", HOUND, "south", Vec2(60, 320))
    world = make_world([hound, enemy], orders={"north-t0": PUSH_ENEMY_BASE})

    destinations = {
        (c.destination.x, c.destination.y)
        for c in generate_candidates(look(world, hound))
        if c.kind == "advance" and c.destination is not None
    }

    assert (SOUTH_BASE.x, SOUTH_BASE.y) in destinations
    assert (60.0, 320.0) in destinations


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


def test_no_candidate_expresses_a_retreat() -> None:
    """The three verbs cannot say "leave", and a reader will assume they can.

    A unit standing on its station, badly hurt, with enemies in contact. Every
    option is scored and the least-bad wins — but withdrawing was never one of
    them: `hold` keeps it exactly where it is, and the only `advance` on offer
    leads toward an enemy, because the station it would otherwise walk to is
    under its feet already.

    That is faithful to this ticket, which owns advance, attack, cast and hold;
    backing off belongs with positioning and bounded pursuit in JQ-329. It is
    pinned here rather than left implicit because the danger factor reads like a
    survival instinct and is not one, and because this test failing is exactly
    the signal that JQ-329 has added the missing verb.

    **Two verbs, not one, when it does.** They are different actions and want
    different execution:

    * **withdraw** — give ground while still fighting. Reduced speed, because
      backing away from something while facing it is slower than running, and
      the shooting continues.
    * **retreat** — disengage and live. Full speed, and no attacking at all.

    The first half of `withdraw` is already free: a unit with any non-attack
    intent still auto-attacks whatever is in range, so moving and firing in one
    tick works today. `retreat` is the one with no path at all — **nothing in
    the loop can currently suppress an attack.** `acquire_target` falls back to
    nearest-in-range for every intent that is not `attack`, so a retreating unit
    would keep shooting the thing it is running from. Whoever adds these needs a
    way for an intent to decline a target, and that is a change to
    `phases/targeting.py` rather than to the candidate set.
    """
    station = Vec2(180, 300)
    cornered = make_unit("h", HOUND, "north", station, hp=HOUND.max_hp / 5)
    world = make_world(
        [cornered]
        + [make_unit(f"e{i}", HOUND, "south", Vec2(station.x + 5 + i * 4, station.y)) for i in range(3)]
    )
    candidates = generate_candidates(look(world, cornered))

    assert {c.kind for c in candidates} == {"hold", "attack", "advance"}
    # The one advance leads toward an enemy, never away from the danger.
    advances = [c for c in candidates if c.kind == "advance"]
    assert all(c.target_id is not None for c in advances)
    assert all(
        min(distance(c.destination, e.position) for e in world.units if e.side == "south")
        < min(distance(station, e.position) for e in world.units if e.side == "south")
        for c in advances
        if c.destination is not None
    )
