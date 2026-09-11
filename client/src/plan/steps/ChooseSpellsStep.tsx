/**
 * Step 2 — choose spells (JQ-293).
 *
 * Both slots are re-picked each round and keep their previous choice while it is
 * still legal (§10 #32, decided 2026-09-11 over the anchor+flex alternative: an
 * anchor slot puts a match-long choice in round 1, which §3.2 rules out).
 *
 * Ineligible spells stay on the menu, greyed, with the reason. Hiding them would
 * hide the mage-to-spell link that is the whole reason troops are chosen first.
 */

import { spellMenu, strandedSlots } from '../derive.ts';
import type { PlanAction } from '../planReducer.ts';
import type { PlanState } from '../types.ts';

export interface ChooseSpellsStepProps {
  readonly plan: PlanState;
  readonly dispatch: (action: PlanAction) => void;
}

export function ChooseSpellsStep({ plan, dispatch }: ChooseSpellsStepProps) {
  const menu = spellMenu(plan);
  const stranded = strandedSlots(plan);

  return (
    <>
      <p className="step-lede">
        Two slots, both re-picked each round. Energy {plan.energy}.
      </p>

      <ul className="spell-slots">
        {plan.spellSlots.map((spellId, index) => {
          const slot = index as 0 | 1;
          const spell = plan.roster.spells.find((candidate) => candidate.id === spellId);
          const isStranded = stranded.includes(index);

          return (
            <li
              key={slot}
              className={isStranded ? 'spell-slot needs-replacement' : 'spell-slot'}
              data-testid={`spell-slot-${slot}`}
            >
              <span className="slot-index">Slot {slot + 1}</span>
              {isStranded ? (
                <span className="slot-name">NEEDS REPLACEMENT</span>
              ) : (
                <span className="slot-name">{spell?.name ?? 'Empty'}</span>
              )}
              {spellId !== null ? (
                <button
                  type="button"
                  className="link-button"
                  onClick={() => dispatch({ type: 'clearSpell', slot })}
                >
                  Clear
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>

      <ul className="spell-menu">
        {menu.map(({ spell, eligible, reason, affordable }) => {
          const equippedSlot = plan.spellSlots.indexOf(spell.id);

          return (
            <li key={spell.id} className={eligible ? 'spell' : 'spell is-ineligible'}>
              <div className="spell-head">
                <span className="spell-name">{spell.name}</span>
                <span className={affordable ? 'spell-cost' : 'spell-cost is-unaffordable'}>
                  {spell.cost}
                </span>
              </div>
              <p className="spell-text">{spell.text}</p>
              {reason ? <p className="spell-reason">{reason}</p> : null}

              <div className="spell-actions">
                {([0, 1] as const).map((slot) => (
                  <button
                    key={slot}
                    type="button"
                    className="link-button"
                    disabled={!eligible || equippedSlot === slot}
                    onClick={() => dispatch({ type: 'equipSpell', slot, spellId: spell.id })}
                  >
                    {equippedSlot === slot ? `In slot ${slot + 1}` : `Slot ${slot + 1}`}
                  </button>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
