/**
 * Placeholder armies for the headless demo and the determinism harness.
 *
 * Names come from the design doc's provisional Fire roster (§7.4) so the printed
 * event stream reads like the game; the numbers are made up. Balance is not a v1
 * goal and certainly not slice A's — these exist so there is something to run.
 *
 * v1 is a Fire mirror (§7.4), and round 1 opens at the starting mage cap of
 * three (§4.3): three troops, one mage each, with their summons.
 */
import type { UnitType } from './units.js';
import type { ArmySetup, BattleSetup } from './world.js';
import type { Side } from './types.js';

export const PLACEHOLDER_UNIT_TYPES: UnitType[] = [
  {
    id: 'ember-adept',
    kind: 'mage',
    schools: ['fire'],
    maxHp: 55,
    damage: 7,
    range: 90,
    speed: 26,
    attackCooldownSeconds: 1.4,
    supportCapacity: 2,
    resummonPaceSeconds: 8,
  },
  {
    id: 'cinder-hound',
    kind: 'summon',
    schools: ['fire'],
    maxHp: 70,
    damage: 11,
    range: 16,
    speed: 62,
    attackCooldownSeconds: 0.9,
  },
  {
    id: 'ember-sprite',
    kind: 'summon',
    schools: ['fire'],
    maxHp: 40,
    damage: 9,
    range: 70,
    speed: 44,
    attackCooldownSeconds: 1.2,
  },
  {
    id: 'ash-ram',
    kind: 'summon',
    schools: ['fire'],
    maxHp: 120,
    damage: 16,
    range: 18,
    speed: 38,
    attackCooldownSeconds: 1.6,
  },
];

function fireArmy(side: Side): ArmySetup {
  return {
    side,
    troops: [
      { mages: [{ typeId: 'ember-adept' }], summons: [{ typeId: 'cinder-hound', count: 2 }] },
      {
        mages: [{ typeId: 'ember-adept' }],
        summons: [{ typeId: 'ash-ram' }, { typeId: 'ember-sprite' }],
      },
      { mages: [{ typeId: 'ember-adept' }], summons: [{ typeId: 'ember-sprite', count: 2 }] },
    ],
  };
}

/** Two identical Fire armies — the v1 mirror match. */
export function placeholderBattle(): BattleSetup {
  return {
    unitTypes: PLACEHOLDER_UNIT_TYPES,
    armies: [fireArmy('north'), fireArmy('south')],
  };
}
