/**
 * The plan phase (JQ-293).
 *
 * Planning is roughly half the gameplay, not an interstitial — so this is a
 * screen with its own structure rather than a modal over the battle. A hub shows
 * the whole pre-filled plan as a board position and locks it in with one tap;
 * each step is a full screen entered from the hub, and any step can show the
 * board without losing its place.
 *
 * State lives in a pure reducer (`planReducer`) over a fixture-supplied
 * `PlanState`. The fixture is the seam: when JQ-287 settles orders and placement
 * and JQ-297 settles the spell loadout, the real plan arrives from the server and
 * only `fixtures/` changes.
 */

import { useReducer, useState } from 'react';

import type { PlanResolver } from '../match/resolve.ts';
import { RoundHub } from './RoundHub.tsx';
import { StepFrame } from './StepFrame.tsx';
import { WaitingForOpponent } from './WaitingForOpponent.tsx';
import { planReducer } from './planReducer.ts';
import { stepSummaries, type StepId } from './derive.ts';
import { starterMirrorRound1 } from './fixtures/starterMirror.ts';
import { ChooseSpellsStep } from './steps/ChooseSpellsStep.tsx';
import { ChooseTroopsStep } from './steps/ChooseTroopsStep.tsx';
import { GiveOrdersStep } from './steps/GiveOrdersStep.tsx';
import { TroopDetail } from './steps/TroopDetail.tsx';
import type { PlanState } from './types.ts';

type View = 'hub' | StepId | 'waiting';

const STEP_TITLES: Record<StepId, string> = {
  troops: 'Choose troops',
  spells: 'Choose spells',
  orders: 'Give orders',
};

export interface PlanScreenProps {
  readonly initialPlan?: PlanState;
  /** Called when the player locks in — the future "submit plan" call. */
  readonly onLockIn?: (plan: PlanState) => void;
  /**
   * Asks what the plan currently means (JQ-311). Supplied by the match layer,
   * which knows whether there is a server to ask; absent, the screen falls back
   * to the derivations JQ-293 shipped with and nothing blocks lock-in.
   */
  readonly resolve?: PlanResolver;
  /**
   * Where lock-in leads. The match layer takes this over so that "locked" means
   * the server has the plan, not that a local flag was set — which is why the
   * built-in waiting screen is only the fallback.
   */
  readonly waitingView?: 'internal' | 'external';
}

export function PlanScreen({
  initialPlan,
  onLockIn,
  resolve,
  waitingView = 'internal',
}: PlanScreenProps) {
  const [plan, dispatch] = useReducer(planReducer, initialPlan ?? starterMirrorRound1());
  const [view, setView] = useState<View>('hub');
  const [detailMageId, setDetailMageId] = useState<string | null>(null);
  const resolved = resolve?.(plan);

  /** Steps that exist this round, in order. Absent steps are skipped by Next. */
  const presentSteps = stepSummaries(plan)
    .filter((step) => step.fold !== 'absent')
    .map((step) => step.id);

  function goToStepAfter(step: StepId): void {
    const next = presentSteps[presentSteps.indexOf(step) + 1];
    setView(next ?? 'hub');
  }

  if (view === 'waiting') {
    return <WaitingForOpponent plan={plan} onUnlock={() => setView('hub')} />;
  }

  if (view === 'hub') {
    return (
      <RoundHub
        plan={plan}
        resolved={resolved}
        onOpenStep={(step) => setView(step)}
        onLockIn={() => {
          onLockIn?.(plan);
          if (waitingView === 'internal') setView('waiting');
        }}
      />
    );
  }

  if (view === 'troops' && detailMageId !== null) {
    return (
      <TroopDetail
        plan={plan}
        mageId={detailMageId}
        dispatch={dispatch}
        onDone={() => setDetailMageId(null)}
      />
    );
  }

  const stepNumber = presentSteps.indexOf(view) + 1;
  const isLastStep = stepNumber === presentSteps.length;

  return (
    <StepFrame
      plan={plan}
      title={STEP_TITLES[view]}
      stepNumber={stepNumber}
      stepCount={presentSteps.length}
      onBack={() => setView('hub')}
      onNext={() => goToStepAfter(view)}
      nextLabel={isLastStep ? 'Review plan' : 'Next'}
      highlightMageId={detailMageId ?? undefined}
    >
      {view === 'troops' ? (
        <ChooseTroopsStep plan={plan} dispatch={dispatch} onCustomise={setDetailMageId} />
      ) : null}
      {view === 'spells' ? (
        <ChooseSpellsStep plan={plan} dispatch={dispatch} resolved={resolved} />
      ) : null}
      {view === 'orders' ? <GiveOrdersStep plan={plan} dispatch={dispatch} /> : null}
    </StepFrame>
  );
}
