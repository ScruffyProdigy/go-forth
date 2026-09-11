/**
 * Plane geometry, kept to the operations IEEE-754 specifies exactly — add,
 * subtract, multiply, divide, and square root. No trigonometry and no `**` with
 * a fractional exponent: those are implementation-defined, and a battle that
 * replays differently on another Node build is not deterministic.
 */
import type { Vec2 } from './types.js';

export function distance(a: Vec2, b: Vec2): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/** Steps `from` toward `to` by at most `step`, stopping exactly on `to`. */
export function moveToward(from: Vec2, to: Vec2, step: number): Vec2 {
  const gap = distance(from, to);
  if (gap === 0 || step >= gap) {
    return { x: to.x, y: to.y };
  }
  const scale = step / gap;
  return { x: from.x + (to.x - from.x) * scale, y: from.y + (to.y - from.y) * scale };
}
