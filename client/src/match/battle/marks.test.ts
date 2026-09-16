import { describe, expect, it } from 'vitest';

import { WISP_FLOOR_PX, markRadii, showsEnergyRing } from './marks.ts';

/**
 * The floor is in pixels, and the map is scaled to fit — so these are the tests
 * that the two facts have actually been reconciled. A regression here does not
 * look like a crash; it looks like a board that is merely slightly hard to read,
 * which is exactly the kind of thing that ships.
 */
describe('the Wisp floor', () => {
  it('draws the plate sizes when the map is at 1:1', () => {
    const radii = markRadii(1);

    expect(radii.summon).toBe(8);
    expect(radii.mage).toBe(13);
  });

  it('never lets the smallest mark fall under 16 px, however far the map shrinks', () => {
    for (const scale of [1, 0.9, 0.835, 0.6, 0.35]) {
      const radii = markRadii(scale);
      expect(radii.summon * 2 * scale).toBeGreaterThanOrEqual(WISP_FLOOR_PX - 1e-9);
    }
  });

  it('grows the marks rather than the map on a short screen', () => {
    // 375x667 with a header, the lane strip and the cast bar taking their share
    // leaves roughly this much for a 569-deep map.
    const squeezed = markRadii(475 / 569);

    expect(squeezed.summon).toBeGreaterThan(8);
  });

  it('keeps mages distinguishable from summons when the floor pushes sizes up', () => {
    const radii = markRadii(0.5);

    // The ratio is what makes "where are their mages" answerable at a glance,
    // so growing the summons must not quietly close the gap.
    expect(radii.mage / radii.summon).toBeCloseTo(13 / 8, 5);
  });

  it('falls back to the plate sizes before the map has been measured', () => {
    // A server render, or the first frame before layout. Dividing by zero here
    // would put every mark at Infinity.
    for (const unmeasured of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(markRadii(unmeasured)).toEqual({ mage: 13, summon: 8, tap: 22 });
    }
  });

  it('scales the tap target so it stays 44 px of glass', () => {
    expect(markRadii(1).tap * 2).toBe(44);
    expect(markRadii(0.5).tap * 2 * 0.5).toBe(44);
  });
});

describe('the energy ring', () => {
  it('appears only once the gauge is nearly full', () => {
    expect(showsEnergyRing(0)).toBe(false);
    expect(showsEnergyRing(0.69)).toBe(false);
    expect(showsEnergyRing(0.7)).toBe(true);
    expect(showsEnergyRing(1)).toBe(true);
  });

  it('stays off for a unit that never charges', () => {
    expect(showsEnergyRing(undefined)).toBe(false);
  });
});
