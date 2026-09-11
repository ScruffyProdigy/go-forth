/**
 * The plan as a pure state machine (JQ-293).
 *
 * Every edit the screen can make is an action, so the reducer's output is a
 * complete description of a locked-in plan — which is what the server will be
 * handed once JQ-287 (orders, placement) and JQ-297 (spell loadout) settle the
 * contract. Keeping it pure is what lets the rules be tested without rendering.
 */

import { isSpellEligible, remainingSummons, troopCapacity } from './derive.ts';
import type { Order, PlanState, PlannedTroop, SpellSlots } from './types.ts';

export type PlanAction =
  | { readonly type: 'fieldMage'; readonly mageId: string }
  | { readonly type: 'unfieldMage'; readonly mageId: string }
  | { readonly type: 'addSummon'; readonly mageId: string; readonly summonId: string }
  | { readonly type: 'removeSummon'; readonly mageId: string; readonly summonId: string }
  | { readonly type: 'setOrder'; readonly mageId: string; readonly order: Order }
  | { readonly type: 'equipSpell'; readonly slot: 0 | 1; readonly spellId: string }
  | { readonly type: 'clearSpell'; readonly slot: 0 | 1 };

export function planReducer(plan: PlanState, action: PlanAction): PlanState {
  switch (action.type) {
    case 'fieldMage':
      return fieldMage(plan, action.mageId);
    case 'unfieldMage':
      return withTroops(
        plan,
        plan.troops.filter((troop) => troop.mageId !== action.mageId),
      );
    case 'addSummon':
      return addSummon(plan, action.mageId, action.summonId);
    case 'removeSummon':
      return mapTroop(plan, action.mageId, (troop) => ({
        ...troop,
        summonIds: removeFirst(troop.summonIds, action.summonId),
      }));
    case 'setOrder':
      return mapTroop(plan, action.mageId, (troop) => ({ ...troop, order: action.order }));
    case 'equipSpell':
      return equipSpell(plan, action.slot, action.spellId);
    case 'clearSpell':
      return { ...plan, spellSlots: replaceSlot(plan.spellSlots, action.slot, null) };
  }
}

/**
 * Fielding a mage fields its default entourage with it: picking a mage *is*
 * picking a troop shape (§3.2). Customising the entourage is a drill-down on a
 * troop already chosen, never a prerequisite for choosing it.
 */
function fieldMage(plan: PlanState, mageId: string): PlanState {
  if (plan.troops.some((troop) => troop.mageId === mageId)) return plan;
  if (plan.troops.length >= plan.mageCap) return plan;

  const mage = plan.roster.mages.find((candidate) => candidate.id === mageId);
  if (!mage) return plan;

  const available = remainingSummons(plan);
  const entourage: string[] = [];
  for (const summonId of mage.defaultEntourage) {
    if ((available[summonId] ?? 0) <= 0) continue;
    available[summonId] -= 1;
    entourage.push(summonId);
  }

  const troop: PlannedTroop = {
    mageId,
    summonIds: entourage,
    // A newcomer's obvious plan is one troop per zone (§4.3), so the default
    // order for each new troop is the first zone nobody has been sent to.
    order: firstFreeOrder(plan),
  };

  return withTroops(plan, [...plan.troops, troop]);
}

function firstFreeOrder(plan: PlanState): Order {
  const taken = new Set(
    plan.troops
      .filter((troop) => troop.order.kind === 'hold')
      .map((troop) => (troop.order.kind === 'hold' ? troop.order.zone : '')),
  );

  for (const zone of ['A', 'B', 'C'] as const) {
    if (!taken.has(zone)) return { kind: 'hold', zone };
  }
  return { kind: 'defendBase' };
}

function addSummon(plan: PlanState, mageId: string, summonId: string): PlanState {
  const troop = plan.troops.find((candidate) => candidate.mageId === mageId);
  if (!troop) return plan;

  if ((remainingSummons(plan)[summonId] ?? 0) <= 0) return plan;

  const cost = plan.roster.summons[summonId]?.capacityCost ?? 1;
  const { unsupported } = troopCapacity(plan, troop);
  if (cost > unsupported) return plan;

  return mapTroop(plan, mageId, (current) => ({
    ...current,
    summonIds: [...current.summonIds, summonId],
  }));
}

/**
 * Both slots are re-picked each round and keep their previous choice while it is
 * legal (§10 #32). A slot stranded by a troop edit is *not* cleared here — the
 * screen flags it so the player learns their edit cost them the spell.
 */
function equipSpell(plan: PlanState, slot: 0 | 1, spellId: string): PlanState {
  if (!isSpellEligible(plan, spellId)) return plan;

  const otherSlot = slot === 0 ? 1 : 0;
  const slots = plan.spellSlots[otherSlot] === spellId
    ? replaceSlot(plan.spellSlots, otherSlot, null)
    : plan.spellSlots;

  return { ...plan, spellSlots: replaceSlot(slots, slot, spellId) };
}

/* ---------------------------------------------------------------- helpers -- */

function withTroops(plan: PlanState, troops: readonly PlannedTroop[]): PlanState {
  return { ...plan, troops };
}

function mapTroop(
  plan: PlanState,
  mageId: string,
  change: (troop: PlannedTroop) => PlannedTroop,
): PlanState {
  return withTroops(
    plan,
    plan.troops.map((troop) => (troop.mageId === mageId ? change(troop) : troop)),
  );
}

function removeFirst(values: readonly string[], value: string): string[] {
  const index = values.indexOf(value);
  return index < 0 ? [...values] : [...values.slice(0, index), ...values.slice(index + 1)];
}

function replaceSlot(slots: SpellSlots, slot: 0 | 1, value: string | null): SpellSlots {
  return slot === 0 ? [value, slots[1]] : [slots[0], value];
}
