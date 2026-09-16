/**
 * The map, in map units (JQ-311, corrected for JQ-376 by JQ-312).
 *
 * These numbers mirror `TWO_LANE_MAP` in `api/app/sim/map.py` — a 375 x 569
 * portrait board, **two lanes divided west to east** with a push corridor
 * between them, a hotspot at the centre of each lane, and a base and deployment
 * strip at each end. They are duplicated rather than derived because the map has
 * to come *from the server* once JQ-309 lands; a client that computed it would
 * be a second source of truth for something the sim already owns. Until then
 * this is the fixture's copy, and `test_map.py`'s numbers are the ones it has to
 * agree with.
 *
 * It used to be `THREE_ZONE_MAP`: three bands stacked *across* the attack axis.
 * JQ-376 deleted that server-side — bands stacked north to south gave each side
 * a zone next to its own deployment strip that the enemy never reached, so
 * farming it beat playing the game. The client had not caught up, which meant
 * the battle screen was drawing a map the sim no longer produces. Two facts
 * about the replacement matter to a renderer and are why this is not a rename:
 *
 *  1. **A zone is a rectangle, not a band.** It has an extent across the map as
 *     well as a depth down it, so nothing may assume a zone spans the full
 *     width — the corridor between the lanes belongs to neither.
 *  2. **Scoring happens on the hotspot, not in the zone.** Holding is a mage
 *     standing in a small square at the lane's centre, so the hotspot has to be
 *     on screen: a board that drew only the lane would not show the thing the
 *     round is actually being decided on.
 *
 * World-to-screen lives here too, so the battle renderer never does arithmetic
 * on raw coordinates.
 */

import type { ZoneId } from '../plan/types.ts';
import { type MapPoint, type Side, opposing } from './types.ts';

/** A half-open interval, as the sim's `Span`. */
export interface Span {
  readonly start: number;
  readonly end: number;
}

export interface ZoneGeometry {
  readonly id: ZoneId;
  /** How far down the map the lane runs, north edge to south edge. */
  readonly lane: Span;
  /** The lane's width. The gap between two lanes is the push corridor. */
  readonly extent: Span;
  readonly pointsPerTick: number;
}

export interface DeploymentStrip {
  readonly lane: Span;
  readonly extent: Span;
}

/**
 * The corner of a zone the sim reserves for that zone's state chip.
 *
 * JQ-287 routes unit placement around this box, so the renderer has to draw the
 * chip in the *same* box rather than wherever is convenient on screen — the two
 * agreeing is the only reason army size can never occlude a chip.
 */
export interface ChipReserve {
  readonly width: number;
  readonly height: number;
}

export interface MapGeometry {
  readonly width: number;
  readonly height: number;
  readonly zones: readonly ZoneGeometry[];
  readonly bases: Readonly<Record<Side, MapPoint>>;
  readonly baseMaxHp: number;
  readonly baseFootprintRadius: number;
  readonly deployment: Readonly<Record<Side, DeploymentStrip>>;
  readonly chipReserve: ChipReserve;
  /** Side of the square at a lane's centre a mage must stand in to hold it. */
  readonly hotspotSize: number;
}

export const TWO_LANE_MAP: MapGeometry = {
  width: 375,
  height: 569,
  zones: [
    { id: 'W', lane: { start: 100, end: 469 }, extent: { start: 0, end: 160 }, pointsPerTick: 1 },
    { id: 'E', lane: { start: 100, end: 469 }, extent: { start: 215, end: 375 }, pointsPerTick: 1 },
  ],
  bases: { north: { x: 187.5, y: 20 }, south: { x: 187.5, y: 549 } },
  baseMaxHp: 1000,
  baseFootprintRadius: 24,
  deployment: {
    north: { lane: { start: 40, end: 100 }, extent: { start: 0, end: 375 } },
    south: { lane: { start: 469, end: 529 }, extent: { start: 0, end: 375 } },
  },
  chipReserve: { width: 115, height: 25 },
  hotspotSize: 60,
};

/** Human-readable lane names. The ids stay the sim's single letters. */
export const ZONE_NAME: Readonly<Record<ZoneId, string>> = { W: 'West', E: 'East' };

export function zoneGeometry(map: MapGeometry, zone: ZoneId): ZoneGeometry {
  const found = map.zones.find((candidate) => candidate.id === zone);
  if (!found) throw new Error(`no zone ${zone} on map`);
  return found;
}

export function spanCentre(span: Span): number {
  return (span.start + span.end) / 2;
}

export function spanContains(span: Span, value: number): boolean {
  return value >= span.start && value < span.end;
}

/** The middle of a lane. Its hotspot sits here. */
export function zoneCentre(zone: ZoneGeometry): MapPoint {
  return { x: spanCentre(zone.extent), y: spanCentre(zone.lane) };
}

/**
 * The zone a position sits in, or null for the corridor, the strips and the
 * base plates. Both axes, because a lane no longer spans the map's width.
 */
export function zoneContaining(map: MapGeometry, point: MapPoint): ZoneId | null {
  const found = map.zones.find(
    (zone) => spanContains(zone.lane, point.y) && spanContains(zone.extent, point.x),
  );
  return found ? found.id : null;
}

/* --------------------------------------------------------------- hotspot -- */

export interface Box {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** The square that has to be stood in to hold this lane. */
export function hotspotBox(map: MapGeometry, zone: ZoneGeometry): Box {
  const centre = zoneCentre(zone);
  const reach = map.hotspotSize / 2;
  return {
    x: centre.x - reach,
    y: centre.y - reach,
    width: map.hotspotSize,
    height: map.hotspotSize,
  };
}

export function hotspotContains(map: MapGeometry, zone: ZoneGeometry, point: MapPoint): boolean {
  const box = hotspotBox(map, zone);
  return (
    spanContains({ start: box.x, end: box.x + box.width }, point.x) &&
    spanContains({ start: box.y, end: box.y + box.height }, point.y)
  );
}

/**
 * The reserved corner of a zone, in *map* coordinates.
 *
 * Deliberately not "the top-left of the band on screen": JQ-287 clears units out
 * of this world-space box, and a renderer that anchored the chip to a screen
 * corner instead would put it somewhere units are still allowed to stand.
 */
export function chipBox(map: MapGeometry, zone: ZoneGeometry): Box {
  return {
    x: zone.extent.start,
    y: zone.lane.start,
    width: Math.min(map.chipReserve.width, zone.extent.end - zone.extent.start),
    height: map.chipReserve.height,
  };
}

export function distance(a: MapPoint, b: MapPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/* ---------------------------------------------------------------- camera -- */

/**
 * Flips the map so the viewer's own base is always at the bottom.
 *
 * Both players are looking at the same authoritative world, but "my base is down
 * there" has to hold on both phones or the battle reads backwards on one of
 * them. Doing it as a transform keeps every coordinate in the state in the
 * server's frame; only the drawing is relative to the seat.
 *
 * It is a 180-degree *rotation*, not a vertical mirror, which is why x flips
 * too: turning the board around is what the second player is doing, and a mirror
 * would reverse the board's handedness so that a move described as "round their
 * east flank" meant two different things on the two phones. The cost is that
 * world-west draws on the right of north's screen — which is why the lane chips
 * carry their name and the map does not rely on which side of the glass a lane
 * appears.
 */
export function toScreen(point: MapPoint, you: Side, map: MapGeometry): MapPoint {
  if (you === 'south') return point;
  return { x: map.width - point.x, y: map.height - point.y };
}

/** The inverse of `toScreen` — a tap on the map, back in the server's frame. */
export function toMap(point: MapPoint, you: Side, map: MapGeometry): MapPoint {
  return toScreen(point, you, map);
}

/** A whole box through the camera. Rotating one moves its origin corner. */
export function boxToScreen(box: Box, you: Side, map: MapGeometry): Box {
  if (you === 'south') return box;
  return {
    x: map.width - (box.x + box.width),
    y: map.height - (box.y + box.height),
    width: box.width,
    height: box.height,
  };
}

export function withinMap(point: MapPoint, map: MapGeometry): boolean {
  return point.x >= 0 && point.x <= map.width && point.y >= 0 && point.y <= map.height;
}

/* --------------------------------------------------------------- targets -- */

export interface TargetRegion {
  readonly id: string;
  readonly label: string;
  readonly at: MapPoint;
  /** The zone this region is, for the regions that are one. */
  readonly zone?: ZoneId;
}

/**
 * The places a spell can be aimed: the map's own landmarks.
 *
 * Deliberately the same list an order can name — JQ-287 derives legal orders
 * from the map's zones for the same reason, so neither hard-codes a count. A
 * spell still lands at a point (the sim takes a location, not a zone id); this
 * is which points a thumb can pick on a phone.
 *
 * A lane's point is its **hotspot**, not its geometric middle by area, because
 * the hotspot is where the fight for the lane actually happens — aiming at a
 * lane means aiming at the thing being contested in it.
 */
export function targetRegions(you: Side, map: MapGeometry = TWO_LANE_MAP): TargetRegion[] {
  const them = opposing(you);
  return [
    { id: 'enemyBase', label: 'Their base', at: map.bases[them] },
    ...map.zones.map((zone) => ({
      id: `zone-${zone.id}`,
      label: `${ZONE_NAME[zone.id]} lane`,
      at: zoneCentre(zone),
      zone: zone.id,
    })),
    { id: 'ownBase', label: 'Your base', at: map.bases[you] },
  ];
}
