/**
 * The local plan resolver the screens ask before a server is connected.
 *
 * Until JQ-297 this file invented its own magnitudes — a base of 30 plus 11 per
 * contributing mage — because nothing said what a spell's numbers actually were.
 * Something does now: `plan/spellResolver.ts` is the calculation, checked case
 * for case against the server's through `conformance/spell-resolver.json`. So
 * what is left here is assembly, not rules.
 *
 * It stays a fixture because of *where* it sits, not what it computes. The
 * authoritative answer comes from the server at lock-in and the battle runs the
 * server's snapshot; this is the preview the plan screen shows between taps,
 * which has to be instant and therefore local (JQ-297: "client consumes resolved
 * previews or an equivalent local calculation"). JQ-190 wires the screen to the
 * live session; nothing in `plan/` changes when it does.
 */

import { effectSummary, resolveMenu, resolveSlots } from '../../plan/spellResolver.ts';
import { deployedMages, displayReason } from '../../plan/derive.ts';
import type { PlanState } from '../../plan/types.ts';
import type { LockBlocker, ResolvedPlan, ResolvedSpell } from '../resolve.ts';
import type { LoadoutSpell } from '../types.ts';

export function resolvePlanLocally(plan: PlanState): ResolvedPlan {
  const menu = resolveMenu({
    mages: deployedMages(plan),
    rosterAccess: plan.roster.independentSpellAccess,
    definitions: plan.roster.spells,
  });

  const spells: ResolvedSpell[] = menu.entries.map((entry, index) => ({
    spellId: entry.spell.spellId,
    name: entry.spell.name,
    cost: entry.spell.cost,
    effect: effectSummary(entry.spell, plan.roster.spells[index].text),
    eligible: entry.eligible,
    reason: displayReason(plan.roster.spells[index], entry, plan),
    affordable: entry.spell.cost <= plan.energy,
    contributors: entry.spell.contributors,
  }));

  const slots = resolveSlots(menu, plan.spellSlots).map(
    (slot) => spells.find((spell) => spell.spellId === slot.spellId) ?? null,
  );

  const blockers: LockBlocker[] = [];
  if (plan.troops.length === 0) {
    blockers.push({ kind: 'noTroops', message: 'Field at least one troop before locking in.' });
  }
  slots.forEach((slot, index) => {
    if (slot && !slot.eligible) {
      blockers.push({
        kind: 'strandedSlot',
        message: `Spell ${index + 1} — ${slot.name} ${slot.reason ?? 'is no longer legal'}.`,
      });
    }
  });

  const loadout: LoadoutSpell[] = slots
    .filter((slot): slot is ResolvedSpell => slot !== null && slot.eligible)
    .map((slot) => ({
      spellId: slot.spellId,
      name: slot.name,
      cost: slot.cost,
      effect: slot.effect,
    }));

  return { round: plan.round, spells, slots, blockers, loadout };
}
