/**
 * How the round — and the test — ended (JQ-311 AC 5, and Ryan's 2026-09-13
 * correction).
 *
 * The correction is the whole design of this screen: an ordinary round ending
 * and a base coming down are *different events*, and reporting them the same way
 * misstates the central rule of the game. So the headline names which one
 * happened, the rule is spelled out in one line beneath it, and both bases'
 * remaining HP is on screen — because base damage carries into the next round
 * and is therefore part of the result, not decoration.
 *
 * The opening demo plays one round. That is a fact about the test, not about the
 * game, and the screen says so rather than implying a one-round match.
 */

import type { BaseHp, MatchResult, RoundResult, Side } from './types.ts';
import { opposing } from './types.ts';

const MATCH_RULE =
  'Win three rounds, or destroy the enemy base. Base damage carries between rounds.';

export interface ResultScreenProps {
  readonly result: MatchResult;
  readonly you: Side;
  readonly testProfile: boolean;
  readonly onNewTest: () => void;
  readonly onReturnToLobby: () => void;
  readonly lobbyUrl: string | null;
}

export function ResultScreen({
  result,
  you,
  testProfile,
  onNewTest,
  onReturnToLobby,
  lobbyUrl,
}: ResultScreenProps) {
  const them = opposing(you);
  const { headline, detail } = describe(result, result.lastRound, you);

  return (
    <section className="result" aria-label="Result">
      <header className="result-header">
        {testProfile ? <p className="result-profile">Test profile · single round</p> : null}
        <h1 data-testid="result-headline">{headline}</h1>
        <p className="result-detail" data-testid="result-detail">
          {detail}
        </p>
      </header>

      <dl className="result-bases" data-testid="result-bases">
        <BaseRow label="Your base" hp={result.baseHp[you]} />
        <BaseRow label="Their base" hp={result.baseHp[them]} />
      </dl>

      <p className="result-score">
        {`Zone score ${result.lastRound.zoneScore[you]} – ${result.lastRound.zoneScore[them]} · rounds ${result.roundsWon[you]} – ${result.roundsWon[them]}`}
      </p>

      <p className="result-rule">{MATCH_RULE}</p>

      <div className="result-actions">
        <button type="button" className="primary-button" onClick={onNewTest}>
          New test
        </button>
        {lobbyUrl ? (
          <a className="link-button" href={lobbyUrl}>
            Return to Lobby
          </a>
        ) : (
          <button type="button" className="link-button" onClick={onReturnToLobby}>
            Return to Lobby
          </button>
        )}
      </div>
    </section>
  );
}

function BaseRow({ label, hp }: { readonly label: string; readonly hp: BaseHp }) {
  const share = Math.max(0, hp.hp / hp.maxHp);
  return (
    <div className={hp.hp <= 0 ? 'result-base is-destroyed' : 'result-base'}>
      <dt>{label}</dt>
      <dd>
        <span className="result-base-bar" aria-hidden="true">
          <span className="result-base-fill" style={{ width: `${share * 100}%` }} />
        </span>
        {hp.hp <= 0 ? 'Destroyed' : `${Math.round(hp.hp)} / ${hp.maxHp}`}
      </dd>
    </div>
  );
}

const ROUND_REASON: Record<'zoneControl' | 'annihilation' | 'timeUp', string> = {
  zoneControl: 'on zone control',
  annihilation: 'by wiping the field',
  timeUp: 'on the clock',
};

function describe(
  result: MatchResult,
  round: RoundResult,
  you: Side,
): { headline: string; detail: string } {
  if (result.ending.kind === 'baseDestroyed') {
    const won = result.ending.winner === you;
    return {
      headline: won ? 'Their base is down — you win' : 'Your base is down — you lose',
      // Not "you won round 1": a destroyed base is not a round win that happens
      // to be decisive, it is the match ending on the spot.
      detail: won
        ? 'Destroying a base ends the match immediately. It does not wait for three rounds.'
        : 'A destroyed base ends the match immediately — the remaining rounds are not played.',
    };
  }

  if (result.ending.kind === 'roundsWon') {
    return {
      headline: result.ending.winner === you ? 'You win the match' : 'They win the match',
      detail: 'Three rounds taken.',
    };
  }

  if (result.ending.kind === 'abandoned') {
    return { headline: 'The match ended early', detail: 'One seat left before the match finished.' };
  }

  const reason =
    round.ending.kind === 'roundComplete' ? ROUND_REASON[round.ending.reason] : 'on zone control';
  const winner = result.ending.roundWinner;
  const headline =
    winner === null
      ? `Round ${round.round} drawn`
      : winner === you
        ? `Round ${round.round} to you`
        : `Round ${round.round} to them`;

  return {
    headline,
    detail: `Decided ${reason}. This test stops after one round — a full match runs on.`,
  };
}
