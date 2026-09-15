/**
 * The states that are not the game (JQ-311 AC 4).
 *
 * Loading, a refused seat, and a session we have left. They get real screens
 * rather than a spinner and a shrug because "legible" is the acceptance
 * criterion: a player who cannot claim a seat needs to know whether waiting will
 * help, and one who left needs a way back.
 */

import type { ScenarioId } from './fixtures/scenarios.ts';
import { SCENARIO_IDS, scenario } from './fixtures/scenarios.ts';

export function ConnectingScreen() {
  return (
    <section className="connecting" aria-label="Connecting">
      <h1>Taking your seat…</h1>
      <p className="connecting-note">Claiming your seat in the match.</p>
    </section>
  );
}

export interface ClaimFailedScreenProps {
  readonly reason: string;
  readonly retryable: boolean;
  readonly onRetry: () => void;
  readonly lobbyUrl: string | null;
}

export function ClaimFailedScreen({
  reason,
  retryable,
  onRetry,
  lobbyUrl,
}: ClaimFailedScreenProps) {
  return (
    <section className="claim-failed" aria-label="Could not join">
      <h1>Could not join</h1>
      <p className="claim-reason" data-testid="claim-reason">
        {reason}
      </p>
      <p className="claim-advice">
        {retryable
          ? 'This usually clears on its own. Try again.'
          : 'This seat cannot be claimed. Go back to the Lobby and start again.'}
      </p>
      <div className="result-actions">
        {retryable ? (
          <button type="button" className="primary-button" onClick={onRetry}>
            Try again
          </button>
        ) : null}
        {lobbyUrl ? (
          <a className="link-button" href={lobbyUrl}>
            Return to Lobby
          </a>
        ) : null}
      </div>
    </section>
  );
}

export interface LeftScreenProps {
  readonly onNewTest: () => void;
  readonly lobbyUrl: string | null;
}

export function LeftScreen({ onNewTest, lobbyUrl }: LeftScreenProps) {
  return (
    <section className="left-match" aria-label="Left the match">
      <h1>You left the match</h1>
      <p className="connecting-note">Nothing is running. A new test starts a fresh run.</p>
      <div className="result-actions">
        <button type="button" className="primary-button" onClick={onNewTest}>
          New test
        </button>
        {lobbyUrl ? (
          <a className="link-button" href={lobbyUrl}>
            Return to Lobby
          </a>
        ) : null}
      </div>
    </section>
  );
}

export interface ScenarioPickerProps {
  readonly current: ScenarioId;
  readonly onPick: (id: ScenarioId) => void;
}

/**
 * Fixture-only. Every state JQ-311 has to make legible needs to be reachable by
 * someone reviewing it, and a real server cannot be asked to drop a connection
 * on cue. This goes when JQ-309 lands, along with `fixtures/`.
 */
export function ScenarioPicker({ current, onPick }: ScenarioPickerProps) {
  return (
    <section className="scenario-picker" aria-label="Fixture run">
      <h2>Fixture run</h2>
      <ul>
        {SCENARIO_IDS.map((id) => {
          const option = scenario(id);
          return (
            <li key={id}>
              <button
                type="button"
                className={id === current ? 'scenario-option is-current' : 'scenario-option'}
                aria-pressed={id === current}
                onClick={() => onPick(id)}
              >
                <span className="scenario-label">{option.label}</span>
                <span className="scenario-summary">{option.summary}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
