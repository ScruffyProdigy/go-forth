/**
 * How big a ground mark is drawn (JQ-312 AC 2).
 *
 * The map is a fixed viewBox scaled to fit the phone, so a radius in map units
 * is *not* a size on glass: the same 8-unit Wisp is 16 px on a 375-wide screen
 * showing the map at 1:1 and 13 px once the map has to shrink to leave room for
 * the cast bar. JQ-243's finding is a floor in **pixels** — below about 16 px
 * across, a mark stops being a thing you can count and becomes texture — so the
 * floor has to be applied after the scale is known, which is what this is for.
 *
 * The consequence is deliberate: on a short screen the marks grow in map units
 * rather than the map growing. Twenty a side drawn slightly too large overlap
 * and read as a crowd, which is true; drawn too small they read as noise, which
 * is not.
 */

/** JQ-243: the smallest mark that can still be counted on a phone. */
export const WISP_FLOOR_PX = 16;

/** A tap target below this is not reliably hittable with a thumb. */
export const TAP_TARGET_PX = 44;

/**
 * The JQ-243 plate sizes at 1:1 — mages 26 px across, summons 16 px. The ratio
 * between them is what makes "where are their mages" answerable at a glance, so
 * it is preserved when the floor forces the marks up.
 */
const NOMINAL_SUMMON_RADIUS = 8;
const NOMINAL_MAGE_RADIUS = 13;
const MAGE_TO_SUMMON = NOMINAL_MAGE_RADIUS / NOMINAL_SUMMON_RADIUS;

export interface MarkRadii {
  readonly mage: number;
  readonly summon: number;
  /** The invisible circle that catches a tap, in map units. */
  readonly tap: number;
}

/**
 * Mark radii in map units, for a map drawn at `scale` pixels per map unit.
 *
 * A scale of 0 or less means the map has not been measured yet (a server render,
 * or the first frame before layout). The nominal sizes are used then rather than
 * dividing by zero — the first painted frame is briefly at the plate sizes and
 * corrects on layout, which is invisible and strictly better than not drawing.
 */
export function markRadii(scale: number): MarkRadii {
  if (!Number.isFinite(scale) || scale <= 0) {
    return {
      mage: NOMINAL_MAGE_RADIUS,
      summon: NOMINAL_SUMMON_RADIUS,
      tap: TAP_TARGET_PX / 2,
    };
  }

  const summon = Math.max(NOMINAL_SUMMON_RADIUS, WISP_FLOOR_PX / 2 / scale);
  return {
    mage: Math.max(NOMINAL_MAGE_RADIUS, summon * MAGE_TO_SUMMON),
    summon,
    tap: TAP_TARGET_PX / 2 / scale,
  };
}

/**
 * Whether a mage's energy ring is drawn.
 *
 * Above about 70% only. A ring on every mage all round is chrome you stop
 * seeing; a ring that appears shortly before the ability fires is a warning, and
 * the point of drawing it at all is that the other player gets the same warning
 * about yours.
 */
export const RING_THRESHOLD = 0.7;

export function showsEnergyRing(charge: number | undefined): boolean {
  return charge !== undefined && charge >= RING_THRESHOLD;
}
