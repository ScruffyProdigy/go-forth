/**
 * Plan-phase domain types (JQ-293).
 *
 * These live client-side on purpose. The plan -> sim contract is still moving:
 * orders, formations and deployment placement are JQ-287, and spell selection is
 * JQ-297. Neither has landed, and the JQ-286 sim slice defines neither. Guessing
 * the server's field names now would just be a rename later, so the screen owns
 * its own shape and `fixtures/` is the single seam that gets replaced.
 */

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
 * What a spell needs before it can be equipped. A spell that reads a tag needs
 * at least one *fielded* mage carrying it — mages left on the bench grant
 * nothing, which is the whole reason troops precede spells (§10 #31).
 */
export type SpellRequirement =
  | { readonly kind: 'always' }
  | { readonly kind: 'signature'; readonly mageId: string }
  | { readonly kind: 'tag'; readonly tag: string };

export interface SpellOption {
  readonly id: string;
  readonly name: string;
  readonly cost: number;
  readonly text: string;
  readonly requires: SpellRequirement;
  /**
   * The tags whose *count among fielded mages* sets this spell's numbers (§4.8).
   *
   * Added by JQ-311: a spell's printed text says which tags matter, but nothing
   * could say by how much, and the opening demo has to show "actual resolved
   * costs/effects/contributors" rather than a card's printed ones. Resolution
   * itself belongs to the server — this only names what it reads.
   */
  readonly reads?: readonly string[];
}

export interface Roster {
  readonly mages: readonly MageOption[];
  /** A multiset: duplicates and arbitrary counts are legal (JQ-286 AC). */
  readonly summonCounts: Readonly<Record<string, number>>;
  readonly summons: Readonly<Record<string, SummonOption>>;
  readonly spells: readonly SpellOption[];
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
