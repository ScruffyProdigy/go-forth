/**
 * Plan-phase domain types (JQ-293).
 *
 * Orders, formations and deployment placement are still the screen's own shape:
 * JQ-287 settles them server-side and `fixtures/` is the seam that gets replaced.
 *
 * **Spells are no longer among them.** JQ-297 landed the resolver, so a spell is
 * a `SpellDefinition` from `spellResolver.ts` — the same schema the server
 * authors them in — and eligibility and numbers come from the shared
 * calculation rather than from a client-side guess at the rules.
 */

import type { SpellDefinition } from './spellResolver.ts';

export type ZoneId = 'A' | 'B' | 'C';

export const ZONE_IDS: readonly ZoneId[] = ['A', 'B', 'C'];

/** Schools per design doc §4.4. Neutral units belong to none of them. */
export type School = 'fire' | 'stone' | 'artifice' | 'time' | 'necromancy' | 'neutral';

/** The light rock-paper-scissors that makes composition matter more than count (§4.4). */
export type SummonRole = 'melee' | 'cavalry' | 'siege' | 'support';

/**
 * One order per troop, by tap (§3.2). Orders also determine formation and where
 * the troop is auto-placed in the deployment strip — there is no manual
 * placement in v1.
 */
export type Order =
  | { readonly kind: 'hold'; readonly zone: ZoneId }
  | { readonly kind: 'defendBase' }
  | { readonly kind: 'pushEnemyBase' };

export interface SummonOption {
  readonly id: string;
  readonly name: string;
  readonly role: SummonRole;
  readonly schools: readonly School[];
  /** A large summon fills more than one point of a mage's support capacity (§10 #18). */
  readonly capacityCost: number;
}

export interface MageOption {
  readonly id: string;
  readonly name: string;
  readonly schools: readonly School[];
  /**
   * Tags describe disciplines, roles and personality, and connect mages across
   * schools (§4.8). They are what player spells read, and they are distinct from
   * school membership.
   */
  readonly tags: readonly string[];
  /** How many points of summon this mage sustains (§4.4). */
  readonly supportCapacity: number;
  /** Picking a mage is picking a troop shape — this is the shape (§3.2). */
  readonly defaultEntourage: readonly string[];
  /** Deploying this mage contributes this player spell to the menu (§4.8). */
  readonly signatureSpellId?: string;
}

/**
 * A player spell, as the roster offers it (JQ-297).
 *
 * The whole definition — access rule, base effects and per-effect curves —
 * rather than a pre-resolved card. The screen has to re-price a spell on every
 * tap of a troop, and a definition is what `spellResolver.ts` needs to do that
 * without asking the server. Its authoritative twin is Python's
 * `SpellDefinition`, and `conformance/spell-resolver.json` is what keeps the two
 * readings of it the same.
 *
 * Replaces JQ-293's `requires` / `reads` pair, which said *which* tags a spell
 * read and could not say by how much.
 */
export type { SpellAccess, SpellDefinition } from './spellResolver.ts';
export type SpellOption = SpellDefinition;

export interface Roster {
  readonly mages: readonly MageOption[];
  /** A multiset: duplicates and arbitrary counts are legal (JQ-286 AC). */
  readonly summonCounts: Readonly<Record<string, number>>;
  readonly summons: Readonly<Record<string, SummonOption>>;
  readonly spells: readonly SpellOption[];
  /**
   * The independent spells this side owns (JQ-292). Explicit data: a spell
   * absent from this list is not eligible however the field is arranged, and no
   * tag ever adds it. Preconstructed fills it; a constructed or draft mode would
   * fill it differently, which is the whole reason it is a roster field rather
   * than a rule.
   */
  readonly independentSpellAccess: readonly string[];
}

/** A mage plus the summons it supports, plus what it has been told to do. */
export interface PlannedTroop {
  readonly mageId: string;
  readonly summonIds: readonly string[];
  readonly order: Order;
}

export type SpellSlots = readonly [string | null, string | null];

export interface PlanState {
  readonly round: number;
  /**
   * Maximum mages on the field this round (§4.3). Read from the fixture, never
   * hardcoded: a one-round playtest and a best-of-5 match are the same screen
   * with different numbers (§10 #36, decided 2026-09-11).
   */
  readonly mageCap: number;
  readonly roster: Roster;
  readonly troops: readonly PlannedTroop[];
  readonly spellSlots: SpellSlots;
  /** Player energy, for pricing the spell menu (§4.7). */
  readonly energy: number;
  /** Last round's sighting, greyed on the map. Absent in round 1. */
  readonly opponentLastKnown?: readonly OpponentSighting[];
}

/**
 * What the player already saw at the end of last round, per zone. Planning
 * without information is guessing, but the phase is also where hidden
 * simultaneous choice is the point (JQ-293, open) — so this is last-known and
 * greyed, never live.
 */
export interface OpponentSighting {
  readonly zone: ZoneId;
  readonly mages: number;
  readonly summons: number;
}
