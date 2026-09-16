/**
 * The Starter 1v1 mirror, Fire school (v1's only matchup — README).
 *
 * THIS FILE IS THE SEAM. When JQ-287 settles orders/placement and JQ-297 settles
 * the spell loadout, the real `PlanState` arrives from the server and this
 * fixture is what gets deleted — not the screen, the reducer, or the
 * derivations. Nothing outside `fixtures/` should grow a dependency on the
 * specific mages and spells named here.
 *
 * Numbers are the design doc's provisionals: mage cap starts at 3 (§4.3),
 * support capacities 2 / 1-large / 3 (§10 #18), player energy starts ~3 (§10 #4).
 */

import type { MageOption, PlanState, Roster, SpellOption, SummonOption } from '../types.ts';

const summons: Record<string, SummonOption> = {
  emberHound: {
    id: 'emberHound',
    name: 'Ember Hound',
    role: 'melee',
    schools: ['fire'],
    capacityCost: 1,
  },
  scoriaLancer: {
    id: 'scoriaLancer',
    name: 'Scoria Lancer',
    role: 'cavalry',
    schools: ['fire'],
    capacityCost: 1,
  },
  flameWisp: {
    id: 'flameWisp',
    name: 'Flame Wisp',
    role: 'support',
    schools: ['fire'],
    capacityCost: 1,
  },
  cinderBulwark: {
    id: 'cinderBulwark',
    name: 'Cinder Bulwark',
    role: 'siege',
    schools: ['fire'],
    // The Warden's "1 large" (§10 #18): one summon that eats the whole capacity.
    capacityCost: 2,
  },
};

const mages: MageOption[] = [
  {
    id: 'emberwright',
    name: 'Emberwright',
    schools: ['fire'],
    tags: ['Evocation', 'Reckless'],
    supportCapacity: 2,
    defaultEntourage: ['emberHound', 'emberHound'],
    signatureSpellId: 'fireball',
  },
  {
    id: 'ashenWarden',
    name: 'Ashen Warden',
    schools: ['fire'],
    tags: ['Guardian', 'Disciplined'],
    supportCapacity: 2,
    defaultEntourage: ['cinderBulwark'],
    signatureSpellId: 'flameWard',
  },
  {
    id: 'pyreMagus',
    name: 'Pyre Magus',
    schools: ['fire'],
    tags: ['Evocation', 'Summoner'],
    supportCapacity: 3,
    defaultEntourage: ['flameWisp', 'flameWisp', 'scoriaLancer'],
    signatureSpellId: 'rekindle',
  },
  {
    id: 'kindler',
    name: 'Kindler',
    schools: ['fire'],
    tags: ['Summoner', 'Disciplined'],
    supportCapacity: 2,
    defaultEntourage: ['emberHound', 'flameWisp'],
  },
];

/**
 * Illustrative only — §4.8 is explicit that these are not final spell designs,
 * and the real set is JQ-292. What matters here is the *shape*: signature spells
 * arrive with their mage, independents read a tag, and a fallback is always legal.
 */
const spells: SpellOption[] = [
  {
    id: 'fireball',
    name: 'Fireball',
    cost: 3,
    text: 'Evocation sets the damage, Reckless the radius.',
    requires: { kind: 'signature', mageId: 'emberwright' },
    reads: ['Evocation', 'Reckless'],
  },
  {
    id: 'flameWard',
    name: 'Flame Ward',
    cost: 2,
    text: 'Guardian sets the protection, Disciplined the duration.',
    requires: { kind: 'signature', mageId: 'ashenWarden' },
    reads: ['Guardian', 'Disciplined'],
  },
  {
    id: 'rekindle',
    name: 'Rekindle',
    cost: 2,
    text: 'Returns defeated summons; Summoner sets how many.',
    requires: { kind: 'signature', mageId: 'pyreMagus' },
    reads: ['Summoner'],
  },
  {
    id: 'cinderVeil',
    name: 'Cinder Veil',
    cost: 2,
    text: 'Screens a troop as it crosses open ground.',
    requires: { kind: 'tag', tag: 'Guardian' },
    reads: ['Guardian'],
  },
  {
    id: 'scorch',
    name: 'Scorch',
    cost: 1,
    text: 'A small burst. The basic fallback — always available.',
    requires: { kind: 'always' },
    reads: ['Evocation'],
  },
];

const roster: Roster = {
  mages,
  summons,
  // A multiset: the roster holds four Ember Hounds, not a flag saying it has one.
  summonCounts: { emberHound: 4, scoriaLancer: 2, flameWisp: 3, cinderBulwark: 1 },
  spells,
};

/**
 * Round 1 of the Starter mirror, pre-filled with the Starter's suggested lineup
 * (§3.2) — three mages against a cap of 3, one per zone, spells pre-picked. The
 * player can change either axis before locking in, and a round they do not touch
 * is one tap.
 */
export function starterMirrorRound1(): PlanState {
  return {
    round: 1,
    mageCap: 3,
    roster,
    energy: 3,
    troops: [
      {
        mageId: 'emberwright',
        summonIds: ['emberHound', 'emberHound'],
        order: { kind: 'hold', zone: 'W' },
      },
      {
        mageId: 'pyreMagus',
        summonIds: ['flameWisp', 'flameWisp', 'scoriaLancer'],
        order: { kind: 'hold', zone: 'E' },
      },
      {
        mageId: 'ashenWarden',
        summonIds: ['cinderBulwark'],
        order: { kind: 'defendBase' },
      },
    ],
    spellSlots: ['fireball', 'flameWard'],
  };
}
