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

import { PlanMap } from './PlanMap.tsx';
import { ResonanceHeadline } from './ResonanceHeadline.tsx';
import { stepSummaries, type StepId } from './derive.ts';
import type { PlanState } from './types.ts';

export interface RoundHubProps {
  readonly plan: PlanState;
  readonly onOpenStep: (step: StepId) => void;
  readonly onLockIn: () => void;
}

export function RoundHub({ plan, onOpenStep, onLockIn }: RoundHubProps) {
  const steps = stepSummaries(plan);

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

      <button type="button" className="primary-button lock-in" onClick={onLockIn}>
        Lock in
      </button>
    </section>
  );
}
