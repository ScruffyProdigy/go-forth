/**
 * The entourage drill-down (JQ-293).
 *
 * A drill-down on a troop already chosen, pre-filled from last round — in round
 * 1, from the Starter's suggested lineup. Reached from the troop card and never
 * required: a player who never opens this still has a complete plan.
 */

import { remainingSummons, troopCapacity } from '../derive.ts';
import type { PlanAction } from '../planReducer.ts';
import type { PlanState } from '../types.ts';

export interface TroopDetailProps {
  readonly plan: PlanState;
  readonly mageId: string;
  readonly dispatch: (action: PlanAction) => void;
  readonly onDone: () => void;
}

export function TroopDetail({ plan, mageId, dispatch, onDone }: TroopDetailProps) {
  const troop = plan.troops.find((candidate) => candidate.mageId === mageId);
  const mage = plan.roster.mages.find((candidate) => candidate.id === mageId);
  if (!troop || !mage) return null;

  const capacity = troopCapacity(plan, troop);
  const remaining = remainingSummons(plan);

  return (
    <section className="troop-detail" aria-label={`${mage.name}'s summons`}>
      <header className="step-header">
        <button type="button" className="link-button" onClick={onDone}>
          Back
        </button>
        <div className="step-title">
          <h2>{mage.name}</h2>
          <p className="step-count">
            {capacity.used} of {capacity.capacity} support used
            {capacity.unsupported > 0 ? ` · ${capacity.unsupported} unsupported` : ''}
          </p>
        </div>
        <span className="step-header-spacer" />
      </header>

      <div className="step-body">
        <h3 className="detail-heading">Supporting</h3>
        {troop.summonIds.length === 0 ? (
          <p className="detail-empty">Nothing summoned. This mage stands alone.</p>
        ) : (
          <ul className="summon-list">
            {troop.summonIds.map((summonId, index) => (
              <li key={`${summonId}-${index}`}>
                <span>{plan.roster.summons[summonId]?.name ?? summonId}</span>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => dispatch({ type: 'removeSummon', mageId, summonId })}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <h3 className="detail-heading">Available</h3>
        <ul className="summon-list">
          {Object.values(plan.roster.summons).map((summon) => {
            const left = remaining[summon.id] ?? 0;
            const fits = summon.capacityCost <= capacity.unsupported;

            return (
              <li key={summon.id}>
                <span>
                  {summon.name}
                  <span className="summon-meta">
                    {summon.role}
                    {summon.capacityCost > 1 ? ` · large (${summon.capacityCost})` : ''} · {left} left
                  </span>
                </span>
                <button
                  type="button"
                  className="link-button"
                  disabled={left <= 0 || !fits}
                  onClick={() => dispatch({ type: 'addSummon', mageId, summonId: summon.id })}
                >
                  Add
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
