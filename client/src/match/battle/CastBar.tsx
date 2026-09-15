/**
 * Tap a spell, then tap where it goes (JQ-311 AC 3).
 *
 * Two taps, both cancellable, with nothing happening on the board until the
 * server says it did. The client is not allowed to draw the effect early: a
 * spell that appears and then vanishes because the server refused it is worse
 * than one that takes 180 ms to appear, and it would be the client simulating
 * ahead of the sim, which this codebase does not do anywhere.
 *
 * Affordability is shown as a number, not a disabled button with no explanation
 * — "needs 3, you have 1.4" tells a player to wait, which is the actual move.
 */

import type { LoadoutSpell } from '../types.ts';

export interface CastBarProps {
  readonly loadout: readonly LoadoutSpell[];
  readonly energy: number;
  /** Which spell is waiting for a target. Its prompt and Cancel live on the map. */
  readonly armed: LoadoutSpell | null;
  readonly onArm: (spell: LoadoutSpell) => void;
  /** The last thing the server said about a cast. */
  readonly feedback: string | null;
  readonly disabled?: boolean;
}

export function CastBar({
  loadout,
  energy,
  armed,
  onArm,
  feedback,
  disabled = false,
}: CastBarProps) {
  return (
    <section className="cast-bar" aria-label="Spells">
      <div className="cast-bar-head">
        <span className="cast-energy" data-testid="cast-energy">
          Energy {energy.toFixed(1)}
        </span>
      </div>

      <ul className="cast-spells">
        {loadout.length === 0 ? (
          <li className="cast-empty">No spells this round.</li>
        ) : null}
        {loadout.map((spell) => {
          const affordable = energy >= spell.cost;
          const isArmed = armed?.spellId === spell.spellId;

          return (
            <li key={spell.spellId}>
              <button
                type="button"
                className={isArmed ? 'cast-spell is-armed' : 'cast-spell'}
                aria-pressed={isArmed}
                disabled={disabled || !affordable}
                onClick={() => onArm(spell)}
              >
                <span className="cast-spell-name">{spell.name}</span>
                <span className={affordable ? 'cast-spell-cost' : 'cast-spell-cost is-short'}>
                  {affordable
                    ? `${spell.cost}`
                    : `needs ${spell.cost} · you have ${energy.toFixed(1)}`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {/* Polite, not assertive: a rejection is worth reading, not worth
          interrupting a screen reader mid-sentence for. */}
      <p className="cast-feedback" role="status" aria-live="polite" data-testid="cast-feedback">
        {feedback ?? ''}
      </p>
    </section>
  );
}
