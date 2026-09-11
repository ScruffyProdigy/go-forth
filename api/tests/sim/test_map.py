"""The map as data — geometry, validation, and the occupancy test."""

import copy

import pytest

from app.sim.map import (
    THREE_ZONE_MAP,
    MapConfig,
    validate_map_config,
    zone_containing,
)
from app.sim.types import Span, Vec2


@pytest.fixture
def a_map() -> MapConfig:
    return copy.deepcopy(THREE_ZONE_MAP)


def test_the_shipped_map_is_valid() -> None:
    validate_map_config(THREE_ZONE_MAP)


def test_three_zones_lie_in_a_line_down_the_lane() -> None:
    zones = THREE_ZONE_MAP.zones

    assert len(zones) == 3
    assert zones[0].lane.end <= zones[1].lane.start
    assert zones[1].lane.end <= zones[2].lane.start


def test_each_side_has_one_base_at_opposite_ends() -> None:
    north = THREE_ZONE_MAP.bases["north"]
    south = THREE_ZONE_MAP.bases["south"]

    assert north.position.y < south.position.y
    assert north.max_hp > 0
    assert south.max_hp > 0


def test_a_deployment_strip_sits_between_each_base_and_the_nearest_zone() -> None:
    north = THREE_ZONE_MAP.deployment["north"]
    south = THREE_ZONE_MAP.deployment["south"]

    assert north.lane.start >= THREE_ZONE_MAP.bases["north"].position.y
    assert north.lane.end <= THREE_ZONE_MAP.zones[0].lane.start
    assert south.lane.start >= THREE_ZONE_MAP.zones[-1].lane.end
    assert south.lane.end <= THREE_ZONE_MAP.bases["south"].position.y


def test_rejects_a_map_with_no_zones(a_map: MapConfig) -> None:
    a_map.zones = []

    with pytest.raises(ValueError, match="at least one zone"):
        validate_map_config(a_map)


def test_rejects_zones_that_overlap_along_the_lane(a_map: MapConfig) -> None:
    a_map.zones[1].lane.start = a_map.zones[0].lane.end - 10

    with pytest.raises(ValueError, match="overlap"):
        validate_map_config(a_map)


def test_rejects_a_zone_that_runs_off_the_map(a_map: MapConfig) -> None:
    a_map.zones[2].lane.end = a_map.size_height + 1

    with pytest.raises(ValueError, match="outside the map"):
        validate_map_config(a_map)


def test_rejects_a_deployment_strip_that_overlaps_a_zone(a_map: MapConfig) -> None:
    a_map.deployment["north"].lane.end = a_map.zones[0].lane.end

    with pytest.raises(ValueError, match="deployment strip"):
        validate_map_config(a_map)


def test_rejects_a_zone_worth_no_points(a_map: MapConfig) -> None:
    a_map.zones[0].points_per_tick = 0

    with pytest.raises(ValueError, match="points"):
        validate_map_config(a_map)


def test_names_the_zone_a_position_sits_in() -> None:
    zone = THREE_ZONE_MAP.zones[1]
    middle = Vec2(
        x=(zone.extent.start + zone.extent.end) / 2,
        y=(zone.lane.start + zone.lane.end) / 2,
    )

    found = zone_containing(THREE_ZONE_MAP, middle)
    assert found is not None
    assert found.id == zone.id


def test_the_deployment_strip_is_no_zone() -> None:
    strip = THREE_ZONE_MAP.deployment["north"]
    in_strip = Vec2(x=THREE_ZONE_MAP.size_width / 2, y=(strip.lane.start + strip.lane.end) / 2)

    assert zone_containing(THREE_ZONE_MAP, in_strip) is None


def test_beside_a_narrow_zone_is_the_bypass_lane(a_map: MapConfig) -> None:
    a_map.zones[1].extent = Span(start=100, end=275)
    zone = a_map.zones[1]
    beside_it = Vec2(x=20, y=(zone.lane.start + zone.lane.end) / 2)

    assert zone_containing(a_map, beside_it) is None
