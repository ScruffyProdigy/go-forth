/**
 * The runs the opening demo can be put through (JQ-311).
 *
 * JQ-311 AC 4 asks for loading, claim failure, disconnection, authoritative
 * recovery and terminal return to all be *legible*. A state nobody can reach is
 * a state nobody has looked at, so each one is a scenario here and the demo lets
 * you pick between them. They are fixtures, and they go when JQ-309 lands a real
 * session — but until a real server can be made to drop a connection on cue,
 * this is the only way those screens get reviewed at all.
 */

import type { PlanState } from '../../plan/types.ts';
import { starterMirrorRound1 } from '../../plan/fixtures/starterMirror.ts';
import { THREE_ZONE_MAP } from '../geometry.ts';
import type { MapPoint, Side } from '../types.ts';

export type ScenarioId = 'zoneControl' | 'baseDestruction' | 'claimFailure' | 'dropout';

export interface ScriptedOpponentCast {
  readonly atTick: number;
  readonly spellId: string;
  readonly spellName: string;
  readonly at: MapPoint;
}

export interface Scenario {
  readonly id: ScenarioId;
  readonly label: string;
  readonly summary: string;
  readonly matchId: string;
  readonly you: Side;
  /** The plan the server opens with. The player edits it before locking in. */
  readonly openingPlan: PlanState;
  readonly opponentPlan: PlanState;
  readonly opponentCasts: readonly ScriptedOpponentCast[];
  readonly claimFails: { readonly reason: string; readonly retryable: boolean } | null;
  readonly dropout: { readonly atTick: number; readonly forMs: number } | null;
}

/**
 * The opponent's plan. Never sent to the client in a real session — it exists
 * here because the fixture is standing in for the server, which does know it.
 */
function opponentPlan(orders: 'holdTheLine' | 'allIn'): PlanState {
  const base = starterMirrorRound1();
  const troops =
    orders === 'allIn'
      ? base.troops.map((troop) => ({ ...troop, order: { kind: 'pushEnemyBase' } as const }))
      : base.troops.map((troop, index) =>
          index === 2 ? { ...troop, order: { kind: 'hold', zone: 'C' } as const } : troop,
        );

  return { ...base, troops };
}

const CENTRE = THREE_ZONE_MAP.width / 2;

const SCENARIOS: Record<ScenarioId, Scenario> = {
  zoneControl: {
    id: 'zoneControl',
    label: 'Ordinary round',
    summary: 'Both sides hold ground. The round ends on zone control, both bases standing.',
    matchId: 'demo-zone-control',
    you: 'south',
    openingPlan: starterMirrorRound1(),
    opponentPlan: opponentPlan('holdTheLine'),
    opponentCasts: [
      { atTick: 140, spellId: 'scorch', spellName: 'Scorch', at: { x: CENTRE, y: 300 } },
      { atTick: 360, spellId: 'fireball', spellName: 'Fireball', at: { x: CENTRE, y: 380 } },
    ],
    claimFails: null,
    dropout: null,
  },
  baseDestruction: {
    id: 'baseDestruction',
    label: 'Base destroyed',
    summary: 'They commit everything to your base. If it falls, the match is over at once.',
    matchId: 'demo-base-destruction',
    you: 'south',
    openingPlan: starterMirrorRound1(),
    opponentPlan: opponentPlan('allIn'),
    opponentCasts: [
      { atTick: 200, spellId: 'fireball', spellName: 'Fireball', at: { x: CENTRE, y: 470 } },
    ],
    claimFails: null,
    dropout: null,
  },
  dropout: {
    id: 'dropout',
    label: 'Dropped mid-battle',
    summary: 'The connection dies during the battle and recovers to wherever the server got to.',
    matchId: 'demo-dropout',
    you: 'south',
    openingPlan: starterMirrorRound1(),
    opponentPlan: opponentPlan('holdTheLine'),
    opponentCasts: [
      { atTick: 140, spellId: 'scorch', spellName: 'Scorch', at: { x: CENTRE, y: 300 } },
    ],
    claimFails: null,
    // Six seconds of battle happen without us. Recovery has to be visibly a jump.
    dropout: { atTick: 160, forMs: 6000 },
  },
  claimFailure: {
    id: 'claimFailure',
    label: 'Seat claim fails',
    summary: 'The seat token is refused. Retrying works — the failure was transient.',
    matchId: 'demo-claim-failure',
    you: 'south',
    openingPlan: starterMirrorRound1(),
    opponentPlan: opponentPlan('holdTheLine'),
    opponentCasts: [],
    claimFails: { reason: 'The seat could not be claimed — the match service did not answer.', retryable: true },
    dropout: null,
  },
};

export const SCENARIO_IDS: readonly ScenarioId[] = [
  'zoneControl',
  'baseDestruction',
  'dropout',
  'claimFailure',
];

export function scenario(id: ScenarioId): Scenario {
  return SCENARIOS[id];
}

export function isScenarioId(value: string): value is ScenarioId {
  return (SCENARIO_IDS as readonly string[]).includes(value);
}
