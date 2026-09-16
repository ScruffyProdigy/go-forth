import { describe, expect, it } from 'vitest';

import {
  TWO_LANE_MAP,
  boxToScreen,
  chipBox,
  hotspotBox,
  hotspotContains,
  targetRegions,
  toMap,
  toScreen,
  zoneCentre,
  zoneContaining,
  zoneGeometry,
} from './geometry.ts';

const MAP = TWO_LANE_MAP;

/**
 * The client's map is a copy of the server's, and a copy that drifts is worse
 * than no copy: the board would draw lanes the sim is not scoring. These pin the
 * numbers against `api/app/sim/map.py`'s `TWO_LANE_MAP`, which is what
 * `api/tests/test_map.py` checks on the other side. If one of these fails,
 * the server moved and this file has to follow — not the other way round.
 */
describe('the map mirrors the sim', () => {
  it('is two lanes divided west to east, not bands stacked north to south', () => {
    expect(MAP.zones.map((zone) => zone.id)).toEqual(['W', 'E']);

    for (const zone of MAP.zones) {
      // Both lanes span the whole depth between the strips; they differ in x.
      expect(zone.lane).toEqual({ start: 100, end: 469 });
    }
    expect(MAP.zones.map((zone) => zone.extent)).toEqual([
      { start: 0, end: 160 },
      { start: 215, end: 375 },
    ]);
  });

  it('carries the sim’s dimensions, hotspot size and chip reserve', () => {
    expect(MAP.width).toBe(375);
    expect(MAP.height).toBe(569);
    expect(MAP.hotspotSize).toBe(60);
    expect(MAP.chipReserve).toEqual({ width: 115, height: 25 });
    expect(MAP.baseMaxHp).toBe(1000);
  });

  it('leaves a push corridor that belongs to no lane', () => {
    const corridor = { x: 187.5, y: 300 };

    expect(zoneContaining(MAP, corridor)).toBeNull();
  });

  it('puts both hotspots the same distance from both bases', () => {
    const [west, east] = MAP.zones.map((zone) => zoneCentre(zone));

    // The whole point of lanes: no lane is safe for one player and deep for the
    // other, so neither is free income (JQ-376).
    expect(west.y).toBe(east.y);
    expect(west.y - MAP.bases.north.y).toBeCloseTo(MAP.bases.south.y - west.y, 5);
  });
});

describe('locating a position', () => {
  it('needs both axes — a lane is a rectangle, not a band', () => {
    expect(zoneContaining(MAP, { x: 80, y: 300 })).toBe('W');
    expect(zoneContaining(MAP, { x: 300, y: 300 })).toBe('E');
    // Same depth, but in the corridor between them.
    expect(zoneContaining(MAP, { x: 190, y: 300 })).toBeNull();
    // In a lane's x, but up in the deployment strip.
    expect(zoneContaining(MAP, { x: 80, y: 60 })).toBeNull();
  });

  it('holds the hotspot to its own square, not to the lane around it', () => {
    const west = zoneGeometry(MAP, 'W');
    const centre = zoneCentre(west);

    expect(hotspotContains(MAP, west, centre)).toBe(true);
    // Still well inside the lane, nowhere near the spot.
    expect(zoneContaining(MAP, { x: 20, y: 150 })).toBe('W');
    expect(hotspotContains(MAP, west, { x: 20, y: 150 })).toBe(false);
  });

  it('keeps the chip inside its own lane rather than over the corridor', () => {
    for (const zone of MAP.zones) {
      const box = chipBox(MAP, zone);
      expect(box.x).toBeGreaterThanOrEqual(zone.extent.start);
      expect(box.x + box.width).toBeLessThanOrEqual(zone.extent.end);
    }
  });

  it('keeps every hotspot inside its lane', () => {
    for (const zone of MAP.zones) {
      const box = hotspotBox(MAP, zone);
      expect(box.x).toBeGreaterThanOrEqual(zone.extent.start);
      expect(box.x + box.width).toBeLessThanOrEqual(zone.extent.end);
      expect(box.y).toBeGreaterThanOrEqual(zone.lane.start);
      expect(box.y + box.height).toBeLessThanOrEqual(zone.lane.end);
    }
  });
});

describe('the camera', () => {
  it('leaves south’s world alone', () => {
    const point = { x: 100, y: 200 };
    expect(toScreen(point, 'south', MAP)).toEqual(point);
  });

  it('turns the board around for north rather than mirroring it', () => {
    // A mirror would flip y and leave x, reversing the board's handedness so
    // that "their east flank" meant different things on the two phones.
    expect(toScreen({ x: 100, y: 200 }, 'north', MAP)).toEqual({ x: 275, y: 369 });
  });

  it('puts each player’s own base at the bottom of their own screen', () => {
    expect(toScreen(MAP.bases.south, 'south', MAP).y).toBeGreaterThan(MAP.height / 2);
    expect(toScreen(MAP.bases.north, 'north', MAP).y).toBeGreaterThan(MAP.height / 2);
  });

  it('is its own inverse, so a tap round-trips exactly', () => {
    for (const you of ['north', 'south'] as const) {
      const point = { x: 137, y: 421 };
      expect(toMap(toScreen(point, you, MAP), you, MAP)).toEqual(point);
    }
  });

  it('moves a box’s origin corner when the board turns', () => {
    const box = { x: 0, y: 100, width: 160, height: 369 };

    expect(boxToScreen(box, 'south', MAP)).toEqual(box);
    expect(boxToScreen(box, 'north', MAP)).toEqual({ x: 215, y: 100, width: 160, height: 369 });
  });
});

describe('the places a spell can be aimed', () => {
  it('is derived from the map’s lanes, so a lane count change carries through', () => {
    const regions = targetRegions('south', MAP);

    expect(regions.map((region) => region.label)).toEqual([
      'Their base',
      'West lane',
      'East lane',
      'Your base',
    ]);
  });

  it('aims a lane at its hotspot — the thing actually being contested', () => {
    const west = targetRegions('south', MAP).find((region) => region.zone === 'W');

    expect(west?.at).toEqual(zoneCentre(zoneGeometry(MAP, 'W')));
  });

  it('points “their base” at the other seat’s base for each player', () => {
    const forSouth = targetRegions('south', MAP).find((region) => region.id === 'enemyBase');
    const forNorth = targetRegions('north', MAP).find((region) => region.id === 'enemyBase');

    expect(forSouth?.at).toEqual(MAP.bases.north);
    expect(forNorth?.at).toEqual(MAP.bases.south);
  });
});
