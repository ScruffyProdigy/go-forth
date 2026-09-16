/**
 * Pure derivations for the plan phase (JQ-293).
 *
 * Everything interesting about the phase — the resonance curve, support
 * capacity, which spells are legal, and how deep each step is folded — lives
 * here rather than in a component, so it can be tested without rendering
 * anything and reused by the server when the real contract lands.
 */

import {
  type DeployedMage,
  type MenuEntry,
  type SpellDefinition,
  resolveMenu,
  resolveSlots,
} from './spellResolver.ts';
import {
  type MageOption,
  type Order,
  type PlanState,
  type PlannedTroop,
  type School,
  type SpellOption,
  type ZoneId,
  ZONE_IDS,
} from './types.ts';

/* ------------------------------------------------------------------ mages -- */

export function fieldedMages(plan: PlanState): MageOption[] {
  return plan.troops
    .map((troop) => plan.roster.mages.find((mage) => mage.id === troop.mageId))
    .filter((mage): mage is MageOption => mage !== undefined);
}

export function isFielded(plan: PlanState, mageId: string): boolean {
  return plan.troops.some((troop) => troop.mageId === mageId);
}

export function atMageCap(plan: PlanState): boolean {
  return plan.troops.length >= plan.mageCap;
}

/* -------------------------------------------------------------- resonance -- */

/**
 * §10 #21: 1 weak, 2 below par, 3 par, 4+ strong. Resonance scales energy gain,
 * resummon pace and mage respawn, which is why it is the headline number — the
 * decision and its consequence belong on the same screen.
 */
export type ResonanceTier = 'weak' | 'below-par' | 'par' | 'strong';

export const RESONANCE_TIER_LABEL: Record<ResonanceTier, string> = {
  weak: 'WEAK',
  'below-par': 'BELOW PAR',
  par: 'PAR',
  strong: 'STRONG',
};

export function resonanceTier(mageCount: number): ResonanceTier {
  if (mageCount >= 4) return 'strong';
  if (mageCount === 3) return 'par';
  if (mageCount === 2) return 'below-par';
  return 'weak';
}

export interface SchoolResonance {
  readonly school: School;
  readonly mageCount: number;
  readonly tier: ResonanceTier;
}

/**
 * Counts *fielded* mages per school. A dual mage counts once for each of its
 * schools, which is what makes duals worth fielding (§10 #22).
 */
export function resonance(plan: PlanState): SchoolResonance[] {
  const counts = new Map<School, number>();
  for (const mage of fieldedMages(plan)) {
    for (const school of mage.schools) {
      if (school === 'neutral') continue;
      counts.set(school, (counts.get(school) ?? 0) + 1);
    }
  }

  return [...counts.entries()]
    .map(([school, mageCount]) => ({ school, mageCount, tier: resonanceTier(mageCount) }))
    .sort((a, b) => b.mageCount - a.mageCount || a.school.localeCompare(b.school));
}

/** The one number the headline shows. Undefined when nothing is fielded yet. */
export function headlineResonance(plan: PlanState): SchoolResonance | undefined {
  return resonance(plan)[0];
}

/* --------------------------------------------------------------- capacity -- */

export interface TroopCapacity {
  readonly mageId: string;
  readonly capacity: number;
  readonly used: number;
  /** Capacity paid for and not filled — a summon slot going to waste. */
  readonly unsupported: number;
}

export function troopCapacity(plan: PlanState, troop: PlannedTroop): TroopCapacity {
  const mage = plan.roster.mages.find((candidate) => candidate.id === troop.mageId);
  const capacity = mage?.supportCapacity ?? 0;
  const used = troop.summonIds.reduce(
    (total, summonId) => total + (plan.roster.summons[summonId]?.capacityCost ?? 1),
    0,
  );

  return { mageId: troop.mageId, capacity, used, unsupported: Math.max(0, capacity - used) };
}

export interface ArmyCapacity {
  readonly capacity: number;
  readonly used: number;
  readonly unsupported: number;
  readonly perTroop: readonly TroopCapacity[];
}

export function armyCapacity(plan: PlanState): ArmyCapacity {
  const perTroop = plan.troops.map((troop) => troopCapacity(plan, troop));

  return {
    capacity: perTroop.reduce((total, troop) => total + troop.capacity, 0),
    used: perTroop.reduce((total, troop) => total + troop.used, 0),
    unsupported: perTroop.reduce((total, troop) => total + troop.unsupported, 0),
    perTroop,
  };
}

/**
 * How many of a summon are left in the roster multiset once the current plan has
 * taken its share. Duplicates are legal, so this is a count and not a flag.
 */
export function remainingSummons(plan: PlanState): Record<string, number> {
  const remaining: Record<string, number> = { ...plan.roster.summonCounts };
  for (const troop of plan.troops) {
    for (const summonId of troop.summonIds) {
      remaining[summonId] = (remaining[summonId] ?? 0) - 1;
    }
  }
  return remaining;
}

/* ----------------------------------------------------------------- spells -- */

export interface SpellAvailability {
  readonly spell: SpellOption;
  readonly eligible: boolean;
  /** Why it is greyed. Shown rather than hidden, so the link teaches itself. */
  readonly reason?: string;
  readonly affordable: boolean;
  /** The resolved menu entry: actual numbers, contributors, and who granted it. */
  readonly resolved: MenuEntry;
}

/**
 * This plan's mages as the resolver wants them (JQ-297).
 *
 * Instance ids are the troop's position in the plan, so fielding the same mage
 * card twice is two deployed mages — counted twice for every tag they carry,
 * and granting one menu entry between them.
 *
 * Summons are not here, and this is the only place they could have been: the
 * resolver never sees the roster, so "never count summons" is a property of the
 * shape rather than of a filter somebody has to remember.
 */
export function deployedMages(plan: PlanState): DeployedMage[] {
  return plan.troops.flatMap((troop, index) => {
    const mage = plan.roster.mages.find((candidate) => candidate.id === troop.mageId);
    if (!mage) return [];
    return [
      {
        instanceId: `troop-${index + 1}`,
        typeId: mage.id,
        name: mage.name,
        tags: mage.tags,
      },
    ];
  });
}

/**
 * The resolver's reason, with the mage named where the screen can name it.
 *
 * The server's reason for a missing signature is "needs its mage on the field",
 * and it has to be: it travels on the wire to a client whose roster may not be
 * loaded, and it is pinned by the conformance fixtures. Here the roster *is*
 * loaded, and "needs Emberwright fielded" tells the player what to change while
 * the generic sentence does not.
 *
 * Rebuilt from the access rule rather than by rewriting the server's string. A
 * display layer that pattern-matched on prose would break silently the first
 * time somebody reworded it.
 */
export function displayReason(
  definition: SpellDefinition,
  entry: MenuEntry,
  plan: PlanState,
): string | undefined {
  if (entry.eligible) return undefined;
  if (definition.access.kind === 'signature') {
    const { mageTypeId } = definition.access;
    const mage = plan.roster.mages.find((candidate) => candidate.id === mageTypeId);
    if (mage) return `needs ${mage.name} fielded`;
  }
  return entry.reason ?? undefined;
}

/**
 * §4.8: a deployed mage contributes its signature spell to the menu; other
 * spells read tags carried by deployed mages, and independents need explicit
 * roster access on top. Ineligible spells stay on the menu with their reason —
 * hiding them would hide the mage-to-spell link that is the point of choosing
 * troops first.
 *
 * Derived on every call rather than cached, which is what makes "editing troops
 * updates eligibility and previews immediately" (JQ-297) true by construction:
 * there is no stale answer to invalidate.
 */
export function spellMenu(plan: PlanState): SpellAvailability[] {
  const menu = resolveMenu({
    mages: deployedMages(plan),
    rosterAccess: plan.roster.independentSpellAccess,
    definitions: plan.roster.spells,
  });

  return menu.entries.map((entry, index) => {
    const spell = plan.roster.spells[index];
    return {
      spell,
      eligible: entry.eligible,
      reason: displayReason(spell, entry, plan),
      // The *resolved* cost, not the card's. They are the same today — nothing
      // discounts a spell yet (JQ-297 defers that) — and reading the resolved
      // one means they stay right when something does.
      affordable: entry.spell.cost <= plan.energy,
      resolved: entry,
    };
  });
}

export function isSpellEligible(plan: PlanState, spellId: string): boolean {
  return spellMenu(plan).some((entry) => entry.spell.id === spellId && entry.eligible);
}

/**
 * Slots are re-picked every round and keep their previous choice while it is
 * still legal (§10 #32). A troop edit that strands a slot flags it rather than
 * silently clearing it — the player chose that spell and should be told it went
 * away, not discover an empty slot.
 */
export function strandedSlots(plan: PlanState): number[] {
  const menu = resolveMenu({
    mages: deployedMages(plan),
    rosterAccess: plan.roster.independentSpellAccess,
    definitions: plan.roster.spells,
  });

  return resolveSlots(menu, plan.spellSlots)
    .filter((slot) => slot.stranded)
    .map((slot) => slot.index);
}

/* ------------------------------------------------------------- placements -- */

export function orderLabel(order: Order): string {
  switch (order.kind) {
    case 'hold':
      return `Hold ${order.zone}`;
    case 'defendBase':
      return 'Defend base';
    case 'pushEnemyBase':
      return 'Push enemy base';
  }
}

export const ORDER_CHOICES: readonly Order[] = [
  ...ZONE_IDS.map((zone): Order => ({ kind: 'hold', zone })),
  { kind: 'defendBase' },
  { kind: 'pushEnemyBase' },
];

export function sameOrder(a: Order, b: Order): boolean {
  if (a.kind !== b.kind) return false;
  return a.kind === 'hold' && b.kind === 'hold' ? a.zone === b.zone : true;
}

/**
 * Troops are placed automatically by their order (§3.2) — a Hold A troop starts
 * on A's side of the deployment strip. `lane` is a fraction across the strip;
 * the map turns it into pixels so this stays free of geometry.
 *
 * Lanes are distributed evenly rather than fixed per order. Fixed lanes put two
 * troops on top of each other as soon as a plan sends one to B and one home,
 * and an unreadable board is worse than an imprecise one: the point of showing
 * the plan as a board position is that you can see whose troop is where.
 */
export interface Placement {
  readonly troop: PlannedTroop;
  readonly mage: MageOption;
  readonly lane: number;
  readonly towards: ZoneId | 'ownBase' | 'enemyBase';
  /**
   * Formation follows the order too (§3.2): Hold and Defend put summons in
   * front of the mages, Push puts the mages close behind the line.
   */
  readonly formation: 'summonsForward' | 'magesClose';
}

/** Left-to-right ordering of the strip: the zones in map order, then the bases. */
function laneRank(order: Order): number {
  if (order.kind === 'hold') return ZONE_IDS.indexOf(order.zone);
  return order.kind === 'defendBase' ? ZONE_IDS.length : ZONE_IDS.length + 1;
}

export function placements(plan: PlanState): Placement[] {
  const ordered = [...plan.troops].sort((a, b) => laneRank(a.order) - laneRank(b.order));

  return ordered.flatMap((troop) => {
    const mage = plan.roster.mages.find((candidate) => candidate.id === troop.mageId);
    if (!mage) return [];

    const index = ordered.indexOf(troop);
    return [
      {
        troop,
        mage,
        lane: (index + 0.5) / ordered.length,
        towards: towards(troop.order),
        formation: troop.order.kind === 'pushEnemyBase' ? 'magesClose' : 'summonsForward',
      },
    ];
  });
}

function towards(order: Order): ZoneId | 'ownBase' | 'enemyBase' {
  if (order.kind === 'hold') return order.zone;
  return order.kind === 'defendBase' ? 'ownBase' : 'enemyBase';
}

/* -------------------------------------------------------------- fold depth -- */

/**
 * §3.2: a control appears when the decision it serves first exists. Three
 * values, not two — "absent" is a decision that genuinely does not exist yet,
 * and is derived state rather than a tutorial flag. Nothing a returning player
 * would want is hidden.
 */
export type StepFold = 'absent' | 'collapsed';

export type StepId = 'troops' | 'spells' | 'orders';

export interface StepSummary {
  readonly id: StepId;
  readonly title: string;
  readonly fold: StepFold;
  /** The one line a collapsed step shows. */
  readonly line: string;
  readonly needsAttention: boolean;
}

export function stepSummaries(plan: PlanState): StepSummary[] {
  const menu = spellMenu(plan);
  const anySpellEligible = menu.some((entry) => entry.eligible);
  const stranded = strandedSlots(plan);

  return [
    {
      id: 'troops',
      title: 'Choose troops',
      fold: 'collapsed',
      line: troopsLine(plan),
      needsAttention: plan.troops.length === 0,
    },
    {
      id: 'spells',
      title: 'Choose spells',
      // No fielded mage grants a spell and no fallback is legal: the decision
      // does not exist this round, so the step is absent rather than empty.
      fold: anySpellEligible ? 'collapsed' : 'absent',
      line: spellsLine(plan),
      needsAttention: stranded.length > 0,
    },
    {
      id: 'orders',
      title: 'Give orders',
      // One troop has nowhere to distribute itself — there is no choice to make.
      fold: plan.troops.length > 1 ? 'collapsed' : 'absent',
      line: ordersLine(plan),
      needsAttention: false,
    },
  ];
}

function troopsLine(plan: PlanState): string {
  if (plan.troops.length === 0) return 'No troops fielded';

  const names = fieldedMages(plan).map((mage) => mage.name);
  const summons = plan.troops.reduce((total, troop) => total + troop.summonIds.length, 0);
  const { unsupported } = armyCapacity(plan);
  const tail = unsupported > 0 ? ` · ${unsupported} unsupported` : '';

  return `${names.join(', ')} · ${summons} summons${tail}`;
}

function spellsLine(plan: PlanState): string {
  const stranded = strandedSlots(plan);
  const names = plan.spellSlots.map((spellId, index) => {
    if (spellId === null) return 'empty';
    if (stranded.includes(index)) return 'NEEDS REPLACEMENT';
    return plan.roster.spells.find((spell) => spell.id === spellId)?.name ?? 'unknown';
  });

  return names.join(' · ');
}

function ordersLine(plan: PlanState): string {
  if (plan.troops.length === 0) return 'Nothing to order';
  return plan.troops.map((troop) => orderLabel(troop.order)).join(' · ');
}
