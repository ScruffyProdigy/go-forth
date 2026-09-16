/**
 * Tap a unit, get the thing you were actually asking about (JQ-312 AC 2).
 *
 * This replaces per-unit health bars. At twenty a side those are forty moving
 * two-pixel rectangles, and forty of anything on a 375 px board is texture: you
 * cannot read one, and their sum tells you nothing the unit count does not. The
 * questions a player really asks are about *one* unit — what is that, is it
 * nearly dead, is its ability about to go off — so the board stays clean and the
 * answer arrives on demand.
 *
 * It sits below the map rather than floating over the tapped unit. A popover at
 * the tap point lands under the thumb that summoned it, which on a phone means
 * the player has to move their hand to read it.
 */

import type { BattleUnit, Side } from '../types.ts';
import { RING_THRESHOLD } from './marks.ts';

export interface UnitInspectorProps {
  readonly unit: BattleUnit;
  readonly you: Side;
  readonly onClose: () => void;
}

export function UnitInspector({ unit, you, onClose }: UnitInspectorProps) {
  const mine = unit.side === you;
  const share = unit.maxHp > 0 ? Math.max(0, unit.hp / unit.maxHp) : 0;
  const charge = unit.ability?.charge;

  return (
    <aside
      className={mine ? 'unit-inspector is-yours' : 'unit-inspector is-theirs'}
      aria-label={`${unit.typeName}, ${mine ? 'yours' : 'theirs'}`}
      data-testid="unit-inspector"
    >
      <header>
        <span className="inspector-name">{unit.typeName}</span>
        <span className="inspector-side">{mine ? 'Yours' : 'Theirs'}</span>
        <button type="button" className="inspector-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>

      <p className="inspector-health" data-testid="inspector-health">
        <span className="inspector-health-track">
          <span className="inspector-health-fill" style={{ width: `${share * 100}%` }} />
        </span>
        {`${Math.round(unit.hp)} / ${unit.maxHp}`}
        {/* Protection is stated only when the server stated it. An absent value
            shown as "0" would be the client inventing a fact the preview
            deliberately refuses to invent. */}
        {unit.protection !== undefined ? ` · ${unit.protection} protection` : null}
      </p>

      {unit.ability ? (
        <p className="inspector-ability" data-testid="inspector-ability">
          <span className="inspector-ability-name">{unit.ability.name}</span>
          <span className="inspector-ability-charge">
            {charge !== undefined && charge >= 1
              ? 'ready'
              : `${Math.round((charge ?? 0) * 100)}% charged`}
          </span>
          {charge !== undefined && charge >= RING_THRESHOLD && charge < 1 ? (
            <span className="inspector-ability-soon">about to fire</span>
          ) : null}
        </p>
      ) : (
        <p className="inspector-ability is-none">No ability.</p>
      )}
    </aside>
  );
}
