/**
 * After Lock In (JQ-293).
 *
 * A player who locks in first is never shown an idle wait. There is no
 * countdown here and no spinner — the board is already doing something worth
 * watching, because the troops are taking the positions the plan just gave them.
 *
 * The backstop that stops a stalled match is a constant, not a number on screen:
 * showing it would make the phase a timer again, which §3.2 explicitly drops.
 */

import { PlanMap } from './PlanMap.tsx';
import type { PlanState } from './types.ts';

export interface WaitingForOpponentProps {
  readonly plan: PlanState;
  readonly onUnlock: () => void;
}

export function WaitingForOpponent({ plan, onUnlock }: WaitingForOpponentProps) {
  return (
    <section className="waiting" aria-label="Waiting for your opponent">
      <header className="hub-header">
        <h1>Locked in</h1>
        <p className="waiting-note">Your troops are taking position.</p>
      </header>

      <PlanMap plan={plan} />

      <button type="button" className="link-button" onClick={onUnlock}>
        Change the plan
      </button>
    </section>
  );
}
