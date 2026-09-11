/**
 * The map as data.
 *
 * Zone count, each zone's depth, its horizontal extent, and its point value are
 * all map data rather than constants in the sim (design doc §4.12: "maps vary by
 * data, not by code"). A zone narrower than the map is the one variation that
 * adds a new verb — it opens a bypass lane — so `extent` is separate from the
 * map width even though v1's single map uses the full width.
 *
 * Scoring the zones is slice B (JQ-287). What lives here is the geometry and the
 * occupancy test everything else reads.
 */
import type { Side, Span, Vec2 } from './types.js';
import { SIDES } from './types.js';

export interface ZoneConfig {
  /** Short label, as the design doc's A–B–C. Data, not an enum. */
  id: string;
  /** The zone's band down the lane, north edge to south edge. */
  lane: Span;
  /** Horizontal extent. Narrower than the map width leaves a bypass lane either side. */
  extent: Span;
  /** Zone score awarded per tick to whoever holds it. */
  pointsPerTick: number;
}

export interface BaseConfig {
  position: Vec2;
  maxHp: number;
}

/** Where a side's troops are auto-placed at the start of a battle. */
export interface DeploymentStrip {
  lane: Span;
  extent: Span;
}

export interface MapConfig {
  id: string;
  size: { width: number; height: number };
  /** Ordered north to south. */
  zones: ZoneConfig[];
  bases: Record<Side, BaseConfig>;
  deployment: Record<Side, DeploymentStrip>;
}

/**
 * v1 ships one map. Dimensions follow the JQ-243 readability plates: a 375 px
 * portrait width, three 123 px zones — the measured ceiling, since four zones
 * need ~150 px each and do not fit.
 */
export const THREE_ZONE_MAP: MapConfig = {
  id: 'three-zone-lane',
  size: { width: 375, height: 569 },
  zones: [
    { id: 'A', lane: { from: 100, to: 223 }, extent: { from: 0, to: 375 }, pointsPerTick: 1 },
    { id: 'B', lane: { from: 223, to: 346 }, extent: { from: 0, to: 375 }, pointsPerTick: 1 },
    { id: 'C', lane: { from: 346, to: 469 }, extent: { from: 0, to: 375 }, pointsPerTick: 1 },
  ],
  bases: {
    north: { position: { x: 187.5, y: 20 }, maxHp: 1000 },
    south: { position: { x: 187.5, y: 549 }, maxHp: 1000 },
  },
  deployment: {
    north: { lane: { from: 40, to: 100 }, extent: { from: 0, to: 375 } },
    south: { lane: { from: 469, to: 529 }, extent: { from: 0, to: 375 } },
  },
};

function assertSpanWithin(span: Span, limit: number, what: string): void {
  if (span.from >= span.to) {
    throw new Error(`${what} has a lane span that does not run north to south`);
  }
  if (span.from < 0 || span.to > limit) {
    throw new Error(`${what} falls outside the map`);
  }
}

/** Throws unless the map is coherent. Called once, at battle start. */
export function validateMapConfig(map: MapConfig): void {
  const { width, height } = map.size;
  if (width <= 0 || height <= 0) {
    throw new Error('map size must be positive');
  }
  if (map.zones.length === 0) {
    throw new Error('map must have at least one zone');
  }

  const seen = new Set<string>();
  map.zones.forEach((zone, index) => {
    if (seen.has(zone.id)) {
      throw new Error(`map has two zones called "${zone.id}"`);
    }
    seen.add(zone.id);

    assertSpanWithin(zone.lane, height, `zone ${zone.id}`);
    assertSpanWithin(zone.extent, width, `zone ${zone.id} extent`);

    if (zone.pointsPerTick <= 0) {
      throw new Error(`zone ${zone.id} is worth no points per tick`);
    }

    const previous = map.zones[index - 1];
    if (previous && zone.lane.from < previous.lane.to) {
      throw new Error(`zones ${previous.id} and ${zone.id} overlap along the lane`);
    }
  });

  for (const side of SIDES) {
    const strip = map.deployment[side];
    assertSpanWithin(strip.lane, height, `${side} deployment strip`);
    assertSpanWithin(strip.extent, width, `${side} deployment strip extent`);

    for (const zone of map.zones) {
      if (strip.lane.from < zone.lane.to && zone.lane.from < strip.lane.to) {
        throw new Error(`${side} deployment strip overlaps zone ${zone.id}`);
      }
    }

    const base = map.bases[side];
    if (base.maxHp <= 0) {
      throw new Error(`${side} base has no HP`);
    }
    if (base.position.y < 0 || base.position.y > height) {
      throw new Error(`${side} base falls outside the map`);
    }
  }
}

function spanContains(span: Span, value: number): boolean {
  return value >= span.from && value < span.to;
}

/**
 * The zone a position sits in, or `null` for the strips, the base plates, and
 * the bypass lanes beside a narrow zone. This is the occupancy test zone scoring
 * will read, so it lives here rather than being re-derived per system.
 */
export function zoneContaining(map: MapConfig, position: Vec2): ZoneConfig | null {
  for (const zone of map.zones) {
    if (spanContains(zone.lane, position.y) && spanContains(zone.extent, position.x)) {
      return zone;
    }
  }
  return null;
}
