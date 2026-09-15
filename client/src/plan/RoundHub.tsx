/**
 * The round hub (JQ-293).
 *
 * The steps are a wizard — one decision per screen — but a wizard alone cannot
 * satisfy "a round with no changes is one tap to lock in", because three steps
 * is three Nexts. The hub is what reconciles the two: the whole plan on one
 * screen, as a board position, with Lock In right there. The wizard is for
 * deciding; the hub is for confirming.
 *
 * Steps appear here at their fold depth (§3.2): absent when the decision does
 * not exist yet, one line when it has a good default, expanded only on tap.
 */

import type { ResolvedPlan } from '../match/resolve.ts';
import { PlanMap } from './PlanMap.tsx';
import { ResonanceHeadline } from './ResonanceHeadline.tsx';
import { stepSummaries, type StepId } from './derive.ts';
import type { PlanState } from './types.ts';

export interface RoundHubProps {
  readonly plan: PlanState;
  readonly onOpenStep: (step: StepId) => void;
  readonly onLockIn: () => void;
  /**
   * The server's reading of this plan, when there is a server to ask (JQ-311).
   * Absent means nothing is blocking and Lock In behaves as JQ-293 shipped it.
   */
  readonly resolved?: ResolvedPlan;
}

export function RoundHub({ plan, onOpenStep, onLockIn, resolved }: RoundHubProps) {
  const steps = stepSummaries(plan);
  const blockers = resolved?.blockers ?? [];

  return (
    <section className="hub" aria-label={`Round ${plan.round} plan`}>
      <header className="hub-header">
        <h1>Round {plan.round}</h1>
      </header>

      <ResonanceHeadline plan={plan} />
      <PlanMap plan={plan} />

      <ul className="hub-steps">
        {steps
          .filter((step) => step.fold !== 'absent')
          .map((step) => (
            <li key={step.id}>
              <button
                type="button"
                className={step.needsAttention ? 'hub-step needs-attention' : 'hub-step'}
                onClick={() => onOpenStep(step.id)}
              >
                <span className="hub-step-title">{step.title}</span>
                <span className="hub-step-line">{step.line}</span>
              </button>
            </li>
          ))}
      </ul>

      {blockers.length > 0 ? (
        <ul className="lock-blockers" data-testid="lock-blockers">
          {blockers.map((blocker) => (
            <li key={`${blocker.kind}-${blocker.message}`}>{blocker.message}</li>
          ))}
        </ul>
      ) : null}

      {/*
        A blocked plan is refused here rather than at world creation. JQ-304 is
        the bug where the sim rejected a plan the client had already accepted —
        after lock-in, on a screen with nothing left to change. Disabling the
        button keeps the refusal next to the thing that can fix it.
      */}
      <button
        type="button"
        className="primary-button lock-in"
        onClick={onLockIn}
        disabled={blockers.length > 0}
      >
        Lock in
      </button>
    </section>
  );
}
