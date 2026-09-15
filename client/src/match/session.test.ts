import { beforeEach, describe, expect, it } from 'vitest';

import { starterMirrorRound1 } from '../plan/fixtures/starterMirror.ts';
import { type ManualClock, manualClock } from './clock.ts';
import { type ScenarioId, scenario } from './fixtures/scenarios.ts';
import { type MatchSession, createFixtureSession } from './session.ts';
import type { BattleSnapshot, CastOutcome, MatchSnapshot } from './types.ts';

const CONNECT_MS = 700;
const OPPONENT_LOCK_MS = 2200;
const CAST_ROUND_TRIP_MS = 180;

let clock: ManualClock;
let session: MatchSession;
let outcomes: CastOutcome[];

function open(id: ScenarioId): MatchSession {
  clock = manualClock();
  outcomes = [];
  session = createFixtureSession({ scenario: scenario(id), runId: `run-${id}`, clock });
  session.onCastOutcome((outcome) => outcomes.push(outcome));
  return session;
}

function snapshot(): MatchSnapshot {
  const current = session.getView().snapshot;
  if (!current) throw new Error('no snapshot yet');
  return current;
}

function battle(): BattleSnapshot {
  const phase = snapshot().phase;
  if (phase.kind !== 'battle') throw new Error(`expected a battle, got ${phase.kind}`);
  return phase.battle;
}

/** Connect, lock the opening plan in, and let the other seat lock in too. */
function intoBattle(id: ScenarioId = 'zoneControl'): void {
  open(id);
  clock.advance(CONNECT_MS);
  session.lockIn(starterMirrorRound1());
  clock.advance(OPPONENT_LOCK_MS);
}

describe('connecting', () => {
  beforeEach(() => open('zoneControl'));

  it('starts with nothing to show and says so', () => {
    expect(session.getView().connection).toEqual({ kind: 'connecting' });
    expect(session.getView().snapshot).toBeNull();
    expect(session.getView().stale).toBe(true);
  });

  it('arrives on the planning phase, not mid-battle', () => {
    clock.advance(CONNECT_MS);

    expect(session.getView().connection).toEqual({ kind: 'live' });
    expect(session.getView().stale).toBe(false);
    expect(snapshot().phase.kind).toBe('planning');
    expect(snapshot().testProfile).toBe(true);
  });

  it('notifies subscribers rather than making them poll', () => {
    const seen: string[] = [];
    session.subscribe((view) => seen.push(view.connection.kind));
    clock.advance(CONNECT_MS);

    expect(seen).toEqual(['live']);
  });
});

describe('a seat claim that fails', () => {
  beforeEach(() => open('claimFailure'));

  it('says why, and that it can be retried', () => {
    clock.advance(CONNECT_MS);
    const { connection } = session.getView();

    expect(connection.kind).toBe('claimFailed');
    if (connection.kind !== 'claimFailed') return;
    expect(connection.reason).toMatch(/seat could not be claimed/i);
    expect(connection.retryable).toBe(true);
  });

  it('recovers on a retry', () => {
    clock.advance(CONNECT_MS);
    session.retryClaim();
    expect(session.getView().connection).toEqual({ kind: 'connecting' });

    clock.advance(CONNECT_MS);
    expect(session.getView().connection).toEqual({ kind: 'live' });
    expect(snapshot().phase.kind).toBe('planning');
  });
});

describe('locking in', () => {
  it('puts your own troops on the field and nobody else’s', () => {
    open('zoneControl');
    clock.advance(CONNECT_MS);
    session.lockIn(starterMirrorRound1());

    const phase = snapshot().phase;
    expect(phase.kind).toBe('planning');
    if (phase.kind !== 'planning') return;
    expect(phase.locked).toBe(true);
    expect(phase.deployment).not.toBeNull();
    expect(phase.deployment!.units.length).toBeGreaterThan(0);
    // The opponent may well have locked in already. Their plan is still theirs.
    expect(phase.deployment!.units.every((unit) => unit.side === 'south')).toBe(true);
  });

  it('starts the battle once the other seat locks in too', () => {
    intoBattle();

    expect(battle().units.some((unit) => unit.side === 'north')).toBe(true);
    expect(battle().units.some((unit) => unit.side === 'south')).toBe(true);
    expect(battle().loadout.map((spell) => spell.spellId)).toEqual(['fireball', 'flameWard']);
  });

  it('ignores a second lock-in', () => {
    open('zoneControl');
    clock.advance(CONNECT_MS);
    session.lockIn(starterMirrorRound1());
    const first = snapshot();
    session.lockIn(starterMirrorRound1());

    expect(snapshot()).toEqual(first);
  });
});

describe('casting', () => {
  it('is pending before it is accepted — the client never draws it first', () => {
    intoBattle();
    const before = battle().energy;

    session.cast({ commandId: 'c1', spellId: 'fireball', at: { x: 187, y: 300 }, tick: battle().tick });
    expect(outcomes).toEqual([{ kind: 'pending', commandId: 'c1' }]);
    expect(battle().energy).toBe(before);

    clock.advance(CAST_ROUND_TRIP_MS);
    expect(outcomes.at(-1)).toEqual({ kind: 'accepted', commandId: 'c1' });
    expect(battle().casts.map((cast) => cast.commandId)).toContain('c1');
  });

  it('is rejected with a reason the screen can say out loud', () => {
    intoBattle();
    session.cast({ commandId: 'c1', spellId: 'notTaken', at: { x: 187, y: 300 }, tick: 0 });
    clock.advance(CAST_ROUND_TRIP_MS);

    expect(outcomes.at(-1)).toEqual({
      kind: 'rejected',
      commandId: 'c1',
      reason: 'notEquipped',
    });
  });

  it('is refused outright while the connection is down', () => {
    intoBattle('dropout');
    clock.advance(160 * 50);
    expect(session.getView().connection.kind).toBe('reconnecting');

    session.cast({ commandId: 'late', spellId: 'fireball', at: { x: 187, y: 300 }, tick: 0 });
    expect(outcomes.at(-1)).toEqual({
      kind: 'rejected',
      commandId: 'late',
      reason: 'notConnected',
    });
  });
});

describe('losing the connection mid-battle', () => {
  beforeEach(() => intoBattle('dropout'));

  it('keeps the last authoritative picture, marked stale', () => {
    clock.advance(160 * 50);
    const view = session.getView();

    expect(view.connection).toEqual({ kind: 'reconnecting', attempt: 1 });
    expect(view.stale).toBe(true);
    expect(view.snapshot).not.toBeNull();
    expect(view.snapshot!.phase.kind).toBe('battle');
  });

  it('recovers to where the battle actually got to, not where we left it', () => {
    clock.advance(160 * 50);
    const abandonedAt = battle().tick;

    clock.advance(6000);
    expect(session.getView().connection).toEqual({ kind: 'live' });
    expect(session.getView().stale).toBe(false);
    // Six seconds of battle happened without us: the jump is the proof that
    // recovery came from the server rather than from a client that kept ticking.
    expect(battle().tick).toBeGreaterThan(abandonedAt + 100);
  });

  it('fails a cast that was in flight rather than replaying it', () => {
    clock.advance(159 * 50);
    session.cast({ commandId: 'lost', spellId: 'fireball', at: { x: 187, y: 300 }, tick: 0 });
    clock.advance(50);

    expect(outcomes.at(-1)).toEqual({
      kind: 'rejected',
      commandId: 'lost',
      reason: 'notConnected',
    });

    clock.advance(6000 + 1000);
    expect(outcomes.filter((outcome) => outcome.commandId === 'lost')).toHaveLength(2);
    expect(battle().casts.map((cast) => cast.commandId)).not.toContain('lost');
  });
});

describe('how a round ends', () => {
  it('ends the test, not the match, when the round simply finishes', () => {
    intoBattle('zoneControl');
    clock.advance(40_000);

    const phase = snapshot().phase;
    expect(phase.kind).toBe('matchOver');
    if (phase.kind !== 'matchOver') return;
    expect(phase.result.ending.kind).toBe('testComplete');
    expect(phase.result.lastRound.ending.kind).toBe('roundComplete');
  });

  it('ends the match outright when a base comes down', () => {
    intoBattle('baseDestruction');
    clock.advance(40_000);

    const phase = snapshot().phase;
    expect(phase.kind).toBe('matchOver');
    if (phase.kind !== 'matchOver') return;
    expect(phase.result.ending).toEqual({ kind: 'baseDestroyed', winner: 'north' });
    expect(phase.result.baseHp.south.hp).toBe(0);
    expect(phase.result.lastRound.ending).toEqual({ kind: 'baseDestroyed', winner: 'north' });
  });
});

describe('leaving', () => {
  it('is a terminal state the screen can act on', () => {
    intoBattle();
    session.leave();
    expect(session.getView().connection).toEqual({ kind: 'ended', reason: 'left' });
  });
});
