"""Generating candidates: everything legal, nothing illegal, in a stable order."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.sim.ai.candidates import Candidate, generate_candidates
from app.sim.ai.objective import PUSH_ENEMY_BASE, ObjectiveFixtures
from app.sim.map import THREE_ZONE_MAP
from app.sim.types import Vec2
from tests.sim.ai.helpers import look, make_unit, make_world
from tests.sim.fixtures_units import ADEPT, HOUND, WISP

MIDFIELD = Vec2(180, 300)
SOUTH_BASE = THREE_ZONE_MAP.bases["south"].position


@dataclass(frozen=True)
class FakeOrder:
    kind: str


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
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    enemy = make_unit("e", HOUND, "south", Vec2(60, 320))
    world = make_world([hound, enemy])

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
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    setattr(world.troops[0], "order", FakeOrder(kind="holdZone"))  # noqa: B010
    hound.destination = SOUTH_BASE

    candidates = generate_candidates(look(world, hound))

    assert kinds(candidates) == ["hold"]


def test_a_troop_pushing_the_base_does_see_it() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    setattr(world.troops[0], "order", FakeOrder(kind=PUSH_ENEMY_BASE))  # noqa: B010
    hound.destination = SOUTH_BASE

    assert "advance" in kinds(generate_candidates(look(world, hound)))


def test_a_unit_already_standing_on_its_station_is_not_offered_a_walk_to_it() -> None:
    hound = make_unit("h", HOUND, "north", MIDFIELD)
    world = make_world([hound])
    fixtures = ObjectiveFixtures(stations={"north-t0": MIDFIELD})

    assert kinds(generate_candidates(look(world, hound, fixtures))) == ["hold"]


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
