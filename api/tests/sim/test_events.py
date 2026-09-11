"""The event stream envelope."""

import dataclasses

import pytest

from app.sim.events import create_event_emitter, unit_defeated
from app.sim.types import UnitRef, Vec2

HOUND = UnitRef("n-t1-u2", "n-t1", "north", "cinder-hound")
ADEPT = UnitRef("s-t1-u1", "s-t1", "south", "ember-adept")


def test_fills_a_zero_swing_so_every_event_carries_one() -> None:
    emitter = create_event_emitter()

    emitter.emit(type="unitDefeated", tick=4, position=Vec2(1, 2))

    swing = emitter.events[0].swing
    assert swing.zone_score == {"north": 0, "south": 0}
    assert swing.base_hp == {"north": 0, "south": 0}
    assert swing.units_removed == ()


def test_fills_empty_actors_so_every_event_carries_them() -> None:
    emitter = create_event_emitter()

    emitter.emit(type="unitDefeated", tick=4, position=Vec2(1, 2))

    assert emitter.events[0].actors.source is None
    assert emitter.events[0].actors.targets == ()


def test_keeps_the_tick_and_position_it_was_given() -> None:
    emitter = create_event_emitter()

    emitter.emit(type="unitDefeated", tick=9, position=Vec2(30, 120))

    assert emitter.events[0].tick == 9
    assert emitter.events[0].position == Vec2(30, 120)


def test_keeps_events_in_the_order_they_were_emitted() -> None:
    emitter = create_event_emitter()

    emitter.emit(type="unitDefeated", tick=1, position=Vec2(0, 0))
    emitter.emit(type="unitDefeated", tick=2, position=Vec2(0, 0))

    assert [event.tick for event in emitter.events] == [1, 2]


def test_freezes_what_it_emitted_so_a_later_system_cannot_rewrite_history() -> None:
    emitter = create_event_emitter()
    emitter.emit(type="unitDefeated", tick=1, position=Vec2(0, 0))

    with pytest.raises(dataclasses.FrozenInstanceError):
        emitter.events[0].tick = 99  # type: ignore[misc]


def test_hands_the_buffer_over_on_drain_and_starts_empty_again() -> None:
    emitter = create_event_emitter()
    emitter.emit(type="unitDefeated", tick=1, position=Vec2(0, 0))

    drained = emitter.drain()

    assert len(drained) == 1
    assert emitter.events == ()


def test_unit_defeated_records_the_unit_as_removed_by_the_swing() -> None:
    emitter = create_event_emitter()

    emitter.emit(**unit_defeated(tick=12, position=Vec2(5, 6), unit=HOUND, killer=ADEPT))

    event = emitter.events[0]
    assert event.type == "unitDefeated"
    assert event.swing.units_removed == (HOUND,)


def test_unit_defeated_names_the_killer_as_source_and_the_unit_as_target() -> None:
    emitter = create_event_emitter()

    emitter.emit(**unit_defeated(tick=12, position=Vec2(5, 6), unit=HOUND, killer=ADEPT))

    assert emitter.events[0].actors.source == ADEPT
    assert emitter.events[0].actors.targets == (HOUND,)


def test_unit_defeated_leaves_the_source_none_when_nothing_killed_it() -> None:
    emitter = create_event_emitter()

    emitter.emit(**unit_defeated(tick=12, position=Vec2(5, 6), unit=HOUND, killer=None))

    assert emitter.events[0].actors.source is None


def test_a_defeat_moves_neither_zone_score_nor_base_hp_on_its_own() -> None:
    emitter = create_event_emitter()

    emitter.emit(**unit_defeated(tick=12, position=Vec2(5, 6), unit=HOUND, killer=ADEPT))

    assert emitter.events[0].swing.zone_score == {"north": 0, "south": 0}
    assert emitter.events[0].swing.base_hp == {"north": 0, "south": 0}
