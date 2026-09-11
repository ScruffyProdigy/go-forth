/**
 * Step 1 — choose troops (JQ-293).
 *
 * A mage arrives with the summons it supports, so each card is a mage *with its
 * default entourage* and one tap fields the whole shape. Customising the
 * entourage is a drill-down on a troop already chosen (§3.2) — never something
 * the player has to do before they can field anything.
 */

import { atMageCap, isFielded, remainingSummons, troopCapacity } from '../derive.ts';
import type { PlanAction } from '../planReducer.ts';
import type { MageOption, PlanState } from '../types.ts';

export interface ChooseTroopsStepProps {
  readonly plan: PlanState;
  readonly dispatch: (action: PlanAction) => void;
  readonly onCustomise: (mageId: string) => void;
}

export function ChooseTroopsStep({ plan, dispatch, onCustomise }: ChooseTroopsStepProps) {
  const capReached = atMageCap(plan);

  return (
    <>
      <p className="step-lede">
        Fielding a mage fields the summons it supports. {plan.troops.length} of {plan.mageCap}{' '}
        mages.
      </p>

      <ul className="mage-list">
        {plan.roster.mages.map((mage) => (
          <MageCard
            key={mage.id}
            mage={mage}
            plan={plan}
            capReached={capReached}
            dispatch={dispatch}
            onCustomise={onCustomise}
          />
        ))}
      </ul>
    </>
  );
}

function MageCard({
  mage,
  plan,
  capReached,
  dispatch,
  onCustomise,
}: {
  readonly mage: MageOption;
  readonly plan: PlanState;
  readonly capReached: boolean;
  readonly dispatch: (action: PlanAction) => void;
  readonly onCustomise: (mageId: string) => void;
}) {
  const fielded = isFielded(plan, mage.id);
  const troop = plan.troops.find((candidate) => candidate.mageId === mage.id);
  const entourage = troop
    ? troop.summonIds
    : mage.defaultEntourage.filter((summonId) => (remainingSummons(plan)[summonId] ?? 0) > 0);
  const capacity = troop ? troopCapacity(plan, troop) : undefined;

  return (
    <li className={fielded ? 'mage-card is-fielded' : 'mage-card'} data-testid={`mage-${mage.id}`}>
      <button
        type="button"
        className="mage-card-main"
        aria-pressed={fielded}
        disabled={!fielded && capReached}
        onClick={() =>
          dispatch(fielded ? { type: 'unfieldMage', mageId: mage.id } : { type: 'fieldMage', mageId: mage.id })
        }
      >
        <span className="mage-name">{mage.name}</span>
        <span className="mage-tags">{mage.tags.join(' · ')}</span>
        <span className="entourage" aria-label={`${entourage.length} summons`}>
          {entourage.map((summonId, index) => (
            <span key={`${summonId}-${index}`} className={`summon-pip role-${plan.roster.summons[summonId]?.role}`}>
              {plan.roster.summons[summonId]?.name ?? summonId}
            </span>
          ))}
        </span>
      </button>

      {fielded && capacity ? (
        <button
          type="button"
          className="link-button entourage-edit"
          // Named per mage: a round at the cap puts three of these on screen,
          // and "Customise" alone does not say whose summons it opens.
          aria-label={
            capacity.unsupported > 0
              ? `Customise ${mage.name} — ${capacity.unsupported} unsupported`
              : `Customise ${mage.name} — ${capacity.used} of ${capacity.capacity} support used`
          }
          onClick={() => onCustomise(mage.id)}
        >
          {capacity.unsupported > 0
            ? `Customise · ${capacity.unsupported} unsupported`
            : `Customise · ${capacity.used}/${capacity.capacity}`}
        </button>
      ) : null}
    </li>
  );
}
