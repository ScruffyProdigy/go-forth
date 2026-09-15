/**
 * The map, in map units (JQ-311).
 *
 * These numbers mirror `THREE_ZONE_MAP` in `api/app/sim/map.py` — a 375 x 569
 * portrait lane, three zone bands, a base and a deployment strip at each end.
 * They are duplicated rather than derived because the map has to come *from the
 * server* once JQ-309 lands; a client that computed it would be a second source
 * of truth for something the sim already owns. Until then this is the fixture's
 * copy, and `test_map.py`'s numbers are the ones it has to agree with.
 *
 * World-to-screen lives here too, so the battle renderer never does arithmetic
 * on raw coordinates. JQ-312 owns making that rendering *readable* at density —
 * chips, energy rings, tap-to-inspect. This is the geometry it will need, not a
 * pre-emption of its design.
 */

import type { ZoneId } from '../plan/types.ts';
import { type MapPoint, type Side, opposing } from './types.ts';

export interface LaneSpan {
  readonly start: number;
  readonly end: number;
}

export interface ZoneGeometry {
  readonly id: ZoneId;
  readonly lane: LaneSpan;
  readonly pointsPerTick: number;
}

export interface MapGeometry {
  readonly width: number;
  readonly height: number;
  readonly zones: readonly ZoneGeometry[];
  readonly bases: Readonly<Record<Side, MapPoint>>;
  readonly baseMaxHp: number;
  readonly deployment: Readonly<Record<Side, LaneSpan>>;
}

export const THREE_ZONE_MAP: MapGeometry = {
  width: 375,
  height: 569,
  zones: [
    { id: 'A', lane: { start: 100, end: 223 }, pointsPerTick: 1 },
    { id: 'B', lane: { start: 223, end: 346 }, pointsPerTick: 1 },
    { id: 'C', lane: { start: 346, end: 469 }, pointsPerTick: 1 },
  ],
  bases: { north: { x: 187.5, y: 20 }, south: { x: 187.5, y: 549 } },
  baseMaxHp: 1000,
  deployment: { north: { start: 40, end: 100 }, south: { start: 469, end: 529 } },
};

export function zoneGeometry(map: MapGeometry, zone: ZoneId): ZoneGeometry {
  const found = map.zones.find((candidate) => candidate.id === zone);
  if (!found) throw new Error(`no zone ${zone} on map`);
  return found;
}

export function laneCentre(span: LaneSpan): number {
  return (span.start + span.end) / 2;
}

export function zoneAt(map: MapGeometry, y: number): ZoneId | null {
  const found = map.zones.find((zone) => y >= zone.lane.start && y < zone.lane.end);
  return found ? found.id : null;
}

export function distance(a: MapPoint, b: MapPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/**
 * Flips the map so the viewer's own base is always at the bottom.
 *
 * Both players are looking at the same authoritative world, but "my base is down
 * there" has to hold on both phones or the battle reads backwards on one of
 * them. Doing it as a transform keeps every coordinate in the state in the
 * server's frame; only the drawing is relative to the seat.
 */
export function toScreen(point: MapPoint, you: Side, map: MapGeometry): MapPoint {
  if (you === 'south') return point;
  return { x: map.width - point.x, y: map.height - point.y };
}

/** The inverse of `toScreen` — a tap on the map, back in the server's frame. */
export function toMap(point: MapPoint, you: Side, map: MapGeometry): MapPoint {
  return toScreen(point, you, map);
}

export function withinMap(point: MapPoint, map: MapGeometry): boolean {
  return point.x >= 0 && point.x <= map.width && point.y >= 0 && point.y <= map.height;
}

/* --------------------------------------------------------------- targets -- */

export interface TargetRegion {
  readonly id: string;
  readonly label: string;
  readonly at: MapPoint;
}

/**
 * The places a spell can be aimed: the map's own landmarks.
 *
 * Deliberately the same list an order can name — JQ-287 derives legal orders
 * from the map's zones for the same reason, so neither hard-codes "five". A
 * spell still lands at a point (the sim takes a location, not a zone id); this
 * is which points a thumb can pick on a phone.
 */
export function targetRegions(you: Side, map: MapGeometry = THREE_ZONE_MAP): TargetRegion[] {
  const them = opposing(you);
  return [
    { id: 'enemyBase', label: 'Their base', at: map.bases[them] },
    ...map.zones.map((zone) => ({
      id: `zone-${zone.id}`,
      label: `Zone ${zone.id}`,
      at: { x: map.width / 2, y: laneCentre(zone.lane) },
    })),
    { id: 'ownBase', label: 'Your base', at: map.bases[you] },
  ];
}
