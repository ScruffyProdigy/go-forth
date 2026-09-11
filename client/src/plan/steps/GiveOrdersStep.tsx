/**
 * Step 3 — give orders (JQ-293).
 *
 * One order per troop, by tap. Orders also decide placement and formation, so
 * changing one moves that troop on the board immediately — which is visible
 * without leaving the step, via the frame's Board toggle.
 */

import { ORDER_CHOICES, orderLabel, sameOrder } from '../derive.ts';
import type { PlanAction } from '../planReducer.ts';
import type { PlanState } from '../types.ts';

export interface GiveOrdersStepProps {
  readonly plan: PlanState;
  readonly dispatch: (action: PlanAction) => void;
}

export function GiveOrdersStep({ plan, dispatch }: GiveOrdersStepProps) {
  return (
    <>
      <p className="step-lede">Where each troop goes. Tap Board to see it.</p>

      <ul className="order-list">
        {plan.troops.map((troop) => {
          const mage = plan.roster.mages.find((candidate) => candidate.id === troop.mageId);

          return (
            <li key={troop.mageId} className="order-row">
              <span className="order-troop">{mage?.name ?? troop.mageId}</span>
              <div
                className="order-choices"
                role="group"
                aria-label={`Order for ${mage?.name ?? troop.mageId}`}
              >
                {ORDER_CHOICES.map((order) => {
                  const chosen = sameOrder(order, troop.order);
                  return (
                    <button
                      key={orderLabel(order)}
                      type="button"
                      className={chosen ? 'order-choice is-chosen' : 'order-choice'}
                      aria-pressed={chosen}
                      onClick={() => dispatch({ type: 'setOrder', mageId: troop.mageId, order })}
                    >
                      {orderLabel(order)}
                    </button>
                  );
                })}
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
