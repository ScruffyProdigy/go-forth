/** Shared vocabulary: the handful of types every sim module speaks in. */

/** The two sides of the map. Portrait orientation, so north is the top of the screen. */
export type Side = 'north' | 'south';

export const SIDES: readonly Side[] = ['north', 'south'] as const;

/** The opposing side. */
export function opposing(side: Side): Side {
  return side === 'north' ? 'south' : 'north';
}

/** A point in map space. Map space is portrait: `y` runs down the lane, north to south. */
export interface Vec2 {
  readonly x: number;
  readonly y: number;
}

/** An inclusive interval along one axis. */
export interface Span {
  from: number;
  to: number;
}

export type UnitId = string;
export type TroopId = string;

/**
 * How a unit appears in the event stream: enough to identify it without holding
 * a reference to mutable state, so a drained stream stays readable after the
 * battle has moved on.
 */
export interface UnitRef {
  readonly unitId: UnitId;
  readonly troopId: TroopId;
  readonly side: Side;
  readonly typeId: string;
}
