import { describe, expect, it } from 'vitest';

import { TWO_LANE_MAP } from '../geometry.ts';
import type { BattleUnit, MapPoint } from '../types.ts';
import { nearestUnit, pointerToMap } from './hitTest.ts';

const MAP = TWO_LANE_MAP;

/** A 375x667 phone, with the map given the height that is left over. */
const PHONE = { left: 0, top: 0, width: 375, height: 475 };

function unit(id: string, at: MapPoint): BattleUnit {
  return {
    id,
    kind: 'summon',
    side: 'north',
    typeName: 'Flame Wisp',
    position: at,
    hp: 60,
    maxHp: 60,
  };
}

describe('turning a tap into a map position', () => {
  it('undoes the letterboxing the viewBox introduces', () => {
    // 475/569 is the tighter axis, so the map is 313 px wide inside a 375 px
    // box and centred — 31 px of slack on each side. A reader that ignored the
    // slack would land every tap about a tenth of the board to the left.
    const scale = Math.min(PHONE.width / MAP.width, PHONE.height / MAP.height);
    const slack = (PHONE.width - MAP.width * scale) / 2;

    const centre = pointerToMap(slack + (MAP.width * scale) / 2, PHONE.height / 2, PHONE, MAP, 'south');

    expect(centre?.x).toBeCloseTo(MAP.width / 2, 5);
    expect(centre?.y).toBeCloseTo(MAP.height / 2, 5);
  });

  it('takes the tap back through the camera, so north taps its own screen', () => {
    // The top-left corner of the *drawn map* — not of the element, which has
    // letterbox slack either side of it — is the south-east corner of the world
    // for north. A reader that skipped the camera would inspect the wrong army.
    const scale = Math.min(PHONE.width / MAP.width, PHONE.height / MAP.height);
    const slack = (PHONE.width - MAP.width * scale) / 2;

    const corner = pointerToMap(PHONE.left + slack, PHONE.top, PHONE, MAP, 'north');

    expect(corner?.x).toBeCloseTo(MAP.width, 5);
    expect(corner?.y).toBeCloseTo(MAP.height, 5);
  });

  it('declines to place a tap before the map has been laid out', () => {
    expect(pointerToMap(10, 10, { left: 0, top: 0, width: 0, height: 0 }, MAP, 'south')).toBeNull();
  });

  it('accounts for where the map sits on the page', () => {
    const offset = { left: 40, top: 120, width: 375, height: 475 };
    const scale = Math.min(offset.width / MAP.width, offset.height / MAP.height);
    const slack = (offset.width - MAP.width * scale) / 2;

    const topLeft = pointerToMap(offset.left + slack, offset.top, offset, MAP, 'south');

    expect(topLeft?.x).toBeCloseTo(0, 5);
    expect(topLeft?.y).toBeCloseTo(0, 5);
  });
});

describe('picking the unit a thumb meant', () => {
  const units = [unit('near', { x: 100, y: 100 }), unit('far', { x: 300, y: 300 })];

  it('takes the nearest one inside the tap radius', () => {
    expect(nearestUnit(units, { x: 110, y: 105 }, 22)?.id).toBe('near');
  });

  it('returns nothing for a tap on empty ground, rather than the least-far unit', () => {
    // Tapping the board to dismiss the panel has to work; snapping to whatever
    // is nearest on the whole map would make that impossible.
    expect(nearestUnit(units, { x: 200, y: 500 }, 22)).toBeNull();
  });

  it('resolves a tie by array order rather than by iteration order', () => {
    const stacked = [unit('first', { x: 50, y: 50 }), unit('second', { x: 50, y: 50 })];

    expect(nearestUnit(stacked, { x: 50, y: 50 }, 22)?.id).toBe('first');
  });

  it('finds a unit in a crowd that no single mark is a 44 px target in', () => {
    // Twenty a side, packed at the JQ-243 density: the tap still resolves.
    const crowd = Array.from({ length: 20 }, (_, index) =>
      unit(`u${index}`, { x: 40 + index * 6, y: 200 }),
    );

    expect(nearestUnit(crowd, { x: 41, y: 202 }, 22)?.id).toBe('u0');
  });
});
