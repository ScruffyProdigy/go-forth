/**
 * Chrome shared by the three wizard steps (JQ-293).
 *
 * The Board toggle is what lets the wizard get out of the way: it swaps the
 * step's body for the live map — showing the current, uncommitted plan — while
 * leaving the step header and Back/Next in place, so peeking at the board is a
 * look rather than a navigation. Edits survive it because nothing unmounts but
 * the body.
 *
 * Resonance sits above the body on every step, not only behind that toggle.
 * It is the phase's headline number and it moves as mages are fielded, so
 * putting it a tap away would separate the decision from its consequence —
 * which is the one thing JQ-293 asks this screen not to do.
 */

import { type ReactNode, useState } from 'react';

import { PlanMap } from './PlanMap.tsx';
import { ResonanceHeadline } from './ResonanceHeadline.tsx';
import type { PlanState } from './types.ts';

export interface StepFrameProps {
  readonly plan: PlanState;
  readonly title: string;
  readonly stepNumber: number;
  readonly stepCount: number;
  readonly onBack: () => void;
  readonly onNext: () => void;
  readonly nextLabel: string;
  readonly highlightMageId?: string;
  readonly children: ReactNode;
}

export function StepFrame({
  plan,
  title,
  stepNumber,
  stepCount,
  onBack,
  onNext,
  nextLabel,
  highlightMageId,
  children,
}: StepFrameProps) {
  const [showingBoard, setShowingBoard] = useState(false);

  return (
    <section className="step" aria-label={title}>
      <header className="step-header">
        <button type="button" className="link-button" onClick={onBack}>
          Back
        </button>
        <div className="step-title">
          <h2>{title}</h2>
          <p className="step-count">
            Step {stepNumber} of {stepCount}
          </p>
        </div>
        <button
          type="button"
          className={showingBoard ? 'link-button is-active' : 'link-button'}
          aria-pressed={showingBoard}
          onClick={() => setShowingBoard((showing) => !showing)}
        >
          {showingBoard ? 'Done' : 'Board'}
        </button>
      </header>

      <ResonanceHeadline plan={plan} />

      {showingBoard ? (
        <div className="step-board" data-testid="step-board">
          <PlanMap plan={plan} highlightMageId={highlightMageId} />
          <p className="step-board-note">Your plan as it stands. Nothing is locked in yet.</p>
        </div>
      ) : (
        <div className="step-body">{children}</div>
      )}

      <footer className="step-footer">
        <button type="button" className="primary-button" onClick={onNext}>
          {nextLabel}
        </button>
      </footer>
    </section>
  );
}
