import { describe, expect, it } from 'vitest';

import {
  armyCapacity,
  headlineResonance,
  placements,
  resonanceTier,
  spellMenu,
  stepSummaries,
  strandedSlots,
} from './derive.ts';
import { starterMirrorRound1 } from './fixtures/starterMirror.ts';
import { planReducer } from './planReducer.ts';
import type { PlanState } from './types.ts';

function apply(plan: PlanState, ...actions: Parameters<typeof planReducer>[1][]): PlanState {
  return actions.reduce(planReducer, plan);
}

describe('resonance', () => {
  // §10 #21: 1 weak, 2 below par, 3 par, 4+ strong.
  it.each([
    [1, 'weak'],
    [2, 'below-par'],
    [3, 'par'],
    [4, 'strong'],
    [7, 'strong'],
  ])('counts %i fielded mages as %s', (count, tier) => {
    expect(resonanceTier(count)).toBe(tier);
  });

  it('counts fielded mages only, and updates as they are fielded', () => {
    const plan = starterMirrorRound1();
    expect(headlineResonance(plan)).toMatchObject({ school: 'fire', mageCount: 3, tier: 'par' });

    const thinned = apply(plan, { type: 'unfieldMage', mageId: 'ashenWarden' });
    expect(headlineResonance(thinned)).toMatchObject({ mageCount: 2, tier: 'below-par' });
  });

  it('has no headline when nothing is fielded', () => {
    const empty = apply(
      starterMirrorRound1(),
      { type: 'unfieldMage', mageId: 'emberwright' },
      { type: 'unfieldMage', mageId: 'pyreMagus' },
      { type: 'unfieldMage', mageId: 'ashenWarden' },
    );

    expect(headlineResonance(empty)).toBeUndefined();
  });
});

describe('support capacity', () => {
  it('reports unsupported capacity when a mage sustains less than it could', () => {
    // The Warden supports 2 and carries one large (cost 2) — nothing unsupported.
    const plan = starterMirrorRound1();
    expect(armyCapacity(plan).unsupported).toBe(0);

    const thinned = apply(plan, {
      type: 'removeSummon',
      mageId: 'ashenWarden',
      summonId: 'cinderBulwark',
    });
    expect(armyCapacity(thinned).unsupported).toBe(2);
  });

  it('counts a large summon against more than one point of capacity', () => {
    const plan = starterMirrorRound1();
    const warden = armyCapacity(plan).perTroop.find((troop) => troop.mageId === 'ashenWarden');

    expect(warden).toMatchObject({ capacity: 2, used: 2 });
  });
});

describe('spell menu', () => {
  it('offers a signature spell only while its mage is fielded', () => {
    const plan = starterMirrorRound1();
    const fireball = () => spellMenu(plan).find((entry) => entry.spell.id === 'fireball');
    expect(fireball()).toMatchObject({ eligible: true });

    const benched = apply(plan, { type: 'unfieldMage', mageId: 'emberwright' });
    const entry = spellMenu(benched).find((candidate) => candidate.spell.id === 'fireball');
    expect(entry).toMatchObject({ eligible: false, reason: 'needs Emberwright fielded' });
  });

  it('reads tags from fielded mages, and says which tag is missing', () => {
    const noGuardian = apply(starterMirrorRound1(), {
      type: 'unfieldMage',
      mageId: 'ashenWarden',
    });

    const veil = spellMenu(noGuardian).find((entry) => entry.spell.id === 'cinderVeil');
    expect(veil).toMatchObject({ eligible: false, reason: 'needs a fielded Guardian mage' });
  });

  it('keeps the basic fallback legal with nothing fielded at all', () => {
    const empty = apply(
      starterMirrorRound1(),
      { type: 'unfieldMage', mageId: 'emberwright' },
      { type: 'unfieldMage', mageId: 'pyreMagus' },
      { type: 'unfieldMage', mageId: 'ashenWarden' },
    );

    expect(spellMenu(empty).find((entry) => entry.spell.id === 'scorch')).toMatchObject({
      eligible: true,
    });
  });

  it('marks a spell the player cannot currently afford without making it illegal', () => {
    const plan = { ...starterMirrorRound1(), energy: 2 };
    const fireball = spellMenu(plan).find((entry) => entry.spell.id === 'fireball');

    expect(fireball).toMatchObject({ eligible: true, affordable: false });
  });
});

describe('stranded slots', () => {
  it('flags a slot a troop edit invalidated rather than silently clearing it', () => {
    const plan = starterMirrorRound1();
    expect(strandedSlots(plan)).toEqual([]);

    // Slot 2 holds Flame Ward, the Warden's signature.
    const benched = apply(plan, { type: 'unfieldMage', mageId: 'ashenWarden' });
    expect(strandedSlots(benched)).toEqual([1]);
    expect(benched.spellSlots[1]).toBe('flameWard');
  });
});

describe('fold depth', () => {
  it('collapses every step to one line when the plan is pre-filled', () => {
    const steps = stepSummaries(starterMirrorRound1());

    expect(steps.map((step) => step.fold)).toEqual(['collapsed', 'collapsed', 'collapsed']);
    expect(steps[0].line).toContain('Emberwright');
  });

  it('makes orders absent when one troop leaves nothing to distribute', () => {
    const oneTroop = apply(
      starterMirrorRound1(),
      { type: 'unfieldMage', mageId: 'pyreMagus' },
      { type: 'unfieldMage', mageId: 'ashenWarden' },
    );

    const orders = stepSummaries(oneTroop).find((step) => step.id === 'orders');
    expect(orders?.fold).toBe('absent');
  });

  it('shows the stranded slot in the collapsed spell line', () => {
    const benched = apply(starterMirrorRound1(), { type: 'unfieldMage', mageId: 'ashenWarden' });
    const spells = stepSummaries(benched).find((step) => step.id === 'spells');

    expect(spells?.line).toContain('NEEDS REPLACEMENT');
    expect(spells?.needsAttention).toBe(true);
  });
});

describe('placement', () => {
  it('places each troop by its order rather than by hand', () => {
    const laid = placements(starterMirrorRound1());

    expect(laid.map((entry) => entry.towards)).toEqual(['A', 'B', 'ownBase']);
  });

  it('spreads troops sent to the same place so they stay distinguishable', () => {
    const doubledUp = planReducer(starterMirrorRound1(), {
      type: 'setOrder',
      mageId: 'pyreMagus',
      order: { kind: 'hold', zone: 'A' },
    });

    const lanes = placements(doubledUp)
      .filter((entry) => entry.towards === 'A')
      .map((entry) => entry.lane);

    expect(lanes).toHaveLength(2);
    expect(lanes[0]).not.toBe(lanes[1]);
  });
});
