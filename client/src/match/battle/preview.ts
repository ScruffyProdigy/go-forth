/**
 * What a spell would do, honestly (JQ-312 AC 4).
 *
 * The rule this file exists to enforce: **never infer a clear from enemy count
 * alone.** "Three of them are in the blast" is not "the blast kills three", and
 * the difference is where a player loses a round they thought they had won. So a
 * preview here is computed from the things that actually decide it — the
 * resolved magnitude, each target's current health and protection, whether the
 * spell is eligible, and whether it is affordable — and every one of those it
 * does *not* know is represented as not knowing rather than defaulted.
 *
 * Concretely: a unit whose protection the server did not state is `unknown`, not
 * `defeated`. A lane is only reported as cleared when every living enemy in it
 * is inside the blast, all of them would be reduced to nothing, and none of them
 * are unknown. Under motion or a stale picture the whole thing is labelled an
 * estimate, because the positions it was computed from are already old.
 *
 * Resolving the numbers is JQ-297's. Until that lands `magnitude` and `radius`
 * are absent and every preview says so — which is the correct answer, and the
 * reason this is a seam rather than a stub that guesses.
 */

import {
  type MapGeometry,
  type TargetRegion,
  distance,
  zoneContaining,
} from '../geometry.ts';
import type { BattleSnapshot, BattleUnit, LoadoutSpell, Side } from '../types.ts';
import { opposing } from '../types.ts';

export interface BlastEstimate {
  /** Living enemies inside the blast. */
  readonly inBlast: number;
  /** Of those, how many the resolved magnitude would reduce to nothing. */
  readonly defeated: number;
  /** In the blast and would survive it. */
  readonly survivors: number;
  /** In the blast, but the server did not say enough to judge them. */
  readonly unknown: number;
  /**
   * True only when this region is a lane, something of theirs is in it, all of
   * it is in the blast, all of it dies, and none of it is unknown.
   */
  readonly clearsZone: boolean;
}

export type PreviewConfidence = 'resolved' | 'estimate' | 'unavailable';

export interface OutcomePreview {
  readonly region: TargetRegion;
  readonly affordable: boolean;
  readonly shortfall: number;
  /** Null when the spell's numbers have not been resolved. */
  readonly estimate: BlastEstimate | null;
  readonly confidence: PreviewConfidence;
  /** One line, ready to render. */
  readonly summary: string;
}

/** A unit is in motion if it moved between the last two snapshots. */
export interface PreviewContext {
  readonly snapshot: BattleSnapshot;
  readonly you: Side;
  readonly map: MapGeometry;
  readonly spell: LoadoutSpell;
  /** The picture is known to be out of date. */
  readonly stale: boolean;
  /** Anything on the board moved since the previous snapshot. */
  readonly moving: boolean;
}

function livingEnemies(snapshot: BattleSnapshot, you: Side): BattleUnit[] {
  const them = opposing(you);
  return snapshot.units.filter((unit) => unit.side === them && unit.hp > 0);
}

/**
 * What one unit would suffer. `null` means "cannot say" — the unit's protection
 * is unstated, so any damage number would be made up.
 */
function wouldBeDefeated(unit: BattleUnit, magnitude: number): boolean | null {
  if (unit.protection === undefined) return null;
  return magnitude - unit.protection >= unit.hp;
}

export function previewFor(context: PreviewContext, region: TargetRegion): OutcomePreview {
  const { snapshot, you, map, spell, stale, moving } = context;

  const shortfall = Math.max(0, spell.cost - snapshot.energy);
  const affordable = shortfall === 0;

  if (spell.magnitude === undefined || spell.radius === undefined) {
    return {
      region,
      affordable,
      shortfall,
      estimate: null,
      confidence: 'unavailable',
      summary: 'Effect not resolved yet',
    };
  }

  const enemies = livingEnemies(snapshot, you);
  const inBlast = enemies.filter(
    (unit) => distance(unit.position, region.at) <= spell.radius!,
  );

  let defeated = 0;
  let survivors = 0;
  let unknown = 0;
  for (const unit of inBlast) {
    const verdict = wouldBeDefeated(unit, spell.magnitude);
    if (verdict === null) unknown += 1;
    else if (verdict) defeated += 1;
    else survivors += 1;
  }

  const clearsZone = region.zone
    ? clearsTheLane(enemies, inBlast, region.zone, map, unknown, survivors)
    : false;

  const estimate: BlastEstimate = { inBlast: inBlast.length, defeated, survivors, unknown, clearsZone };
  const confidence: PreviewConfidence = stale || moving ? 'estimate' : 'resolved';

  return {
    region,
    affordable,
    shortfall,
    estimate,
    confidence,
    summary: summarise(estimate, confidence),
  };
}

function clearsTheLane(
  enemies: readonly BattleUnit[],
  inBlast: readonly BattleUnit[],
  zone: string,
  map: MapGeometry,
  unknown: number,
  survivors: number,
): boolean {
  if (unknown > 0 || survivors > 0) return false;

  const inZone = enemies.filter((unit) => zoneContaining(map, unit.position) === zone);
  if (inZone.length === 0) return false;

  const caught = new Set(inBlast.map((unit) => unit.id));
  return inZone.every((unit) => caught.has(unit.id));
}

/**
 * One short line. Short because it is read *while aiming*: the panel sits over
 * the board, and a sentence long enough to wrap twice pushes the panel over the
 * thing the player is aiming at. The hedge is one word for the same reason —
 * the line is already italicised, so "estimate" only has to name the state.
 */
function summarise(estimate: BlastEstimate, confidence: PreviewConfidence): string {
  const { inBlast, defeated, survivors, unknown, clearsZone } = estimate;
  const hedge = confidence === 'estimate' ? ' · estimate' : '';

  if (inBlast === 0) return `Nothing in range${hedge}`;

  if (clearsZone) return `Clears the lane — all ${defeated}${hedge}`;

  const parts: string[] = [`${inBlast} in range`];
  if (defeated > 0) parts.push(`${defeated} would fall`);
  if (survivors > 0) parts.push(`${survivors} would survive`);
  // Said out loud rather than folded into "would survive": the player is being
  // told the preview is incomplete, not that those units are safe.
  if (unknown > 0) parts.push(`${unknown} unknown`);

  return `${parts.join(' · ')}${hedge}`;
}

export function previewsFor(
  context: PreviewContext,
  regions: readonly TargetRegion[],
): OutcomePreview[] {
  return regions.map((region) => previewFor(context, region));
}
