import { describe, expect, it } from 'vitest';

import { troopCapacity } from './derive.ts';
import { starterMirrorRound1 } from './fixtures/starterMirror.ts';
import { planReducer, type PlanAction } from './planReducer.ts';
import type { PlanState } from './types.ts';

function apply(plan: PlanState, ...actions: PlanAction[]): PlanState {
  return actions.reduce(planReducer, plan);
}

/** A plan with the bench cleared, so fielding is the thing under test. */
function emptied(): PlanState {
  return apply(
    starterMirrorRound1(),
    { type: 'unfieldMage', mageId: 'emberwright' },
    { type: 'unfieldMage', mageId: 'pyreMagus' },
    { type: 'unfieldMage', mageId: 'ashenWarden' },
  );
}

describe('fielding a mage', () => {
  it('brings the mage in with its default entourage — one decision, not two', () => {
    const plan = planReducer(emptied(), { type: 'fieldMage', mageId: 'emberwright' });

    expect(plan.troops).toHaveLength(1);
    expect(plan.troops[0].summonIds).toEqual(['emberHound', 'emberHound']);
  });

  it('refuses to field past the mage cap', () => {
    const plan = starterMirrorRound1();
    expect(plan.troops).toHaveLength(plan.mageCap);

    const overCap = planReducer(plan, { type: 'fieldMage', mageId: 'kindler' });
    expect(overCap.troops).toHaveLength(plan.mageCap);
    expect(overCap).toBe(plan);
  });

  it('gives each new troop a different zone, since one per zone is the obvious plan', () => {
    const plan = apply(
      emptied(),
      { type: 'fieldMage', mageId: 'emberwright' },
      { type: 'fieldMage', mageId: 'pyreMagus' },
    );

    expect(plan.troops.map((troop) => troop.order)).toEqual([
      { kind: 'hold', zone: 'A' },
      { kind: 'hold', zone: 'B' },
    ]);
  });

  it('does not hand out a summon the roster has already spent', () => {
    // One Cinder Bulwark exists. The Warden takes it; nobody else can.
    const plan = apply(emptied(), { type: 'fieldMage', mageId: 'ashenWarden' });
    expect(plan.troops[0].summonIds).toEqual(['cinderBulwark']);

    const again = planReducer(plan, { type: 'addSummon', mageId: 'ashenWarden', summonId: 'cinderBulwark' });
    expect(again).toBe(plan);
  });

  it('unfields the whole troop, summons included', () => {
    const plan = planReducer(starterMirrorRound1(), {
      type: 'unfieldMage',
      mageId: 'emberwright',
    });

    expect(plan.troops.map((troop) => troop.mageId)).toEqual(['pyreMagus', 'ashenWarden']);
  });
});

describe('customising an entourage', () => {
  it('adds a summon into unsupported capacity', () => {
    const plan = apply(emptied(), { type: 'fieldMage', mageId: 'kindler' });
    const trimmed = planReducer(plan, {
      type: 'removeSummon',
      mageId: 'kindler',
      summonId: 'flameWisp',
    });

    const refilled = planReducer(trimmed, {
      type: 'addSummon',
      mageId: 'kindler',
      summonId: 'scoriaLancer',
    });

    expect(refilled.troops[0].summonIds).toEqual(['emberHound', 'scoriaLancer']);
    expect(troopCapacity(refilled, refilled.troops[0]).unsupported).toBe(0);
  });

  it('refuses a summon that does not fit the remaining capacity', () => {
    const plan = apply(emptied(), { type: 'fieldMage', mageId: 'emberwright' });
    const full = planReducer(plan, {
      type: 'addSummon',
      mageId: 'emberwright',
      summonId: 'emberHound',
    });

    expect(full).toBe(plan);
  });
});

describe('spell slots', () => {
  it('equips an eligible spell', () => {
    const plan = planReducer(starterMirrorRound1(), {
      type: 'equipSpell',
      slot: 0,
      spellId: 'rekindle',
    });

    expect(plan.spellSlots).toEqual(['rekindle', 'flameWard']);
  });

  it('refuses a spell no fielded mage makes available', () => {
    const benched = planReducer(starterMirrorRound1(), {
      type: 'unfieldMage',
      mageId: 'pyreMagus',
    });

    const attempted = planReducer(benched, { type: 'equipSpell', slot: 0, spellId: 'rekindle' });
    expect(attempted).toBe(benched);
  });

  it('moves a spell rather than equipping it twice', () => {
    const plan = planReducer(starterMirrorRound1(), {
      type: 'equipSpell',
      slot: 1,
      spellId: 'fireball',
    });

    expect(plan.spellSlots).toEqual([null, 'fireball']);
  });

  it('leaves a stranded slot in place for the screen to flag', () => {
    const benched = planReducer(starterMirrorRound1(), {
      type: 'unfieldMage',
      mageId: 'ashenWarden',
    });

    expect(benched.spellSlots[1]).toBe('flameWard');
  });
});

describe('orders', () => {
  it('sets one order per troop', () => {
    const plan = planReducer(starterMirrorRound1(), {
      type: 'setOrder',
      mageId: 'ashenWarden',
      order: { kind: 'pushEnemyBase' },
    });

    expect(plan.troops[2].order).toEqual({ kind: 'pushEnemyBase' });
  });
});
