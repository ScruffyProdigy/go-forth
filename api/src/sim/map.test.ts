import { describe, expect, it } from 'vitest';

import { THREE_ZONE_MAP, validateMapConfig, zoneContaining, type MapConfig } from './map.js';

function cloneMap(): MapConfig {
  return structuredClone(THREE_ZONE_MAP);
}

describe('THREE_ZONE_MAP', () => {
  it('is valid map data', () => {
    expect(() => validateMapConfig(THREE_ZONE_MAP)).not.toThrow();
  });

  it('lays three zones in a line down the lane', () => {
    const zones = THREE_ZONE_MAP.zones;

    expect(zones).toHaveLength(3);
    expect(zones[0].lane.to).toBeLessThanOrEqual(zones[1].lane.from);
    expect(zones[1].lane.to).toBeLessThanOrEqual(zones[2].lane.from);
  });

  it('gives each side one base, at opposite ends of the lane', () => {
    const { north, south } = THREE_ZONE_MAP.bases;

    expect(north.position.y).toBeLessThan(south.position.y);
    expect(north.maxHp).toBeGreaterThan(0);
    expect(south.maxHp).toBeGreaterThan(0);
  });

  it('puts a deployment strip between each base and the nearest zone', () => {
    const { north, south } = THREE_ZONE_MAP.deployment;
    const firstZone = THREE_ZONE_MAP.zones[0];
    const lastZone = THREE_ZONE_MAP.zones[THREE_ZONE_MAP.zones.length - 1];

    expect(north.lane.from).toBeGreaterThanOrEqual(THREE_ZONE_MAP.bases.north.position.y);
    expect(north.lane.to).toBeLessThanOrEqual(firstZone.lane.from);
    expect(south.lane.from).toBeGreaterThanOrEqual(lastZone.lane.to);
    expect(south.lane.to).toBeLessThanOrEqual(THREE_ZONE_MAP.bases.south.position.y);
  });
});

describe('validateMapConfig', () => {
  it('rejects a map with no zones', () => {
    const map = cloneMap();
    map.zones = [];

    expect(() => validateMapConfig(map)).toThrow(/at least one zone/i);
  });

  it('rejects zones that overlap along the lane', () => {
    const map = cloneMap();
    map.zones[1].lane.from = map.zones[0].lane.to - 10;

    expect(() => validateMapConfig(map)).toThrow(/overlap/i);
  });

  it('rejects a zone that runs off the map', () => {
    const map = cloneMap();
    map.zones[2].lane.to = map.size.height + 1;

    expect(() => validateMapConfig(map)).toThrow(/outside the map/i);
  });

  it('rejects a deployment strip that overlaps a zone', () => {
    const map = cloneMap();
    map.deployment.north.lane.to = map.zones[0].lane.to;

    expect(() => validateMapConfig(map)).toThrow(/deployment strip/i);
  });

  it('rejects a zone worth no points', () => {
    const map = cloneMap();
    map.zones[0].pointsPerTick = 0;

    expect(() => validateMapConfig(map)).toThrow(/points/i);
  });
});

describe('zoneContaining', () => {
  it('names the zone a position sits in', () => {
    const zone = THREE_ZONE_MAP.zones[1];
    const middle = {
      x: (zone.extent.from + zone.extent.to) / 2,
      y: (zone.lane.from + zone.lane.to) / 2,
    };

    expect(zoneContaining(THREE_ZONE_MAP, middle)?.id).toBe(zone.id);
  });

  it('returns null in the deployment strip, which is no zone', () => {
    const strip = THREE_ZONE_MAP.deployment.north;
    const inStrip = { x: THREE_ZONE_MAP.size.width / 2, y: (strip.lane.from + strip.lane.to) / 2 };

    expect(zoneContaining(THREE_ZONE_MAP, inStrip)).toBeNull();
  });

  it('returns null beside a zone that is narrower than the map — the bypass lane', () => {
    const map = cloneMap();
    map.zones[1].extent = { from: 100, to: 275 };
    const zone = map.zones[1];
    const besideIt = { x: 20, y: (zone.lane.from + zone.lane.to) / 2 };

    expect(zoneContaining(map, besideIt)).toBeNull();
  });
});
