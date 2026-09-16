/**
 * Turning a tap into a unit (JQ-312 AC 2).
 *
 * Tap-to-inspect replaced per-unit health bars, which means a tap has to find
 * its unit reliably — and at twenty a side no mark is anywhere near a 44 px
 * target. Asking a thumb to land on a 16 px circle is asking it to miss, so a
 * tap anywhere on the board resolves to the *nearest* unit within a radius
 * derived from the tap-target floor rather than from the mark's own size.
 *
 * Kept out of the component file so both halves can be tested without rendering
 * anything, which is the only way the coordinate maths is checkable at all.
 */

import { type MapGeometry, distance, toMap } from '../geometry.ts';
import type { BattleUnit, MapPoint, Side } from '../types.ts';

/**
 * A client-space point, back in the sim's frame. Null if the map has no size
 * yet — before layout, a tap cannot be placed and guessing would place it wrong.
 */
export function pointerToMap(
  clientX: number,
  clientY: number,
  rect: { readonly left: number; readonly top: number; readonly width: number; readonly height: number },
  map: MapGeometry,
  you: Side,
): MapPoint | null {
  if (rect.width === 0 || rect.height === 0) return null;

  // Undo `xMidYMid meet`: the viewBox is scaled to the tighter axis and centred
  // in the other, so the slack has to come off before the scale is divided out.
  const scale = Math.min(rect.width / map.width, rect.height / map.height);
  const offsetX = (rect.width - map.width * scale) / 2;
  const offsetY = (rect.height - map.height * scale) / 2;

  const onScreen = {
    x: (clientX - rect.left - offsetX) / scale,
    y: (clientY - rect.top - offsetY) / scale,
  };

  // Back through the camera: what the thumb touched is in screen space, and
  // every unit's position is in the server's.
  return toMap(onScreen, you, map);
}

export function nearestUnit(
  units: readonly BattleUnit[],
  at: MapPoint,
  within: number,
): BattleUnit | null {
  let best: BattleUnit | null = null;
  let bestGap = within;

  // Index order with a strict `<`, so a tie resolves by position in the array
  // rather than by iteration order — the same rule the sim lives by.
  for (const unit of units) {
    const gap = distance(unit.position, at);
    if (gap < bestGap) {
      best = unit;
      bestGap = gap;
    }
  }

  return best;
}
