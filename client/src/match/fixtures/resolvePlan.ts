/**
 * The fixture's stand-in for the server's plan resolver (JQ-311).
 *
 * It answers the same question `PlanResolver` will be asked over the wire, which
 * is the only thing that has to be true for the screens to be built against it.
 * The magnitudes are invented demo tuning, recorded here (JQ-311's 2026-09-12
 * scheduling note) rather than sent for balance approval: what a spell's numbers
 * *are* is JQ-292 and JQ-297's, and the point of this file is that the client
 * does not decide them either way.
 *
 * Eligibility reuses `plan/derive.ts` because JQ-293 already tested that logic
 * against the design doc, and duplicating it here would mean two client-side
 * answers instead of one. It stays inside `fixtures/` so that when the real
 * resolver lands, the TypeScript copy of the rules leaves with it.
 */

import { fieldedMages, spellMenu } from '../../plan/derive.ts';
import type { PlanState, SpellOption } from '../../plan/types.ts';
import type { LockBlocker, ResolvedPlan, ResolvedSpell, SpellContributor } from '../resolve.ts';
import type { LoadoutSpell } from '../types.ts';

/** Base magnitude of a spell before any fielded mage adds to it. */
const BASE_MAGNITUDE = 30;
/** What each fielded mage carrying a tag the spell reads adds to it. */
const PER_CONTRIBUTOR = 11;

function contributors(plan: PlanState, spell: SpellOption): SpellContributor[] {
  const reads = spell.reads ?? [];
  // Mage order, then tag order as the spell lists them — no set iteration, so
  // the same plan always resolves to the same sentence.
  return fieldedMages(plan).flatMap((mage) =>
    reads
      .filter((tag) => mage.tags.includes(tag))
      .map((tag) => ({ mageId: mage.id, mageName: mage.name, tag })),
  );
}

/** A spell's blast. Provisional demo tuning, like everything else here. */
const SPELL_RADIUS = 60;

function magnitudeOf(found: readonly SpellContributor[]): number {
  return BASE_MAGNITUDE + PER_CONTRIBUTOR * found.length;
}

function effectText(spell: SpellOption, found: readonly SpellContributor[]): string {
  const magnitude = magnitudeOf(found);
  if (found.length === 0) return `${spell.text} At ${magnitude}, with nothing fielded to raise it.`;
  const tags = [...new Set(found.map((entry) => entry.tag))].join(', ');
  return `${spell.text} At ${magnitude} — ${tags} from ${found.length} fielded mage${
    found.length === 1 ? '' : 's'
  }.`;
}

export function resolvePlanLocally(plan: PlanState): ResolvedPlan {
  const spells: ResolvedSpell[] = spellMenu(plan).map((entry) => {
    const found = contributors(plan, entry.spell);
    return {
      spellId: entry.spell.id,
      name: entry.spell.name,
      cost: entry.spell.cost,
      effect: effectText(entry.spell, found),
      magnitude: magnitudeOf(found),
      radius: SPELL_RADIUS,
      eligible: entry.eligible,
      reason: entry.reason,
      affordable: entry.affordable,
      contributors: found,
    };
  });

  const slots = plan.spellSlots.map((spellId) =>
    spellId === null ? null : (spells.find((spell) => spell.spellId === spellId) ?? null),
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
      magnitude: slot.magnitude,
      radius: slot.radius,
    }));

  return { round: plan.round, spells, slots, blockers, loadout };
}
