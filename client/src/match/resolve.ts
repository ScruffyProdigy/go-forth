/**
 * The resolved plan: what the *server* says the plan currently means (JQ-311).
 *
 * The plan screen was built against `plan/derive.ts`, which computes eligibility
 * and costs in TypeScript. That was right for JQ-293 — there was no server to
 * ask — but the opening demo cannot ship it as the answer: the rules live in
 * Python, and a client that re-implements them is a second rule engine that will
 * drift. JQ-311 says it in as many words: "use server-resolved previews or
 * conformance-tested equivalent; no shared-TypeScript-runtime assumption".
 *
 * So the screen stops deriving and starts *asking*. `PlanResolver` is that
 * question. The fixture answers it locally today (`fixtures/resolvePlan.ts`);
 * JQ-309 replaces the implementation with a call, and no screen changes.
 *
 * Lock-in snapshots are provisional (JQ-311 AC 2): what the player locks is what
 * they were last told, and the server is free to resolve it differently when the
 * round actually starts.
 */

import type { PlanState } from '../plan/types.ts';
import type { LoadoutSpell } from './types.ts';

/**
 * A fielded mage that is making a spell's numbers what they are.
 *
 * Shown rather than summarised: "Fireball 52 damage" tells a player nothing they
 * can act on, and "Emberwright and Pyre Magus are both Evocation" tells them
 * what to change. The mage-to-spell link is the whole reason troops are chosen
 * before spells (§4.8).
 */
export interface SpellContributor {
  readonly mageId: string;
  readonly mageName: string;
  readonly tag: string;
}

export interface ResolvedSpell {
  readonly spellId: string;
  readonly name: string;
  /** The resolved cost. Not necessarily the cost printed on the card. */
  readonly cost: number;
  /** The resolved effect, with the numbers this plan actually produces. */
  readonly effect: string;
  readonly eligible: boolean;
  /** Why it is not eligible. Shown, never hidden — the link teaches itself. */
  readonly reason?: string;
  readonly affordable: boolean;
  readonly contributors: readonly SpellContributor[];
}

/**
 * Something that has to change before this plan can be locked in.
 *
 * "Invalid slots block lock-in" (JQ-311 AC 2). Blocking at the hub is the point:
 * JQ-304 is the bug where a plan the client accepted was rejected at world
 * creation *after* lock-in, and the fix in shape is to refuse it while the
 * player is still looking at the screen that can change it.
 */
export interface LockBlocker {
  readonly kind: 'strandedSlot' | 'noTroops';
  readonly message: string;
}

export interface ResolvedPlan {
  readonly round: number;
  /** Every spell in the roster, resolved against this plan. */
  readonly spells: readonly ResolvedSpell[];
  /** The two slots, resolved. Null is an empty slot, which is legal. */
  readonly slots: readonly (ResolvedSpell | null)[];
  readonly blockers: readonly LockBlocker[];
  /** What the round would be fought with — the battle screen's cast bar. */
  readonly loadout: readonly LoadoutSpell[];
}

export type PlanResolver = (plan: PlanState) => ResolvedPlan;

export function canLockIn(resolved: ResolvedPlan): boolean {
  return resolved.blockers.length === 0;
}
