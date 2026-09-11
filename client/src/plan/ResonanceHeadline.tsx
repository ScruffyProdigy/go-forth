/**
 * Resonance is the plan phase's headline number (JQ-293).
 *
 * It updates live as mages are fielded, so the decision and its consequence sit
 * on the same screen rather than the player discovering the cost in the battle.
 */

import {
  armyCapacity,
  RESONANCE_TIER_LABEL,
  resonance,
  type SchoolResonance,
} from './derive.ts';
import type { PlanState } from './types.ts';

function schoolName(school: SchoolResonance['school']): string {
  return school.toUpperCase();
}

export function ResonanceHeadline({ plan }: { readonly plan: PlanState }) {
  const schools = resonance(plan);
  const headline = schools[0];
  const { capacity, used, unsupported } = armyCapacity(plan);

  return (
    <div className="resonance" data-testid="resonance-headline">
      <div className="resonance-main">
        <span className="resonance-label">Resonance</span>
        {headline ? (
          <span className="resonance-value">
            <strong>{schoolName(headline.school)}</strong> {headline.mageCount}
            <span className={`resonance-tier tier-${headline.tier}`}>
              {RESONANCE_TIER_LABEL[headline.tier]}
            </span>
          </span>
        ) : (
          <span className="resonance-value resonance-empty">No mages fielded</span>
        )}
      </div>

      {schools.length > 1 ? (
        <ul className="resonance-others">
          {schools.slice(1).map((entry) => (
            <li key={entry.school}>
              {schoolName(entry.school)} {entry.mageCount} · {RESONANCE_TIER_LABEL[entry.tier]}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="capacity" data-testid="support-capacity">
        <span className="capacity-label">Support</span>
        <span className="capacity-bar" aria-hidden="true">
          {Array.from({ length: capacity }, (_, index) => (
            <span key={index} className={index < used ? 'pip pip-filled' : 'pip pip-empty'} />
          ))}
        </span>
        <span className="capacity-count">
          {used}/{capacity}
        </span>
        {unsupported > 0 ? (
          <span className="capacity-unsupported">{unsupported} unsupported</span>
        ) : null}
      </div>
    </div>
  );
}
