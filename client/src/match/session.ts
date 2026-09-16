/**
 * The transport seam (JQ-311).
 *
 * Everything above this line renders authoritative state and sends commands.
 * Everything below it is how that state arrives. Today the only implementation
 * is a fixture; JQ-309 adds a real one over its realtime session, and the
 * screens do not find out.
 *
 * The rules the seam exists to enforce:
 *
 *  - The client never advances the battle. It renders snapshots it was handed.
 *  - A dropped connection does not blank the screen. The last snapshot stays,
 *    marked stale, until the server says otherwise (AC 4).
 *  - Recovery is authoritative and wholesale. Whatever the client still believed
 *    is discarded and replaced; in-flight casts are reported failed rather than
 *    resent, because a resend is a second cast (AC 4, "no automatic replay of
 *    accepted casts"). Deduplicating retries properly is JQ-310.
 */

import type { PlanState } from '../plan/types.ts';
import { type Clock, realClock } from './clock.ts';
import { TWO_LANE_MAP, type MapGeometry } from './geometry.ts';
import {
  type CastAttempt,
  type ScriptedState,
  advance,
  applyCast,
  openingState,
  toSnapshot,
} from './fixtures/scriptedBattle.ts';
import { TICK_RATE } from './fixtures/scriptedBattle.ts';
import type { Scenario } from './fixtures/scenarios.ts';
import { resolvePlanLocally } from './fixtures/resolvePlan.ts';
import {
  type CastCommand,
  type CastOutcome,
  type LoadoutSpell,
  type MatchSnapshot,
  type MatchView,
  type RoundResult,
  type Side,
  opposing,
} from './types.ts';

export interface MatchSession {
  getView(): MatchView;
  subscribe(listener: (view: MatchView) => void): () => void;
  /** Cast outcomes are a stream, not view state: each one is a single answer. */
  onCastOutcome(listener: (outcome: CastOutcome) => void): () => void;
  lockIn(plan: PlanState): void;
  cast(command: CastCommand): void;
  /** Only meaningful while the claim failed and was retryable. */
  retryClaim(): void;
  leave(): void;
  dispose(): void;
}

/* -------------------------------------------------- fixture-only timings -- */

/** How long the fixture pretends a seat claim takes. */
const CONNECT_MS = 700;
/** How long the other seat takes to lock in after we do. */
const OPPONENT_LOCK_MS = 2200;
/** A cast's round trip. Long enough that "sent" is a state you can see. */
const CAST_ROUND_TRIP_MS = 180;
const MS_PER_TICK = 1000 / TICK_RATE;

export interface FixtureSessionOptions {
  readonly scenario: Scenario;
  readonly runId: string;
  readonly clock?: Clock;
  readonly map?: MapGeometry;
}

export function createFixtureSession(options: FixtureSessionOptions): MatchSession {
  const { scenario, runId } = options;
  const clock = options.clock ?? realClock;
  const map = options.map ?? TWO_LANE_MAP;
  const you = scenario.you;
  const them = opposing(you);

  const viewListeners: ((view: MatchView) => void)[] = [];
  const castListeners: ((outcome: CastOutcome) => void)[] = [];
  const handles: number[] = [];

  let view: MatchView = { connection: { kind: 'connecting' }, snapshot: null, stale: true };
  let battle: ScriptedState | null = null;
  let loadout: readonly LoadoutSpell[] = [];
  let lockedPlan: PlanState | null = null;
  let roundsWon: Record<Side, number> = { north: 0, south: 0 };
  /** Casts sent and not yet answered. Dropped, never replayed, on a disconnect. */
  let inFlight: CastCommand[] = [];
  let disposed = false;
  let deliveringSnapshots = true;
  /** Local, because a retry clears it and the scenario itself is read-only. */
  let claimFails = scenario.claimFails;

  function at(ms: number, run: () => void): void {
    const handle = clock.after(ms, () => {
      if (!disposed) run();
    });
    handles.push(handle);
  }

  function publish(next: MatchView): void {
    view = next;
    for (const listener of viewListeners) listener(view);
  }

  function tellCast(outcome: CastOutcome): void {
    for (const listener of castListeners) listener(outcome);
  }

  /** Republishes with the current connection, so `stale` is never set by hand. */
  function show(snapshot: MatchSnapshot | null, connection = view.connection): void {
    publish({ connection, snapshot, stale: connection.kind !== 'live' });
  }

  /* ---------------------------------------------------------- connecting -- */

  function connect(): void {
    publish({ connection: { kind: 'connecting' }, snapshot: view.snapshot, stale: true });
    at(CONNECT_MS, () => {
      if (claimFails) {
        show(view.snapshot, {
          kind: 'claimFailed',
          reason: claimFails.reason,
          retryable: claimFails.retryable,
        });
        return;
      }
      show(planningSnapshot(false, null), { kind: 'live' });
    });
  }

  function baseHpNow() {
    return battle
      ? battle.baseHp
      : {
          north: { hp: map.baseMaxHp, maxHp: map.baseMaxHp },
          south: { hp: map.baseMaxHp, maxHp: map.baseMaxHp },
        };
  }

  function baseSnapshot(phase: MatchSnapshot['phase']): MatchSnapshot {
    return {
      runId,
      matchId: scenario.matchId,
      you,
      round: 1,
      roundsWon,
      baseHp: baseHpNow(),
      phase,
      testProfile: true,
    };
  }

  function planningSnapshot(locked: boolean, plan: PlanState | null): MatchSnapshot {
    const current = plan ?? scenario.openingPlan;
    return baseSnapshot({
      kind: 'planning',
      plan: current,
      locked,
      deployment:
        locked && battle
          ? toSnapshot(battle, you, loadout, map, { onlyYourUnits: true })
          : null,
    });
  }

  /* ------------------------------------------------------------ the round -- */

  function startDeployment(plan: PlanState): void {
    lockedPlan = plan;
    loadout = resolvePlanLocally(plan).loadout;
    // Only your army exists so far, because only your plan does: the opponent's
    // is not merely hidden on screen, it is not in the snapshot to be found.
    battle = openingState([{ side: you, plan }], map);
    show(planningSnapshot(true, plan));
    at(OPPONENT_LOCK_MS, startBattle);
  }

  function startBattle(): void {
    if (!lockedPlan) return;
    battle = openingState(
      [
        { side: you, plan: lockedPlan },
        { side: them, plan: scenario.opponentPlan },
      ],
      map,
    );
    showBattle();
    scheduleTick();
  }

  function showBattle(): void {
    if (!battle || !deliveringSnapshots) return;
    show(baseSnapshot({ kind: 'battle', battle: toSnapshot(battle, you, loadout, map) }));
  }

  function scheduleTick(): void {
    at(MS_PER_TICK, () => {
      if (!battle) return;
      battle = advance(battle, map);
      runOpponentCasts();

      if (battle.ending !== null) {
        finish();
        return;
      }

      maybeDropConnection();
      showBattle();
      scheduleTick();
    });
  }

  function runOpponentCasts(): void {
    if (!battle) return;
    for (const scripted of scenario.opponentCasts) {
      if (scripted.atTick !== battle.tick) continue;
      const attempt: CastAttempt = applyCast(
        battle,
        them,
        {
          commandId: `${runId}-them-${scripted.atTick}`,
          spellId: scripted.spellId,
          at: scripted.at,
          tick: battle.tick,
        },
        // The opponent's loadout is the server's business; the fixture gives it
        // the one spell it is scripted to cast so the cost is charged somewhere.
        [{ spellId: scripted.spellId, name: scripted.spellName, cost: 0, effect: '' }],
        map,
      );
      battle = attempt.state;
    }
  }

  /**
   * The drop, and the recovery.
   *
   * The battle keeps running while the client is deaf to it — that is the whole
   * point. When the connection comes back the player is shown where the battle
   * actually is, not where it was when they lost it.
   */
  function maybeDropConnection(): void {
    const drop = scenario.dropout;
    if (!drop || !battle || battle.tick !== drop.atTick) return;

    deliveringSnapshots = false;
    for (const command of inFlight) {
      tellCast({ kind: 'rejected', commandId: command.commandId, reason: 'notConnected' });
    }
    inFlight = [];
    show(view.snapshot, { kind: 'reconnecting', attempt: 1 });

    at(drop.forMs, () => {
      deliveringSnapshots = true;
      // Wholesale replacement: the recovered snapshot is the server's, and
      // nothing the client was holding is merged back into it.
      show(
        battle && battle.ending === null
          ? baseSnapshot({ kind: 'battle', battle: toSnapshot(battle, you, loadout, map) })
          : view.snapshot,
        { kind: 'live' },
      );
    });
  }

  function finish(): void {
    if (!battle || battle.ending === null) return;
    const ending = battle.ending;

    const lastRound: RoundResult = {
      round: 1,
      ending,
      baseHp: battle.baseHp,
      zones: toSnapshot(battle, you, loadout, map).zones,
      zoneScore: toSnapshot(battle, you, loadout, map).zoneScore,
    };

    if (ending.kind === 'roundComplete' && ending.winner) {
      roundsWon = { ...roundsWon, [ending.winner]: roundsWon[ending.winner] + 1 };
    }
    if (ending.kind === 'baseDestroyed') {
      roundsWon = { ...roundsWon, [ending.winner]: roundsWon[ending.winner] + 1 };
    }

    // A destroyed base ends the match on the spot. An ordinary round does not —
    // and since the opening demo plays exactly one, what it ends is the *test*.
    deliveringSnapshots = true;
    show(
      baseSnapshot({
        kind: 'matchOver',
        result: {
          ending:
            ending.kind === 'baseDestroyed'
              ? { kind: 'baseDestroyed', winner: ending.winner }
              : { kind: 'testComplete', roundWinner: ending.winner },
          roundsWon,
          baseHp: battle.baseHp,
          lastRound,
        },
      }),
      { kind: 'live' },
    );
  }

  /* -------------------------------------------------------------- the api -- */

  connect();

  return {
    getView: () => view,
    subscribe(listener) {
      viewListeners.push(listener);
      return () => {
        const index = viewListeners.indexOf(listener);
        if (index >= 0) viewListeners.splice(index, 1);
      };
    },
    onCastOutcome(listener) {
      castListeners.push(listener);
      return () => {
        const index = castListeners.indexOf(listener);
        if (index >= 0) castListeners.splice(index, 1);
      };
    },
    lockIn(plan) {
      if (view.connection.kind !== 'live') return;
      const phase = view.snapshot?.phase;
      if (phase?.kind !== 'planning' || phase.locked) return;
      startDeployment(plan);
    },
    cast(command) {
      if (view.connection.kind !== 'live') {
        tellCast({ kind: 'rejected', commandId: command.commandId, reason: 'notConnected' });
        return;
      }
      inFlight = [...inFlight, command];
      tellCast({ kind: 'pending', commandId: command.commandId });

      at(CAST_ROUND_TRIP_MS, () => {
        // The disconnect already answered for this one, and the player has been
        // told it failed. Landing it now would be the replay this must not do.
        if (!inFlight.some((entry) => entry.commandId === command.commandId)) return;
        inFlight = inFlight.filter((entry) => entry.commandId !== command.commandId);
        if (!battle) {
          tellCast({ kind: 'rejected', commandId: command.commandId, reason: 'roundOver' });
          return;
        }
        const attempt = applyCast(battle, you, command, loadout, map);
        battle = attempt.state;
        tellCast(
          attempt.rejection
            ? { kind: 'rejected', commandId: command.commandId, reason: attempt.rejection }
            : { kind: 'accepted', commandId: command.commandId },
        );
        showBattle();
      });
    },
    retryClaim() {
      if (view.connection.kind !== 'claimFailed' || !view.connection.retryable) return;
      // A retryable claim failure is transient by definition, so the retry works.
      claimFails = null;
      connect();
    },
    leave() {
      show(view.snapshot, { kind: 'ended', reason: 'left' });
    },
    dispose() {
      disposed = true;
      for (const handle of handles) clock.clear(handle);
      viewListeners.length = 0;
      castListeners.length = 0;
    },
  };
}
