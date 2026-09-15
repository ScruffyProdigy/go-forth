"""The map as data — geometry, validation, and the occupancy test."""

import copy

import pytest

from app.sim.map import (
    TWO_LANE_MAP,
    MapConfig,
    chip_box,
    clear_of_chip,
    hotspot_contains,
    validate_map_config,
    zone_by_id,
    zone_centre,
    zone_containing,
)
from app.sim.types import Span, Vec2


@pytest.fixture
def a_map() -> MapConfig:
    return copy.deepcopy(TWO_LANE_MAP)


def test_the_shipped_map_is_valid() -> None:
    validate_map_config(TWO_LANE_MAP)


def test_two_lanes_lie_side_by_side_divided_west_to_east() -> None:
    zones = TWO_LANE_MAP.zones

    assert len(zones) == 2
    assert zones[0].extent.end <= zones[1].extent.start
    assert zones[0].lane == zones[1].lane


def test_the_gap_between_the_lanes_is_the_push_corridor() -> None:
    west, east = TWO_LANE_MAP.zones
    corridor = Span(west.extent.end, east.extent.start)
    middle = TWO_LANE_MAP.bases["north"].position.x

    assert corridor.start < middle < corridor.end


def test_every_lane_is_the_same_distance_from_both_bases() -> None:
    """The reason for turning the zones ninety degrees: no lane is safe for one
    player and deep for the other, so there is no free income to farm."""
    north = TWO_LANE_MAP.bases["north"].position.y
    south = TWO_LANE_MAP.bases["south"].position.y

    for zone in TWO_LANE_MAP.zones:
        point = zone_centre(zone)
        assert abs(point.y - north) == abs(point.y - south)


def test_each_side_has_one_base_at_opposite_ends() -> None:
    north = TWO_LANE_MAP.bases["north"]
    south = TWO_LANE_MAP.bases["south"]

    assert north.position.y < south.position.y
    assert north.max_hp > 0
    assert south.max_hp > 0


def test_a_deployment_strip_sits_between_each_base_and_the_nearest_zone() -> None:
    north = TWO_LANE_MAP.deployment["north"]
    south = TWO_LANE_MAP.deployment["south"]

    assert north.lane.start >= TWO_LANE_MAP.bases["north"].position.y
    assert north.lane.end <= TWO_LANE_MAP.zones[0].lane.start
    assert south.lane.start >= TWO_LANE_MAP.zones[-1].lane.end
    assert south.lane.end <= TWO_LANE_MAP.bases["south"].position.y


def test_rejects_a_map_with_no_zones(a_map: MapConfig) -> None:
    a_map.zones = []

    with pytest.raises(ValueError, match="at least one zone"):
        validate_map_config(a_map)


def test_rejects_zones_that_overlap_as_rectangles(a_map: MapConfig) -> None:
    a_map.zones[1].extent.start = a_map.zones[0].extent.end - 10

    with pytest.raises(ValueError, match="overlap"):
        validate_map_config(a_map)


def test_sharing_a_lane_span_is_not_an_overlap(a_map: MapConfig) -> None:
    """Lanes run side by side down the whole map, so they share their entire
    depth. Only sharing both axes is a conflict."""
    assert a_map.zones[0].lane == a_map.zones[1].lane

    validate_map_config(a_map)


def test_rejects_a_zone_too_narrow_for_its_hotspot(a_map: MapConfig) -> None:
    a_map.zones[0].extent = Span(start=0, end=a_map.hotspot_size - 1)

    with pytest.raises(ValueError, match="narrower than its hotspot"):
        validate_map_config(a_map)


def test_rejects_a_hotspot_bigger_than_the_lane_is_deep(a_map: MapConfig) -> None:
    lane = a_map.zones[0].lane
    a_map.zones[0].extent = Span(start=0, end=a_map.size_width)
    a_map.hotspot_size = lane.end - lane.start + 1

    with pytest.raises(ValueError, match="shallower than its hotspot"):
        validate_map_config(a_map)


def test_rejects_a_hotspot_with_no_size(a_map: MapConfig) -> None:
    a_map.hotspot_size = 0

    with pytest.raises(ValueError, match="positive size"):
        validate_map_config(a_map)


def test_rejects_a_zone_that_runs_off_the_map(a_map: MapConfig) -> None:
    a_map.zones[-1].lane.end = a_map.size_height + 1

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
    zone = TWO_LANE_MAP.zones[1]
    middle = Vec2(
        x=(zone.extent.start + zone.extent.end) / 2,
        y=(zone.lane.start + zone.lane.end) / 2,
    )

    found = zone_containing(TWO_LANE_MAP, middle)
    assert found is not None
    assert found.id == zone.id


def test_the_deployment_strip_is_no_zone() -> None:
    strip = TWO_LANE_MAP.deployment["north"]
    in_strip = Vec2(x=TWO_LANE_MAP.size_width / 2, y=(strip.lane.start + strip.lane.end) / 2)

    assert zone_containing(TWO_LANE_MAP, in_strip) is None


def test_the_push_corridor_between_the_lanes_is_no_zone() -> None:
    """Walking up the middle at the enemy base means walking outside both lanes,
    which is why Push is not a way of holding one."""
    west, east = TWO_LANE_MAP.zones
    between = Vec2(
        x=(west.extent.end + east.extent.start) / 2,
        y=(west.lane.start + west.lane.end) / 2,
    )

    assert zone_containing(TWO_LANE_MAP, between) is None


def test_a_hotspot_sits_at_the_centre_of_its_own_lane() -> None:
    for zone in TWO_LANE_MAP.zones:
        assert hotspot_contains(TWO_LANE_MAP, zone, zone_centre(zone))


def test_a_hotspot_is_a_small_part_of_the_lane_it_scores() -> None:
    """Small enough that it cannot be denied by lurking: a straggler in the
    corner of a 369-deep lane is not standing on it."""
    zone = TWO_LANE_MAP.zones[0]
    lane_area = (zone.extent.end - zone.extent.start) * (zone.lane.end - zone.lane.start)

    assert TWO_LANE_MAP.hotspot_size**2 < lane_area / 10


def test_a_corner_of_the_lane_is_not_the_hotspot() -> None:
    zone = TWO_LANE_MAP.zones[0]

    assert not hotspot_contains(TWO_LANE_MAP, zone, Vec2(zone.extent.start, zone.lane.start))


def test_a_zone_is_found_by_its_id() -> None:
    assert zone_by_id(TWO_LANE_MAP, "E") is TWO_LANE_MAP.zones[1]


def test_naming_a_zone_the_map_does_not_have_is_an_error_not_an_empty_answer() -> None:
    with pytest.raises(ValueError, match="no zone"):
        zone_by_id(TWO_LANE_MAP, "Z")


def test_the_middle_of_a_zone_is_the_middle_of_both_its_spans() -> None:
    zone = TWO_LANE_MAP.zones[0]

    assert zone_centre(zone) == Vec2(
        (zone.extent.start + zone.extent.end) / 2,
        (zone.lane.start + zone.lane.end) / 2,
    )


def test_the_chip_corner_sits_at_the_top_left_of_the_zone_band() -> None:
    zone = TWO_LANE_MAP.zones[1]
    across, down = chip_box(TWO_LANE_MAP, zone)

    assert (across.start, down.start) == (zone.extent.start, zone.lane.start)
    assert across.end - across.start == TWO_LANE_MAP.chip_reserve.width
    assert down.end - down.start == TWO_LANE_MAP.chip_reserve.height


def test_the_chip_corner_follows_a_narrow_zone_rather_than_floating_over_the_bypass(
    a_map: MapConfig,
) -> None:
    a_map.zones[1].extent = Span(start=100, end=275)
    across, _ = chip_box(a_map, a_map.zones[1])

    assert across.start == 100


def test_a_spot_in_the_chip_corner_is_moved_out_of_it() -> None:
    zone = TWO_LANE_MAP.zones[0]
    across, down = chip_box(TWO_LANE_MAP, zone)
    inside = Vec2(across.start + 1, down.start + 1)

    moved = clear_of_chip(TWO_LANE_MAP, zone, inside)

    assert not (across.start <= moved.x < across.end and down.start <= moved.y < down.end)


def test_a_spot_outside_the_chip_corner_is_left_alone() -> None:
    zone = TWO_LANE_MAP.zones[0]
    spot = zone_centre(zone)

    assert clear_of_chip(TWO_LANE_MAP, zone, spot) == spot


def test_rejects_a_base_with_a_negative_footprint(a_map: MapConfig) -> None:
    a_map.bases["north"].footprint_radius = -1

    with pytest.raises(ValueError, match="footprint"):
        validate_map_config(a_map)


def test_rejects_a_negative_chip_reserve(a_map: MapConfig) -> None:
    a_map.chip_reserve.height = -1

    with pytest.raises(ValueError, match="chip reserve"):
        validate_map_config(a_map)
