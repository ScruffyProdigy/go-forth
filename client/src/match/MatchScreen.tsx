/**
 * The opening demo, end to end (JQ-311).
 *
 * One screen owns the session and shows whatever the session's current view
 * calls for: connecting, a refused seat, planning, your troops taking position,
 * the battle, the result, a terminal return. Nothing below it knows a session
 * exists — they take authoritative state and give back commands — so JQ-309
 * swapping the fixture for a real transport changes this file and no other.
 *
 * The plan screen is the delivered JQ-293 one, unmodified in structure: it is
 * handed a resolver and a lock-in callback, and its own waiting screen is turned
 * off because "locked" now means the server has the plan.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { lobbyUrl } from '../env.ts';
import { PlanScreen } from '../plan/PlanScreen.tsx';
import type { PlanState } from '../plan/types.ts';
import {
  ClaimFailedScreen,
  ConnectingScreen,
  LeftScreen,
  ScenarioPicker,
} from './ConnectionScreens.tsx';
import { ResultScreen } from './ResultScreen.tsx';
import { BattleMap } from './battle/BattleMap.tsx';
import { BattleScreen } from './battle/BattleScreen.tsx';
import { type ScenarioId, isScenarioId, scenario } from './fixtures/scenarios.ts';
import { resolvePlanLocally } from './fixtures/resolvePlan.ts';
import { type MatchSession, createFixtureSession } from './session.ts';
import {
  CAST_REJECTION_TEXT,
  type LoadoutSpell,
  type MapPoint,
  type MatchView,
} from './types.ts';

const CONNECTING: MatchView = {
  connection: { kind: 'connecting' },
  snapshot: null,
  stale: true,
};

/** Fixture-only: lets a reviewer open the demo straight into a given run. */
function scenarioFromUrl(): ScenarioId {
  if (typeof window === 'undefined') return 'zoneControl';
  const asked = new URLSearchParams(window.location.search).get('scenario');
  return asked && isScenarioId(asked) ? asked : 'zoneControl';
}

let runCounter = 0;

export interface MatchScreenProps {
  readonly initialScenario?: ScenarioId;
}

export function MatchScreen({ initialScenario }: MatchScreenProps) {
  const [run, setRun] = useState(() => {
    const id = initialScenario ?? scenarioFromUrl();
    return { scenarioId: id, runId: `${id}-${(runCounter += 1)}` };
  });
  const [view, setView] = useState<MatchView>(CONNECTING);
  const [feedback, setFeedback] = useState<string | null>(null);

  const session = useRef<MatchSession | null>(null);
  /** What each command was, so its outcome can be reported in the player's terms. */
  const sent = useRef(new Map<string, string>());
  const castCounter = useRef(0);

  useEffect(() => {
    sent.current = new Map();
    castCounter.current = 0;
    setFeedback(null);

    const opened = createFixtureSession({
      scenario: scenario(run.scenarioId),
      runId: run.runId,
    });
    session.current = opened;
    setView(opened.getView());

    const unsubscribeView = opened.subscribe(setView);
    const unsubscribeCasts = opened.onCastOutcome((outcome) => {
      const what = sent.current.get(outcome.commandId) ?? 'The spell';
      if (outcome.kind === 'pending') setFeedback(`${what} — sent…`);
      if (outcome.kind === 'accepted') setFeedback(`${what} — landed.`);
      if (outcome.kind === 'rejected') {
        setFeedback(`${what} — ${CAST_REJECTION_TEXT[outcome.reason]}`);
      }
    });

    return () => {
      unsubscribeView();
      unsubscribeCasts();
      opened.dispose();
      session.current = null;
    };
  }, [run]);

  const startRun = useCallback((scenarioId: ScenarioId) => {
    // A new run, not a reset: a fresh run id, a fresh session, nothing carried.
    setRun({ scenarioId, runId: `${scenarioId}-${(runCounter += 1)}` });
    setView(CONNECTING);
  }, []);

  const lockIn = useCallback((plan: PlanState) => session.current?.lockIn(plan), []);

  const cast = useCallback(
    (spell: LoadoutSpell, at: MapPoint, where: string) => {
      const phase = session.current?.getView().snapshot?.phase;
      const tick = phase?.kind === 'battle' ? phase.battle.tick : 0;
      const commandId = `${run.runId}-cast-${(castCounter.current += 1)}`;
      sent.current.set(commandId, `${spell.name} on ${where}`);
      session.current?.cast({ commandId, spellId: spell.spellId, at, tick });
    },
    [run.runId],
  );

  const lobby = useMemo(lobbyUrl, []);
  const { connection, snapshot, stale } = view;

  if (connection.kind === 'claimFailed') {
    return (
      <>
        <ClaimFailedScreen
          reason={connection.reason}
          retryable={connection.retryable}
          onRetry={() => session.current?.retryClaim()}
          lobbyUrl={lobby}
        />
        <ScenarioPicker current={run.scenarioId} onPick={startRun} />
      </>
    );
  }

  if (connection.kind === 'ended') {
    return (
      <>
        <LeftScreen onNewTest={() => startRun(run.scenarioId)} lobbyUrl={lobby} />
        <ScenarioPicker current={run.scenarioId} onPick={startRun} />
      </>
    );
  }

  if (!snapshot) return <ConnectingScreen />;

  const { phase, you } = snapshot;

  if (phase.kind === 'matchOver') {
    return (
      <>
        <ResultScreen
          result={phase.result}
          you={you}
          testProfile={snapshot.testProfile}
          onNewTest={() => startRun(run.scenarioId)}
          onReturnToLobby={() => session.current?.leave()}
          lobbyUrl={lobby}
        />
        <ScenarioPicker current={run.scenarioId} onPick={startRun} />
      </>
    );
  }

  return (
    <>
      <StaleBanner stale={stale} connection={connection.kind} />

      {phase.kind === 'planning' && !phase.locked ? (
        <PlanScreen
          key={run.runId}
          initialPlan={phase.plan}
          resolve={resolvePlanLocally}
          waitingView="external"
          onLockIn={lockIn}
        />
      ) : null}

      {phase.kind === 'planning' && phase.locked ? (
        <section className="waiting" aria-label="Waiting for your opponent">
          <header className="hub-header">
            <h1>Locked in</h1>
            <p className="waiting-note">
              Your troops are taking position. You will see theirs when the battle starts.
            </p>
          </header>
          {phase.deployment ? (
            <BattleMap
              snapshot={phase.deployment}
              you={you}
              baseHp={snapshot.baseHp}
              stale={stale}
            />
          ) : null}
        </section>
      ) : null}

      {phase.kind === 'battle' ? (
        <BattleScreen
          snapshot={phase.battle}
          you={you}
          round={snapshot.round}
          baseHp={snapshot.baseHp}
          onCast={cast}
          feedback={feedback}
          stale={stale}
        />
      ) : null}

      {phase.kind === 'roundOver' ? (
        <section className="waiting" aria-label="Round over">
          <header className="hub-header">
            <h1>Round {phase.result.round} over</h1>
            <p className="waiting-note">Getting the next round ready…</p>
          </header>
        </section>
      ) : null}
    </>
  );
}

/**
 * Says the picture is old, without taking it away.
 *
 * Blanking to a spinner loses the player's place and tells them less than the
 * stale board does — they can still see where their troops were. What they must
 * not do is act on it, which is why the cast bar goes quiet at the same time.
 */
function StaleBanner({
  stale,
  connection,
}: {
  readonly stale: boolean;
  readonly connection: string;
}) {
  if (!stale) return null;
  return (
    <p className="stale-banner" role="status" aria-live="polite" data-testid="stale-banner">
      {connection === 'reconnecting'
        ? 'Connection lost — reconnecting. The battle is carrying on without you.'
        : 'Connecting…'}
    </p>
  );
}
